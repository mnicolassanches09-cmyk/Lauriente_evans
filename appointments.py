from datetime import date, datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import (APPT_SELECT, DT_FMT, BookingError, available_slots, book_appointment,
                    can_cancel, get_db, now_str)
from utils import role_required

bp = Blueprint("appointments", __name__)


@bp.route("/agendar", methods=["GET", "POST"])
@role_required("patient", "auth.login")
def new():
    db = get_db()
    if request.method == "POST":
        return _confirm(db)

    spec_id = request.args.get("specialty_id", type=int)
    doctor_id = request.args.get("doctor_id", type=int)
    doctor = None
    if doctor_id:
        doctor = db.execute("SELECT d.*, s.name AS specialty_name FROM doctors d JOIN specialties s "
                            "ON s.id = d.specialty_id WHERE d.id = ? AND d.is_active = 1", (doctor_id,)).fetchone()
        if doctor and spec_id and doctor["specialty_id"] != spec_id:
            doctor = None
        elif doctor and not spec_id:
            spec_id = doctor["specialty_id"]
    sql, params = "SELECT * FROM doctors WHERE is_active = 1", []
    if spec_id:
        sql += " AND specialty_id = ?"
        params.append(spec_id)
    doctors = db.execute(sql + " ORDER BY name", params).fetchall()
    specialties = db.execute("SELECT * FROM specialties ORDER BY name").fetchall()

    day, slots = None, []
    date_str = request.args.get("date") or ""
    if doctor and date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
            if day < date.today():
                flash("Escolha uma data a partir de hoje.", "error")
                day = None
            else:
                slots = available_slots(db, doctor, day)
        except ValueError:
            flash("Data inválida.", "error")
    return render_template("appointment_form.html", specialties=specialties, doctors=doctors, doctor=doctor,
                           spec_id=spec_id, date_str=date_str if day else "", day=day, slots=slots,
                           today=date.today().isoformat())


def _confirm(db):
    doctor_id = request.form.get("doctor_id", type=int)
    reason = (request.form.get("reason") or "").strip()[:300]
    try:
        start = datetime.strptime(request.form.get("start_at") or "", DT_FMT)
    except ValueError:
        flash("Selecione um horário válido.", "error")
        return redirect(url_for("appointments.new", doctor_id=doctor_id))
    try:
        book_appointment(db, current_user.id, doctor_id, start, reason)
    except BookingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("appointments.new", doctor_id=doctor_id, date=start.date().isoformat()))
    flash("Consulta agendada com sucesso!", "success")
    return redirect(url_for("patient.dashboard"))


@bp.route("/consultas/<int:appt_id>")
@role_required("patient", "auth.login")
def detail(appt_id):
    row = get_db().execute(APPT_SELECT + " WHERE a.id = ? AND a.patient_id = ?", (appt_id, current_user.id)).fetchone()
    if row is None:
        abort(404)  # inexistente ou de outro paciente: mesma resposta
    appt = dict(row, can_cancel=can_cancel(row, current_app.config["CANCEL_MIN_HOURS"]))
    return render_template("appointment_detail.html", a=appt, admin=False)


@bp.route("/consultas/<int:appt_id>/cancelar", methods=["POST"])
@role_required("patient", "auth.login")
def cancel(appt_id):
    db = get_db()
    row = db.execute("SELECT * FROM appointments WHERE id = ? AND patient_id = ?", (appt_id, current_user.id)).fetchone()
    if row is None:
        abort(404)
    if not can_cancel(row, current_app.config["CANCEL_MIN_HOURS"]):
        flash("Esta consulta não pode mais ser cancelada pelo site. Entre em contato com a secretaria.", "error")
        return redirect(url_for("patient.dashboard"))
    changed = db.execute(
        "UPDATE appointments SET status = 'cancelled', cancelled_at = ? "
        "WHERE id = ? AND patient_id = ? AND status = 'scheduled'", (now_str(), appt_id, current_user.id)).rowcount
    flash("Consulta cancelada. O horário foi liberado." if changed else "Esta consulta já não está agendada.",
          "success" if changed else "info")
    return redirect(url_for("patient.dashboard"))
