# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Standalone test settings — Postgres via DATABASE_URL (zeno container), else zeno's published port 5532."""

import os

import dj_database_url

SECRET_KEY = "not so secret test secret for the siteintel suite"  # noqa: S105 — test-only
DEBUG = True
ALLOWED_HOSTS = ["*"]
ENVIRONMENT = "development"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "django_siteintel",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "tests.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "django_utils.api.v2_errors.v2_exception_handler",
}
SPECTACULAR_SETTINGS = {"TITLE": "django-siteintel Admin API v2", "VERSION": "2.0.0", "OAS_VERSION": "3.1.0"}

_DEFAULT_URL = "postgresql://entirius:entirius-dev@localhost:5532/entirius"
DATABASES = {"default": dj_database_url.parse(os.environ.get("DATABASE_URL", _DEFAULT_URL))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# The suite never leaves the process: every HTTP call is faked in tests/fake_http.py.
SITEINTEL_BLOCK_PRIVATE_HOSTS = True
