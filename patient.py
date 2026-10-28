from flask import Blueprint, render_template
from flask_login import current_user

from models import APPT_SELECT, can_cancel, get_db, now_str
from flask import current_app
from utils import role_required

bp = Blueprint("patient", __name__)


def decorate(rows):
    hours = current_app.config["CANCEL_MIN_HOURS"]
    return [dict(r, can_cancel=can_cancel(r, hours)) for r in rows]


@bp.route("/painel")
@role_required("patient", "auth.login")
def dashboard():
    rows = decorate(get_db().execute(
        APPT_SELECT + " WHERE a.patient_id = ? ORDER BY a.start_at", (current_user.id,)).fetchall())
    now = now_str()
    upcoming = [r for r in rows if r["status"] == "scheduled" and r["start_at"] >= now]
    history = [r for r in reversed(rows) if r not in upcoming]
    return render_template("patient_dashboard.html", upcoming=upcoming, history=history)


@bp.route("/perfil")
@role_required("patient", "auth.login")
def profile():
    return render_template("profile.html")
