import sqlite3
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import APPT_SELECT, get_db, now_str
from utils import audit, only_digits, role_required, WEEKDAYS

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_only = role_required("admin", "auth.admin_login")


@bp.route("/")
@admin_only
def dashboard():
    db = get_db()
    today, now = date.today().isoformat(), now_str()
    one = lambda sql, *p: db.execute(sql, p).fetchone()[0]  # noqa: E731
    stats = {
        "today": one("SELECT COUNT(*) FROM appointments WHERE substr(start_at,1,10) = ? AND status <> 'cancelled'", today),
        "future": one("SELECT COUNT(*) FROM appointments WHERE status = 'scheduled' AND start_at > ?", now),
        "cancelled": one("SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'"),
        "doctors": one("SELECT COUNT(*) FROM doctors WHERE is_active = 1"),
        "patients": one("SELECT COUNT(*) FROM users WHERE role = 'patient'"),
    }
    upcoming = db.execute(APPT_SELECT + " WHERE a.status = 'scheduled' AND a.start_at >= ? ORDER BY a.start_at LIMIT 10",
                          (today,)).fetchall()
    logs = db.execute("SELECT l.*, u.name AS admin_name FROM admin_audit_logs l JOIN users u ON u.id = l.admin_id "
                      "ORDER BY l.id DESC LIMIT 8").fetchall()
    return render_template("admin_dashboard.html", stats=stats, upcoming=upcoming, logs=logs)


# ------------------------------------------------------------ consultas
@bp.route("/consultas")
@admin_only
def appointments():
    f = {k: (request.args.get(k) or "").strip() for k in ("patient", "doctor", "date", "status")}
    f["specialty_id"] = request.args.get("specialty_id", type=int)
    sql, params = APPT_SELECT + " WHERE 1=1", []
    if f["patient"]:
        sql += " AND u.name LIKE ?"; params.append(f"%{f['patient']}%")
    if f["doctor"]:
        sql += " AND d.name LIKE ?"; params.append(f"%{f['doctor']}%")
    if f["specialty_id"]:
        sql += " AND s.id = ?"; params.append(f["specialty_id"])
    if f["date"]:
        sql += " AND substr(a.start_at,1,10) = ?"; params.append(f["date"])
    if f["status"] in ("scheduled", "cancelled", "completed"):
        sql += " AND a.status = ?"; params.append(f["status"])
    db = get_db()
    rows = db.execute(sql + " ORDER BY a.start_at DESC LIMIT 300", params).fetchall()
    specialties = db.execute("SELECT * FROM specialties ORDER BY name").fetchall()
    return render_template("admin_appointments.html", rows=rows, f=f, specialties=specialties)


@bp.route("/consultas/<int:appt_id>")
@admin_only
def appointment_detail(appt_id):
    row = get_db().execute(APPT_SELECT + " WHERE a.id = ?", (appt_id,)).fetchone()
    if row is None:
        abort(404)
    return render_template("appointment_detail.html", a=dict(row, can_cancel=False), admin=True)


def _change_status(appt_id, new_status, action, ok_msg):
    cancelled_at = now_str() if new_status == "cancelled" else None
    changed = get_db().execute(
        "UPDATE appointments SET status = ?, cancelled_at = COALESCE(?, cancelled_at) "
        "WHERE id = ? AND status = 'scheduled'", (new_status, cancelled_at, appt_id)).rowcount
    if changed:
        audit(action, "appointment", appt_id)
        flash(ok_msg, "success")
    else:
        flash("Somente consultas agendadas podem ser alteradas.", "error")
    return redirect(request.referrer or url_for("admin.appointments"))


@bp.route("/consultas/<int:appt_id>/cancelar", methods=["POST"])
@admin_only
def cancel_appointment(appt_id):
    return _change_status(appt_id, "cancelled", "cancel_appointment", "Consulta cancelada e horário liberado.")


@bp.route("/consultas/<int:appt_id>/concluir", methods=["POST"])
@admin_only
def complete_appointment(appt_id):
    return _change_status(appt_id, "completed", "complete_appointment", "Consulta marcada como concluída.")


