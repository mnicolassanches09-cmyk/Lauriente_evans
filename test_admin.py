from conftest import book, count_appts
from models import get_db


def test_patient_blocked_from_admin(patient):
    c = patient()
    for url in ("/admin/", "/admin/consultas", "/admin/medicos", "/admin/pacientes"):
        assert c.get(url).status_code == 403


def test_anonymous_redirected_to_admin_login(client):
    r = client.get("/admin/")
    assert r.status_code == 302 and "/admin/entrar" in r.headers["Location"]


def test_admin_cannot_use_patient_login_nor_patient_area(app, admin_client, client):
    r = client.post("/entrar", data={"email": "admin@teste.local", "password": "adminsenha123"})
    assert r.status_code == 401
    assert admin_client.get("/painel").status_code == 403


def test_patient_cannot_use_admin_login(client, register):
    register(client)
    r = client.post("/admin/entrar", data={"email": "paciente1@teste.local", "password": "senha1234"})
    assert r.status_code == 401


def test_admin_dashboard_and_lists(admin_client):
    for url in ("/admin/", "/admin/consultas", "/admin/medicos", "/admin/pacientes", "/admin/especialidades"):
        assert admin_client.get(url).status_code == 200


def doctor_form(**over):
    data = {"name": "Dr. Novo Médico", "crm": "CRM-XX 1", "specialty_id": "1", "bio": "Bio", "experience_years": "5",
            "consultation_duration": "30", "photo": "", "is_active": "1", "d0_on": "1", "d0_start": "08:00",
            "d0_end": "12:00", "d0_interval": "30"}
    data.update(over)
    return data


def test_create_and_edit_doctor(app, admin_client):
    r = admin_client.post("/admin/medicos/novo", data=doctor_form(), follow_redirects=True)
    assert "Médico salvo" in r.get_data(as_text=True)
    with app.app_context():
        d = get_db().execute("SELECT * FROM doctors WHERE name = 'Dr. Novo Médico'").fetchone()
        assert d and get_db().execute("SELECT COUNT(*) FROM doctor_schedules WHERE doctor_id=?", (d["id"],)).fetchone()[0] == 1
        did = d["id"]
    admin_client.post(f"/admin/medicos/{did}/editar", data=doctor_form(name="Dr. Editado", consultation_duration="45"))
    with app.app_context():
        d = get_db().execute("SELECT * FROM doctors WHERE id = ?", (did,)).fetchone()
        assert d["name"] == "Dr. Editado" and d["consultation_duration"] == 45
        assert get_db().execute("SELECT COUNT(*) FROM admin_audit_logs").fetchone()[0] >= 2


def test_invalid_doctor_rejected(admin_client):
    r = admin_client.post("/admin/medicos/novo", data=doctor_form(name="x", consultation_duration="0"))
    assert r.status_code == 400


def test_inactive_doctor_cannot_be_booked(app, admin_client, patient, make_doctor, tomorrow):
    did = make_doctor()
    admin_client.post(f"/admin/medicos/{did}/alternar")
    c = patient()
    book(c, did, tomorrow, "10:00")
    assert count_appts(app, did) == 0


def test_admin_cancel_and_complete(app, admin_client, patient, make_doctor, tomorrow):
    did = make_doctor()
    c = patient()
    book(c, did, tomorrow, "10:00")
    book(c, did, tomorrow, "11:00")
    with app.app_context():
        ids = [r[0] for r in get_db().execute("SELECT id FROM appointments ORDER BY id")]
    admin_client.post(f"/admin/consultas/{ids[0]}/cancelar")
    admin_client.post(f"/admin/consultas/{ids[1]}/concluir")
    with app.app_context():
        st = [r[0] for r in get_db().execute("SELECT status FROM appointments ORDER BY id")]
    assert st == ["cancelled", "completed"]


def test_patient_cannot_post_admin_actions(app, patient, make_doctor, tomorrow):
    did = make_doctor()
    c = patient()
    book(c, did, tomorrow, "10:00")
    assert c.post("/admin/consultas/1/cancelar").status_code == 403
    assert count_appts(app, did) == 1
