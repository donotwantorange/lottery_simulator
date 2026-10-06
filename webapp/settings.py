"""Django settings with v6 data paths isolated from the legacy application."""

import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_ENV = os.environ.get("LOTTERY_ENV", "development").strip().lower()
IS_PRODUCTION = RUNTIME_ENV in {"prod", "production"}

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if IS_PRODUCTION and not SECRET_KEY:
    raise ImproperlyConfigured("生产环境必须设置 SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = "development-only-insecure-key-do-not-use-in-production"

DEBUG = not IS_PRODUCTION and os.environ.get("LOTTERY_DEBUG", "0").lower() in {
    "1", "true", "yes", "on",
}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("LOTTERY_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

DATA_DIR = Path(os.environ.get("LOTTERY_DATA_DIR", BASE_DIR / "data")).expanduser().resolve()
DATABASE_PATH = Path(
    os.environ.get("LOTTERY_DB_PATH", DATA_DIR / "history_v6.sqlite3")
).expanduser().resolve()
JOBS_DIR = Path(os.environ.get("LOTTERY_JOBS_DIR", DATA_DIR / "jobs_v6")).expanduser().resolve()
EXPORTS_DIR = Path(
    os.environ.get("LOTTERY_EXPORTS_DIR", DATA_DIR / "exports_v6")
).expanduser().resolve()

INSTALLED_APPS = [
    "dashboard.apps.DashboardConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "dashboard.middleware.AccountSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "webapp.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "webapp.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DATABASE_PATH),
        "ATOMIC_REQUESTS": False,
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE",
                    "init_command": "PRAGMA journal_mode=WAL"},
    }
}

AUTH_USER_MODEL = "dashboard.User"
AUTHENTICATION_BACKENDS = ["dashboard.services.accounts.UsernameBackend"]
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_SECURE = IS_PRODUCTION
CSRF_FAILURE_VIEW = "dashboard.api.errors.csrf_failure"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 12 * 60 * 60
LOTTERY_IDLE_SECONDS = int(os.environ.get("LOTTERY_IDLE_SECONDS", "1800"))
LOTTERY_ABSOLUTE_SECONDS = int(os.environ.get("LOTTERY_ABSOLUTE_SECONDS", "43200"))
LOTTERY_ACCOUNT_FAILURES = int(os.environ.get("LOTTERY_ACCOUNT_FAILURES", "5"))
LOTTERY_SOURCE_FAILURES = int(os.environ.get("LOTTERY_SOURCE_FAILURES", "20"))
_trusted_proxy_text = os.environ.get("LOTTERY_TRUSTED_PROXIES", "").strip()
try:
    LOTTERY_TRUSTED_PROXIES = frozenset(
        str(ipaddress.ip_address(value.strip()))
        for value in _trusted_proxy_text.split(",")
    ) if _trusted_proxy_text else frozenset()
except ValueError as exc:
    raise ImproperlyConfigured("LOTTERY_TRUSTED_PROXIES 只能包含精确 IP 地址") from exc
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get("LOTTERY_CSRF_TRUSTED_ORIGINS", "").split(",") if x]
if not IS_PRODUCTION:
    CSRF_TRUSTED_ORIGINS.append("http://127.0.0.1:5173")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "dashboard.api.errors.exception_handler",
}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
