"""Banco de dados (SQLite), modelo de usuário e regras de agenda.

Política de datas: horários são armazenados como texto ISO sem fuso
("YYYY-MM-DDTHH:MM") no horário local do hospital. Nesse formato a ordem
alfabética coincide com a ordem cronológica.
"""
import sqlite3
from datetime import datetime, timedelta

from flask import current_app, g
from flask_login import UserMixin
from werkzeug.security import generate_password_hash

DT_FMT = "%Y-%m-%dT%H:%M"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cpf TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT,
    birth_date TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'patient' CHECK (role IN ('patient','admin')),
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS specialties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    crm TEXT,
    specialty_id INTEGER NOT NULL REFERENCES specialties(id),
    bio TEXT,
    experience_years INTEGER CHECK (experience_years IS NULL OR experience_years >= 0),
    photo TEXT,
    consultation_duration INTEGER NOT NULL DEFAULT 30 CHECK (consultation_duration > 0),
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS doctor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    slot_interval INTEGER NOT NULL CHECK (slot_interval > 0),
    is_active INTEGER NOT NULL DEFAULT 1,
    CHECK (start_time < end_time)
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','cancelled','completed')),
    reason TEXT,
    created_at TEXT NOT NULL,
    cancelled_at TEXT,
    CHECK (start_at < end_at)
);
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments(patient_id, start_at);
CREATE INDEX IF NOT EXISTS ix_appt_doctor ON appointments(doctor_id, start_at);
CREATE INDEX IF NOT EXISTS ix_doctors_spec ON doctors(specialty_id);
CREATE INDEX IF NOT EXISTS ix_sched_doctor ON doctor_schedules(doctor_id, weekday);
-- Rede de proteção no banco: mesmo médico + mesmo início não pode repetir
-- enquanto a consulta não estiver cancelada. A sobreposição parcial é checada
-- na transação (book_appointment).
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_slot
    ON appointments(doctor_id, start_at) WHERE status <> 'cancelled';
"""

APPT_SELECT = """
SELECT a.*, u.name AS patient_name, d.name AS doctor_name, d.crm AS doctor_crm,
       s.name AS specialty_name, s.id AS specialty_id
