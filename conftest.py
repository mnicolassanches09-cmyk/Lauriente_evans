import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import create_user, get_db, init_db, seed_demo  # noqa: E402


def make_cpf(base):
    """Gera um CPF válido a partir de 9 dígitos."""
    d = [int(c) for c in f"{base:09d}"]
    for n in (9, 10):
        s = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append((s * 10 % 11) % 10)
    return "".join(map(str, d))


@pytest.fixture
def app(tmp_path):
    # Banco de testes separado do banco de demonstração.
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "SECRET_KEY": "test",
                      "DATABASE": str(tmp_path / "test.db"), "CANCEL_MIN_HOURS": 2})
    with app.app_context():
        init_db()
        seed_demo(get_db())
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def tomorrow():
    return date.today() + timedelta(days=1)


def reg_data(n=1, **over):
    data = {"name": f"Paciente Teste{n}", "cpf": make_cpf(100000000 + n), "birth_date": "1990-05-10",
            "email": f"paciente{n}@teste.local", "phone": "11999990000",
            "password": "senha1234", "confirm_password": "senha1234"}
    data.update(over)
    return data


@pytest.fixture
def register(app):
    def _register(client, n=1, **over):
        return client.post("/cadastro", data=reg_data(n, **over), follow_redirects=True)
    return _register


@pytest.fixture
def login():
    def _login(client, n=1, password="senha1234", email=None):
        return client.post("/entrar", data={"email": email or f"paciente{n}@teste.local", "password": password},
                           follow_redirects=True)
    return _login


@pytest.fixture
def patient(app, register, login):
    """Fábrica de clientes autenticados como pacientes distintos."""
    def _make(n=1):
        c = app.test_client()
        register(c, n)
        login(c, n)
        return c
    return _make


@pytest.fixture
def admin_client(app):
    with app.app_context():
        create_user(get_db(), "Secretaria Teste", "admin@teste.local", "adminsenha123", role="admin")
    c = app.test_client()
    c.post("/admin/entrar", data={"email": "admin@teste.local", "password": "adminsenha123"})
    return c


@pytest.fixture
def make_doctor(app):
    """Cria médico que atende todos os dias 09:00-12:00."""
    def _make(name="Dr. Teste", duration=30, interval=15, active=1):
        with app.app_context():
            db = get_db()
            sid = db.execute("SELECT id FROM specialties LIMIT 1").fetchone()[0]
            did = db.execute("INSERT INTO doctors (name, specialty_id, consultation_duration, is_active) VALUES (?,?,?,?)",
                             (name, sid, duration, active)).lastrowid
            for wd in range(7):
                db.execute("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time, slot_interval) "
                           "VALUES (?,?,?,?,?)", (did, wd, "09:00", "12:00", interval))
            return did
    return _make


def book(client, doctor_id, day, hhmm, follow=True):
    return client.post("/agendar", data={"doctor_id": doctor_id, "start_at": f"{day.isoformat()}T{hhmm}"},
                       follow_redirects=follow)


def count_appts(app, doctor_id=None, status="scheduled"):
    with app.app_context():
        sql, p = "SELECT COUNT(*) FROM appointments WHERE status = ?", [status]
        if doctor_id:
            sql += " AND doctor_id = ?"
            p.append(doctor_id)
        return get_db().execute(sql, p).fetchone()[0]
