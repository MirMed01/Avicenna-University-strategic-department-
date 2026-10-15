"""Настройки «Канона». Секреты и адреса — только из переменных окружения, в репозиторий не попадают."""

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("KANON_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("KANON_SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("Задайте KANON_SECRET_KEY (или KANON_DEBUG=1 для разработки).")

ALLOWED_HOSTS = [h for h in os.environ.get("KANON_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("KANON_CSRF_ORIGINS", "").split(",") if o]
# Адрес для ссылок и QR-кодов студентам, например https://qanun.tajmedun.tj (без «/» в конце).
KANON_PUBLIC_URL = os.environ.get("KANON_PUBLIC_URL", "").rstrip("/")
# За прокси (Codespaces, nginx) брать настоящий адрес из X-Forwarded-Host.
USE_X_FORWARDED_HOST = os.environ.get("KANON_USE_X_FORWARDED_HOST", "0") == "1"
if USE_X_FORWARDED_HOST:
    # Тот же доверенный прокси сообщает и протокол — ссылки в QR будут https.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "org",
    "accounts",
    "norms",
    "portfolio",
    "instruments",
    "inspections",
    "capa",
    "feedback",
    "dashboard",
    "accreditation",
    "processes",
    "exams",
    "management",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kanon.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "kanon.wsgi.application"


def _database():
    # Боевой сервер: KANON_DATABASE_URL=postgres://пользователь:пароль@хост:5432/база
    url = os.environ.get("KANON_DATABASE_URL")
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    u = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "",
        "PORT": str(u.port or 5432),
    }


DATABASES = {"default": _database()}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
import sys

if sys.argv[1:2] == ["test"]:
    # Только для тестов: быстрое хеширование паролей, на сервере не действует.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CSRF_FAILURE_VIEW = "core.views.csrf_failure"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "ru"
LANGUAGES = [("ru", "Русский"), ("tg", "Тоҷикӣ")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Dushanbe"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("KANON_MEDIA_ROOT", BASE_DIR / "media"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG and os.environ.get("KANON_HTTPS", "1") == "1":
    # Рабочий сервер за nginx с HTTPS (deploy/nginx-kanon.conf): nginx сам ставит X-Forwarded-Proto.
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # HSTS: начинаем с одного дня; увеличить (KANON_HSTS_SECONDS=31536000), когда HTTPS проверен.
    SECURE_HSTS_SECONDS = int(os.environ.get("KANON_HSTS_SECONDS", "86400"))
    # HSTS только для адреса «Канона»: на поддомены и в список preload — нет, это навязало бы HTTPS
    # всему сайту университета (tajmedun.tj и его поддоменам), а это не наше решение.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