FROM appointments a
JOIN users u ON u.id = a.patient_id
JOIN doctors d ON d.id = a.doctor_id
JOIN specialties s ON s.id = d.specialty_id
"""


def now_str():
    return datetime.now().strftime(DT_FMT)


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    get_db().executescript(SCHEMA)


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self.cpf = row["cpf"]
        self.phone = row["phone"]
        self.birth_date = row["birth_date"]
        self._active = bool(row["is_active"])

    @property
    def is_active(self):
        return self._active

    @property
    def is_admin(self):
        return self.role == "admin"


def get_user(user_id):
    try:
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    except (TypeError, ValueError):
        return None
    return User(row) if row else None


def create_user(db, name, email, password, role="patient", cpf=None, phone=None, birth_date=None):
    cur = db.execute(
        "INSERT INTO users (name, cpf, email, phone, birth_date, password_hash, role, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (name, cpf, email.lower(), phone, birth_date, generate_password_hash(password), role, now_str()),
    )
    return cur.lastrowid


# ----------------------------------------------------------------- agenda
class BookingError(Exception):
    """Erro de regra de negócio com mensagem amigável."""


def _t(value):
    return datetime.strptime(value, "%H:%M").time()


def available_slots(db, doctor, day):
    """Horários de início livres de um médico em uma data (objeto date)."""
    if not doctor or not doctor["is_active"]:
        return []
    schedules = db.execute(
        "SELECT * FROM doctor_schedules WHERE doctor_id = ? AND weekday = ? AND is_active = 1",
        (doctor["id"], day.weekday()),
    ).fetchall()
    duration = timedelta(minutes=doctor["consultation_duration"])
    lo = datetime.combine(day, datetime.min.time())
    hi = lo + timedelta(days=1)
    busy = [
        (datetime.strptime(r["start_at"], DT_FMT), datetime.strptime(r["end_at"], DT_FMT))
        for r in db.execute(
            "SELECT start_at, end_at FROM appointments "
            "WHERE doctor_id = ? AND status <> 'cancelled' AND start_at < ? AND end_at > ?",
            (doctor["id"], hi.strftime(DT_FMT), lo.strftime(DT_FMT)),
        )
    ]
    now = datetime.now()
    slots = set()
    for s in schedules:
        cur = datetime.combine(day, _t(s["start_time"]))
        end = datetime.combine(day, _t(s["end_time"]))
        step = timedelta(minutes=s["slot_interval"])
        while cur + duration <= end:
            # sobreposição de intervalos: [cur, cur+dur) x [b0, b1)
            if cur > now and not any(b0 < cur + duration and b1 > cur for b0, b1 in busy):
                slots.add(cur)
            cur += step
    return sorted(slots)


def book_appointment(db, patient_id, doctor_id, start, reason=""):
    """Reserva um horário com transação de escrita exclusiva (BEGIN IMMEDIATE).

    A verificação de disponibilidade é refeita dentro da transação, então duas
    requisições simultâneas nunca reservam intervalos que se sobrepõem.
    """
    try:
        db.execute("BEGIN IMMEDIATE")
        doctor = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        if doctor is None or not doctor["is_active"]:
            raise BookingError("Este médico não está disponível para agendamentos.")
        if start <= datetime.now():
            raise BookingError("Não é possível agendar em datas ou horários passados.")
        if start not in available_slots(db, doctor, start.date()):
            raise BookingError("Esse horário não está mais disponível. Escolha outro horário.")
        end = start + timedelta(minutes=doctor["consultation_duration"])
        cur = db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, start_at, end_at, status, reason, created_at) "
            "VALUES (?,?,?,?, 'scheduled', ?, ?)",
            (patient_id, doctor_id, start.strftime(DT_FMT), end.strftime(DT_FMT), reason, now_str()),
        )
        db.execute("COMMIT")
        return cur.lastrowid
    except sqlite3.IntegrityError:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise BookingError("Esse horário não está mais disponível. Escolha outro horário.")
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def can_cancel(appt, min_hours):
    if appt["status"] != "scheduled":
        return False
    start = datetime.strptime(appt["start_at"], DT_FMT)
    return start - datetime.now() >= timedelta(hours=min_hours)


# ------------------------------------------------------------- dados demo
SPECIALTIES = [
    ("Cardiologia", "Prevenção e tratamento de doenças do coração e da circulação."),
    ("Dermatologia", "Cuidados com a pele, cabelos e unhas."),
    ("Ortopedia", "Ossos, articulações, músculos e lesões esportivas."),
    ("Pediatria", "Acompanhamento da saúde de bebês, crianças e adolescentes."),
    ("Neurologia", "Doenças do cérebro, da medula e dos nervos."),
    ("Ginecologia", "Saúde da mulher, prevenção e acompanhamento."),
    ("Oftalmologia", "Saúde dos olhos e correção da visão."),
    ("Endocrinologia", "Diabetes, tireoide e distúrbios hormonais."),
    ("Psiquiatria", "Saúde mental e bem-estar emocional."),
    ("Clínica Geral", "Primeira avaliação, check-ups e acompanhamento geral."),
]
_SEG_SEX, _TER_QUI, _SEG_QUA_SEX = [0, 1, 2, 3, 4], [1, 3], [0, 2, 4]
DOCTORS = [
    ("Dr. Ricardo Alencar", "Cardiologia", 18, 30, [(_SEG_QUA_SEX, "08:00", "12:00", 30)]),
    ("Dra. Helena Duarte", "Dermatologia", 12, 30, [(_TER_QUI, "09:00", "13:00", 30)]),
    ("Dr. Marcelo Bastos", "Ortopedia", 20, 30, [(_SEG_QUA_SEX, "14:00", "18:00", 30)]),
    ("Dra. Camila Ferraz", "Pediatria", 9, 30, [(_SEG_SEX, "08:00", "12:00", 30)]),
    ("Dr. André Salgado", "Neurologia", 15, 45, [(_TER_QUI, "08:00", "12:00", 15)]),
    ("Dra. Beatriz Nogueira", "Ginecologia", 14, 30, [(_SEG_QUA_SEX, "09:00", "12:00", 30), ([1], "14:00", "17:00", 30)]),
    ("Dr. Thiago Valente", "Oftalmologia", 11, 30, [(_SEG_SEX, "13:00", "17:00", 30)]),
    ("Dra. Patrícia Lemos", "Endocrinologia", 16, 30, [(_TER_QUI, "14:00", "18:00", 30)]),
    ("Dr. Fernando Aguiar", "Psiquiatria", 13, 50, [(_SEG_QUA_SEX, "10:00", "16:00", 60)]),
    ("Dra. Juliana Prado", "Clínica Geral", 8, 30, [(_SEG_SEX, "08:00", "12:00", 30), (_SEG_SEX, "14:00", "17:00", 30)]),
    ("Dr. Rodrigo Esteves", "Clínica Geral", 6, 30, []),  # inativo (demonstração)
]


def seed_demo(db):
    """Cria especialidades e médicos fictícios. Não faz nada se já existirem."""
    if db.execute("SELECT COUNT(*) FROM specialties").fetchone()[0]:
        return False
    db.execute("BEGIN IMMEDIATE")
    for name, desc in SPECIALTIES:
        db.execute("INSERT INTO specialties (name, description) VALUES (?,?)", (name, desc))
    for i, (name, spec, years, dur, blocks) in enumerate(DOCTORS, start=1):
        sid = db.execute("SELECT id FROM specialties WHERE name = ?", (spec,)).fetchone()[0]
        cur = db.execute(
            "INSERT INTO doctors (name, crm, specialty_id, bio, experience_years, consultation_duration, is_active) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, f"CRM-XX {100000 + i} (demonstração)", sid,
             f"Profissional fictício de {spec} com foco em atendimento humanizado. Dados de demonstração.",
             years, dur, 1 if blocks else 0),
        )
        for days, start, end, step in blocks:
            for wd in days:
                db.execute(
                    "INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time, slot_interval) "
                    "VALUES (?,?,?,?,?)", (cur.lastrowid, wd, start, end, step))
    db.execute("COMMIT")
    return True