# -------------------------------------------------------------- médicos
@bp.route("/medicos")
@admin_only
def doctors():
    rows = get_db().execute("SELECT d.*, s.name AS specialty_name FROM doctors d JOIN specialties s "
                            "ON s.id = d.specialty_id ORDER BY d.is_active DESC, d.name").fetchall()
    return render_template("admin_doctors.html", doctors=rows)


def _parse_doctor(db, form):
    errors = []
    d = {k: (form.get(k) or "").strip() for k in
         ("name", "crm", "specialty_id", "bio", "experience_years", "photo", "consultation_duration")}
    d["is_active"] = 1 if form.get("is_active") else 0
    if len(d["name"]) < 3:
        errors.append("Informe o nome do médico.")
    if not d["specialty_id"].isdigit() or not db.execute("SELECT 1 FROM specialties WHERE id = ?", (d["specialty_id"],)).fetchone():
        errors.append("Selecione uma especialidade válida.")
    if len(d["bio"]) > 600:
        errors.append("A biografia deve ter até 600 caracteres.")
    if d["experience_years"] and not (d["experience_years"].isdigit() and int(d["experience_years"]) <= 70):
        errors.append("Anos de experiência inválidos.")
    if not (d["consultation_duration"].isdigit() and 5 <= int(d["consultation_duration"]) <= 240):
        errors.append("A duração da consulta deve estar entre 5 e 240 minutos.")
    if d["photo"] and not d["photo"].startswith(("http://", "https://")):
        errors.append("A foto deve ser uma URL http(s) ou ficar em branco.")
    sched = {}
    for wd in range(7):
        s = {"on": bool(form.get(f"d{wd}_on")), "start": (form.get(f"d{wd}_start") or "08:00").strip(),
             "end": (form.get(f"d{wd}_end") or "12:00").strip(), "interval": (form.get(f"d{wd}_interval") or "30").strip()}
        sched[wd] = s
        if s["on"]:
            try:
                ok = datetime.strptime(s["start"], "%H:%M") < datetime.strptime(s["end"], "%H:%M")
            except ValueError:
                ok = False
            if not ok or not (s["interval"].isdigit() and 5 <= int(s["interval"]) <= 240):
                errors.append(f"Agenda de {WEEKDAYS[wd]} inválida (início antes do fim; intervalo de 5 a 240 min).")
    return d, sched, errors


def _save_doctor(db, doctor_id, d, sched):
    db.execute("BEGIN IMMEDIATE")
    try:
        values = (d["name"], d["crm"] or None, int(d["specialty_id"]), d["bio"] or None,
                  int(d["experience_years"]) if d["experience_years"] else None, d["photo"] or None,
                  int(d["consultation_duration"]), d["is_active"])
        if doctor_id:
            db.execute("UPDATE doctors SET name=?, crm=?, specialty_id=?, bio=?, experience_years=?, photo=?, "
                       "consultation_duration=?, is_active=? WHERE id=?", values + (doctor_id,))
            db.execute("DELETE FROM doctor_schedules WHERE doctor_id = ?", (doctor_id,))
        else:
            doctor_id = db.execute("INSERT INTO doctors (name, crm, specialty_id, bio, experience_years, photo, "
                                   "consultation_duration, is_active) VALUES (?,?,?,?,?,?,?,?)", values).lastrowid
        for wd, s in sched.items():
            if s["on"]:
                db.execute("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time, slot_interval) "
                           "VALUES (?,?,?,?,?)", (doctor_id, wd, s["start"], s["end"], int(s["interval"])))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return doctor_id


