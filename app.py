import logging
import os

import click
from flask import Flask, render_template
from flask_login import current_user
from flask_wtf.csrf import CSRFError

import models
from config import Config
from extensions import csrf, login_manager
from utils import register_filters


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para continuar."
    login_manager.login_message_category = "info"
    login_manager.user_loader(models.get_user)
    app.teardown_appcontext(models.close_db)
    register_filters(app)

    from routes.admin import bp as admin_bp
    from routes.appointments import bp as appointments_bp
    from routes.auth import bp as auth_bp, public_bp
    from routes.patient import bp as patient_bp
    for bp in (public_bp, auth_bp, patient_bp, appointments_bp, admin_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        return {"hospital_name": app.config["HOSPITAL_NAME"]}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if current_user.is_authenticated:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_template("errors/403.html", csrf=True), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error("Erro interno em %s", type(e).__name__)  # sem dados do usuário
        return render_template("errors/500.html"), 500

    @app.cli.command("init-db")
    @click.option("--no-demo", is_flag=True, help="Não criar médicos e especialidades fictícios.")
    def init_db_command(no_demo):
        """Cria as tabelas e (por padrão) os dados fictícios de demonstração."""
        models.init_db()
        if not no_demo:
            created = models.seed_demo(models.get_db())
            click.echo("Dados de demonstração criados." if created else "Dados já existiam; nada alterado.")
        click.echo("Banco inicializado em " + app.config["DATABASE"])

    if not app.testing:
        logging.basicConfig(level=logging.INFO)
    return app


if __name__ == "__main__":
    # Apenas para desenvolvimento local. Em produção use um servidor WSGI (ex.: waitress).
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
