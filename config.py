import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # A chave vem de variável de ambiente. Sem ela, usa-se uma chave aleatória
    # temporária (as sessões deixam de valer ao reiniciar o servidor).
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    DATABASE = os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "instance", "hospital.db")
    # Política de cancelamento: antecedência mínima (em horas). 0 = sem restrição.
    CANCEL_MIN_HOURS = int(os.environ.get("CANCEL_MIN_HOURS", "2"))
    HOSPITAL_NAME = "Laurient Evans"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Em produção (HTTPS) defina SESSION_COOKIE_SECURE=1
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 8 * 3600