def _doctor_form(doctor_id=None):
    db = get_db()
    existing = None
    if doctor_id:
        existing = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        if existing is None:
            abort(404)
    specialties = db.execute("SELECT * FROM specialties ORDER BY name").fetchall()
    if request.method == "POST":
        d, sched, errors = _parse_doctor(db, request.form)
        if not errors:
            saved = _save_doctor(db, doctor_id, d, sched)
            audit("update_doctor" if doctor_id else "create_doctor", "doctor", saved)
            flash("Médico salvo com sucesso.", "success")
            return redirect(url_for("admin.doctors"))
        for e in errors:
            flash(e, "error")
        status = 400
    else:
        status = 200
        if existing:
            d = {k: ("" if existing[k] is None else str(existing[k])) for k in
                 ("name", "crm", "specialty_id", "bio", "experience_years", "photo", "consultation_duration")}
            d["is_active"] = existing["is_active"]
            sched = {wd: {"on": False, "start": "08:00", "end": "12:00", "interval": "30"} for wd in range(7)}
            for s in db.execute("SELECT * FROM doctor_schedules WHERE doctor_id = ? ORDER BY start_time", (doctor_id,)):
                sched[s["weekday"]] = {"on": True, "start": s["start_time"], "end": s["end_time"],
                                       "interval": str(s["slot_interval"])}
        else:
            d = {"name": "", "crm": "", "specialty_id": "", "bio": "", "experience_years": "", "photo": "",
                 "consultation_duration": "30", "is_active": 1}
            sched = {wd: {"on": wd < 5, "start": "08:00", "end": "12:00", "interval": "30"} for wd in range(7)}
    return render_template("admin_doctor_form.html", d=d, sched=sched, specialties=specialties,
                           doctor_id=doctor_id), status


@bp.route("/medicos/novo", methods=["GET", "POST"])
@admin_only
def doctor_new():
    return _doctor_form()


@bp.route("/medicos/<int:doctor_id>/editar", methods=["GET", "POST"])
@admin_only
def doctor_edit(doctor_id):
    return _doctor_form(doctor_id)


@bp.route("/medicos/<int:doctor_id>/alternar", methods=["POST"])
@admin_only
def doctor_toggle(doctor_id):
    db = get_db()
    if not db.execute("UPDATE doctors SET is_active = 1 - is_active WHERE id = ?", (doctor_id,)).rowcount:
        abort(404)
    audit("toggle_doctor", "doctor", doctor_id)
    flash("Status do médico atualizado. Consultas já marcadas não são alteradas.", "success")
    return redirect(url_for("admin.doctors"))


# -------------------------------------------------------- especialidades
@bp.route("/especialidades", methods=["GET", "POST"])
@admin_only
def specialties():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        sid = request.form.get("id", type=int)
        name = (request.form.get("name") or "").strip()
        desc = (request.form.get("description") or "").strip()[:300]
        try:
            if action == "create" and len(name) >= 3:
                new_id = db.execute("INSERT INTO specialties (name, description) VALUES (?,?)", (name, desc)).lastrowid
                audit("create_specialty", "specialty", new_id)
                flash("Especialidade criada.", "success")
            elif action == "update" and sid and len(name) >= 3:
                db.execute("UPDATE specialties SET name = ?, description = ? WHERE id = ?", (name, desc, sid))
                audit("update_specialty", "specialty", sid)
                flash("Especialidade atualizada.", "success")
            elif action == "delete" and sid:
                db.execute("DELETE FROM specialties WHERE id = ?", (sid,))
                audit("delete_specialty", "specialty", sid)
                flash("Especialidade removida.", "success")
            else:
                flash("Dados inválidos (nome com pelo menos 3 caracteres).", "error")
        except sqlite3.IntegrityError:
            flash("Não foi possível concluir: nome já existente ou especialidade em uso por médicos.", "error")
        return redirect(url_for("admin.specialties"))
    rows = db.execute("SELECT s.*, (SELECT COUNT(*) FROM doctors d WHERE d.specialty_id = s.id) AS n_doctors "
                      "FROM specialties s ORDER BY s.name").fetchall()
    return render_template("admin_specialties.html", rows=rows)


# ------------------------------------------------------------- pacientes
@bp.route("/pacientes")
@admin_only
def patients():
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT u.*, (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = u.id) AS n_appts "
           "FROM users u WHERE u.role = 'patient'")
    params = []
    if q:
        sql += " AND (u.name LIKE ? OR u.email LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    rows = get_db().execute(sql + " ORDER BY u.name LIMIT 300", params).fetchall()
    return render_template("admin_patients.html", rows=rows, q=q)
