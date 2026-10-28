"""Cria o primeiro administrador (secretaria) com senha digitada no terminal.

Uso:  python scripts/create_admin.py
Também aceita ADMIN_NAME, ADMIN_EMAIL e ADMIN_PASSWORD como variáveis de ambiente
(úteis para automação). Nenhuma senha fica gravada no código-fonte.
"""
import getpass
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import create_user, get_db, init_db  # noqa: E402
from utils import EMAIL_RE  # noqa: E402


def main():
    name = os.environ.get("ADMIN_NAME") or input("Nome do administrador: ").strip()
    email = (os.environ.get("ADMIN_EMAIL") or input("E-mail: ")).strip().lower()
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Senha (mín. 10 caracteres): ")
        if password != getpass.getpass("Confirme a senha: "):
            sys.exit("As senhas não coincidem.")
    if len(name) < 3 or not EMAIL_RE.match(email):
        sys.exit("Nome ou e-mail inválido.")
    if len(password) < 10:
        sys.exit("A senha deve ter pelo menos 10 caracteres.")
    app = create_app()
    with app.app_context():
        init_db()
        try:
            create_user(get_db(), name, email, password, role="admin")
        except sqlite3.IntegrityError:
            sys.exit("Já existe um usuário com esse e-mail.")
    print("Administrador criado com sucesso.")


if __name__ == "__main__":
    main()
