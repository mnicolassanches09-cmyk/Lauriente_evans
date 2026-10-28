import re
from datetime import datetime
from functools import wraps

from flask import abort, redirect, request, url_for
from flask_login import current_user

from models import DT_FMT, get_db, now_str

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
STATUS_LABELS = {"scheduled": "Agendada", "cancelled": "Cancelada", "completed": "Concluída"}


def only_digits(value):
    return re.sub(r"\D", "", value or "")


def valid_cpf(value):
    d = only_digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (total * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def home_for(user):
    return url_for("admin.dashboard") if user.role == "admin" else url_for("patient.dashboard")


def role_required(role, login_endpoint):
    """Autorização no servidor: exige login e o papel correto (senão 403)."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for(login_endpoint, next=request.path))
            if current_user.role != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def audit(action, entity_type, entity_id=None):
    """Registra operação administrativa (sem senhas nem dados sensíveis)."""
    get_db().execute(
        "INSERT INTO admin_audit_logs (admin_id, action, entity_type, entity_id, created_at) VALUES (?,?,?,?,?)",
        (current_user.id, action, entity_type, entity_id, now_str()),
    )


def register_filters(app):
    @app.template_filter("br_date")
    def br_date(v):
        return datetime.strptime(v, DT_FMT).strftime("%d/%m/%Y") if v else ""

    @app.template_filter("hm")
    def hm(v):
        return datetime.strptime(v, DT_FMT).strftime("%H:%M") if v else ""

    @app.template_filter("status_label")
    def status_label(v):
        return STATUS_LABELS.get(v, v)

    @app.template_filter("cpf_mask")
    def cpf_mask(v):
        d = only_digits(v)
        return f"•••.{d[3:6]}.{d[6:9]}-••" if len(d) == 11 else "—"

    @app.template_filter("cpf_fmt")
    def cpf_fmt(v):
        d = only_digits(v)
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else "—"

    @app.template_filter("initials")
    def initials(name):
        parts = [p for p in re.sub(r"^(Dr|Dra)\.?\s+", "", name or "").split() if p]
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else (parts[0][:2].upper() if parts else "?")

    app.jinja_env.globals["WEEKDAYS"] = WEEKDAYS
