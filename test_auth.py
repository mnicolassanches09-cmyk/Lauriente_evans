from conftest import make_cpf, reg_data
from models import get_db


def test_register_patient(app, client, register):
    r = register(client)
    assert "Cadastro realizado" in r.get_data(as_text=True)
    with app.app_context():
        u = get_db().execute("SELECT * FROM users WHERE email = 'paciente1@teste.local'").fetchone()
        assert u["role"] == "patient"
        assert u["password_hash"] != "senha1234" and "senha1234" not in u["password_hash"]


def test_register_cannot_make_admin(app, client):
    client.post("/cadastro", data=dict(reg_data(), role="admin"))
    with app.app_context():
        assert get_db().execute("SELECT role FROM users").fetchone()["role"] == "patient"


def test_duplicate_email_blocked(client, register):
    register(client, 1)
    r = register(client, 2, email="paciente1@teste.local")
    assert "e-mail" in r.get_data(as_text=True).lower() and r.status_code == 400


def test_duplicate_cpf_blocked(client, register):
    register(client, 1)
    r = client.post("/cadastro", data=reg_data(2, cpf=make_cpf(100000001)))
    assert "CPF" in r.get_data(as_text=True) and r.status_code == 400


def test_invalid_cpf_and_password_mismatch(client):
    r = client.post("/cadastro", data=reg_data(1, cpf="111.111.111-11", confirm_password="outra1234"))
    text = r.get_data(as_text=True)
    assert "CPF inválido" in text and "não coincidem" in text


def test_login_valid_and_invalid(client, register, login):
    register(client)
    assert "Olá, Paciente" in login(client).get_data(as_text=True)
    c2 = client.application.test_client()
    r = login(c2, password="errada123")
    assert "inválidos" in r.get_data(as_text=True)


def test_private_pages_require_login(client):
    for url in ("/painel", "/perfil", "/agendar"):
        r = client.get(url)
        assert r.status_code == 302 and "/entrar" in r.headers["Location"]


def test_logout_requires_post(patient):
    c = patient()
    assert c.get("/sair").status_code == 405
    c.post("/sair")
    assert c.get("/painel").status_code == 302
