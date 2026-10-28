import re
import sqlite3
from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user, login_required
from werkzeug.security import check_password_hash

from models import create_user, get_db
from utils import EMAIL_RE, home_for, only_digits, safe_next, valid_cpf

public_bp = Blueprint("public", __name__)
bp = Blueprint("auth", __name__)


@public_bp.route("/")
def index():
    db = get_db()
    specialties = db.execute("SELECT * FROM specialties ORDER BY name").fetchall()
    doctors = db.execute(
        "SELECT d.*, s.name AS specialty_name FROM doctors d JOIN specialties s ON s.id = d.specialty_id "
        "WHERE d.is_active = 1 ORDER BY d.id LIMIT 4").fetchall()
    return render_template("index.html", specialties=specialties, doctors=doctors)


@public_bp.route("/medicos")
def doctors():
    db = get_db()
    spec_id = request.args.get("specialty_id", type=int)
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT d.*, s.name AS specialty_name FROM doctors d JOIN specialties s ON s.id = d.specialty_id "
           "WHERE d.is_active = 1")
    params = []
    if spec_id:
        sql += " AND d.specialty_id = ?"
        params.append(spec_id)
    if q:
        sql += " AND d.name LIKE ?"
        params.append(f"%{q}%")
    rows = db.execute(sql + " ORDER BY d.name", params).fetchall()
    specialties = db.execute("SELECT * FROM specialties ORDER BY name").fetchall()
    return render_template("doctors.html", doctors=rows, specialties=specialties, spec_id=spec_id, q=q)


def _validate_registration(db, f):
    errors = []
    name = " ".join((f.get("name") or "").split())
    cpf = only_digits(f.get("cpf"))
    email = (f.get("email") or "").strip().lower()
    phone = only_digits(f.get("phone"))
    birth = (f.get("birth_date") or "").strip()
    password, confirm = f.get("password") or "", f.get("confirm_password") or ""

    if len(name) < 5 or " " not in name:
        errors.append("Informe seu nome completo.")
    if not valid_cpf(cpf):
        errors.append("CPF inválido.")
    if not EMAIL_RE.match(email) or len(email) > 120:
        errors.append("Informe um e-mail válido.")
    if len(phone) not in (10, 11):
        errors.append("Informe um telefone com DDD (10 ou 11 dígitos).")
    try:
        b = datetime.strptime(birth, "%Y-%m-%d").date()
        if b > date.today() or b.year < date.today().year - 120:
            raise ValueError
    except ValueError:
        errors.append("Informe uma data de nascimento válida.")
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("A senha deve ter pelo menos 8 caracteres, com letras e números.")
    if password != confirm:
        errors.append("As senhas não coincidem.")
    if not errors:
        if db.execute("SELECT 1 FROM users WHERE cpf = ?", (cpf,)).fetchone():
            errors.append("Já existe um cadastro com este CPF.")
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("Já existe um cadastro com este e-mail.")
    return {"name": name, "cpf": cpf, "email": email, "phone": phone, "birth_date": birth,
            "password": password}, errors


@bp.route("/cadastro", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    if request.method == "POST":
        db = get_db()
        data, errors = _validate_registration(db, request.form)
        if not errors:
            try:
                # O papel é sempre "patient": o formulário não consegue criar administradores.
                create_user(db, data["name"], data["email"], data["password"], role="patient",
                            cpf=data["cpf"], phone=data["phone"], birth_date=data["birth_date"])
            except sqlite3.IntegrityError:
                errors.append("Já existe um cadastro com este CPF ou e-mail.")
            else:
                flash("Cadastro realizado com sucesso! Faça login para continuar.", "success")
                return redirect(url_for("auth.login"))
        for e in errors:
            flash(e, "error")
        data.pop("password")
        return render_template("register.html", values=data), 400
    return render_template("register.html", values={})


def _do_login(role, template, fail_endpoint):
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        row = get_db().execute("SELECT * FROM users WHERE email = ? AND role = ?", (email, role)).fetchone()
        if row and row["is_active"] and check_password_hash(row["password_hash"], password):
            from models import User
            login_user(User(row))
            return redirect(safe_next(request.args.get("next")) or home_for(current_user))
        flash("E-mail ou senha inválidos.", "error")
        return render_template(template, email=email), 401
    return render_template(template, email="")


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return _do_login("patient", "login.html", "auth.login")


@bp.route("/admin/entrar", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return _do_login("admin", "admin_login.html", "auth.admin_login")


@bp.route("/sair", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Você saiu da sua conta.", "info")
    return redirect(url_for("public.index"))
