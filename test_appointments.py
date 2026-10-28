import threading
from datetime import date, timedelta

from conftest import book, count_appts
from models import get_db


def test_valid_booking_shows_in_dashboard(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    c = patient()
    r = book(c, did, tomorrow, "10:00")
    text = r.get_data(as_text=True)
    assert "Consulta agendada" in text and "10:00" in text
    assert count_appts(app, did) == 1


def test_same_slot_blocked(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    book(patient(1), did, tomorrow, "10:00")
    r = book(patient(2), did, tomorrow, "10:00")
    assert "não está mais disponível" in r.get_data(as_text=True)
    assert count_appts(app, did) == 1


def test_partial_overlap_blocked(app, patient, make_doctor, tomorrow):
    did = make_doctor(duration=30, interval=15)
    book(patient(1), did, tomorrow, "10:00")   # 10:00-10:30
    c2 = patient(2)
    book(c2, did, tomorrow, "10:15")            # começa dentro da consulta
    book(c2, did, tomorrow, "09:45")            # termina dentro da consulta
    assert count_appts(app, did) == 1
    book(c2, did, tomorrow, "10:30")            # encostando no fim: permitido
    book(c2, did, tomorrow, "09:30")            # terminando no início: permitido
    assert count_appts(app, did) == 3


def test_different_doctors_same_time(app, patient, make_doctor, tomorrow):
    d1, d2 = make_doctor("Dr. A"), make_doctor("Dr. B")
    book(patient(1), d1, tomorrow, "10:00")
    book(patient(2), d2, tomorrow, "10:00")
    assert count_appts(app, d1) == 1 and count_appts(app, d2) == 1


def test_slot_outside_schedule_rejected(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    book(patient(), did, tomorrow, "15:00")
    assert count_appts(app, did) == 0


def test_past_date_rejected(app, patient, make_doctor):
    did = make_doctor()
    book(patient(), did, date.today() - timedelta(days=1), "10:00")
    assert count_appts(app, did) == 0


def test_booking_requires_login(app, client, make_doctor, tomorrow):
    did = make_doctor()
    r = book(client, did, tomorrow, "10:00", follow=False)
    assert r.status_code == 302 and count_appts(app, did) == 0


def test_slots_page_lists_free_times(patient, make_doctor, tomorrow):
    did = make_doctor()
    c = patient()
    html = c.get(f"/agendar?doctor_id={did}&date={tomorrow.isoformat()}").get_data(as_text=True)
    assert 'value="%sT09:00"' % tomorrow.isoformat() in html


def test_cancel_and_slot_released(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    c1, c2 = patient(1), patient(2)
    book(c1, did, tomorrow, "10:00")
    assert c1.post("/consultas/1/cancelar", follow_redirects=True).status_code == 200
    with app.app_context():
        row = get_db().execute("SELECT * FROM appointments WHERE id = 1").fetchone()
        assert row["status"] == "cancelled" and row["cancelled_at"]  # registro preservado
    book(c2, did, tomorrow, "10:00")  # horário liberado
    assert count_appts(app, did) == 1


def test_cannot_cancel_other_patients_appointment(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    book(patient(1), did, tomorrow, "10:00")
    c2 = patient(2)
    assert c2.post("/consultas/1/cancelar").status_code == 404
    assert c2.get("/consultas/1").status_code == 404
    assert count_appts(app, did) == 1


def test_cancellation_policy(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    c = patient()
    book(c, did, tomorrow, "10:00")
    app.config["CANCEL_MIN_HOURS"] = 24 * 365
    c.post("/consultas/1/cancelar")
    assert count_appts(app, did) == 1


def test_cancel_requires_post(patient):
    assert patient().get("/consultas/1/cancelar").status_code == 405


def test_concurrent_booking_only_one_wins(app, make_doctor, register, login, tomorrow):
    did = make_doctor()
    clients = []
    for n in (1, 2, 3, 4):
        c = app.test_client()
        register(c, n)
        login(c, n)
        clients.append(c)
    barrier = threading.Barrier(len(clients))

    def attempt(c):
        barrier.wait()
        book(c, did, tomorrow, "10:00")

    threads = [threading.Thread(target=attempt, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert count_appts(app, did) == 1


def test_db_unique_index_blocks_duplicate_start(app, patient, make_doctor, tomorrow):
    import sqlite3
    did = make_doctor()
    book(patient(), did, tomorrow, "10:00")
    with app.app_context():
        db = get_db()
        try:
            db.execute("INSERT INTO appointments (patient_id, doctor_id, start_at, end_at, status, created_at) "
                       "VALUES (1, ?, ?, ?, 'scheduled', 'x')", (did, f"{tomorrow}T10:00", f"{tomorrow}T10:30"))
            assert False, "deveria violar o índice único"
        except sqlite3.IntegrityError:
            pass
