---
title: Install
description: What a host needs before the first audit — prerequisites, wiring, the settings table, API keys, bootstrap order.
---

Read this once before `migrate`. Day-2 commands and failure handling: `operations.md`.

## Prerequisites

| Requirement | Why | Verify |
|---|---|---|
| PostgreSQL | the only database the suite runs on; run finishing relies on `select_for_update` | `manage.py migrate` |
| `entirius-django-utils` ≥ 2.0.0 | `BaseModel`, the v2 error helpers | `uv lock` / `pip check` |
| `REST_FRAMEWORK["EXCEPTION_HANDLER"] = "django_utils.api.v2_errors.v2_exception_handler"` | the v2 400 shape | a 400 answers with field errors |
| `SPECTACULAR_SETTINGS["OAS_VERSION"] = "3.1.0"` | Pydantic documents examples as JSON Schema 2020-12 | `manage.py spectacular --validate` |
| A Celery worker consuming queue **`siteintel_default`** | every task runs there; without it audits stay `pending` | `celery -A main worker -Q …,siteintel_default` |
| A Celery **result backend** | `run_audit` is a chord — the callback waits on the header results | `CELERY_RESULT_BACKEND` set |
| Celery beat with the two schedules below | expiry and the stuck-audit sweeper run only from beat | beat log |
| Outbound HTTPS to `www.googleapis.com` and `urlscan.io`, and to the audited sites | the three sources | `manage.py shell` + a request |
| The package installed with its metadata (not a bare path on `sys.path`) | sources are discovered from entry points | `importlib.metadata.entry_points(group="siteintel_sources")` lists three |

## Wiring

```python
INSTALLED_APPS += ["django_siteintel"]

# urls.py
urlpatterns.append(path("", include("django_siteintel.urls")))

CELERY_BEAT_SCHEDULE["siteintel-expire"] = {
    "task": "django_siteintel.expire_audits",
    "schedule": crontab(hour=3, minute=0),
}
CELERY_BEAT_SCHEDULE["siteintel-sweep-stuck"] = {
    "task": "django_siteintel.sweep_stuck_audits",
    "schedule": crontab(minute="*/10"),
}
```

## Settings

The only settings table. Defaults live in `django_siteintel/settings.py`; every value is read at call time,
so `override_settings` and the host always win.

| Setting | Default | Meaning |
|---|---|---|
| `SITEINTEL_PSI_BASE_URL` | `https://www.googleapis.com/pagespeedonline/v5` | any other value switches PSI to recording mode (`concept.md` § Sources) |
| `SITEINTEL_URLSCAN_BASE_URL` | `https://urlscan.io/api/v1` | same, for urlscan |
| `SITEINTEL_ALLOWED_HOSTS` | `[]` | hostnames the SSRF guard lets through even when they resolve to a private address |
| `SITEINTEL_BLOCK_PRIVATE_HOSTS` | `True` | SSRF guard master switch — `False` only in a dev harness |
| `SITEINTEL_FETCH_TIMEOUT_S` | `20` | per-request timeout, every source |
| `SITEINTEL_MAX_PAGE_BYTES` | `5242880` (5 MB) | body cap for every response, PSI and urlscan JSON included |
| `SITEINTEL_PROCESSED_MAX_BYTES` | `65536` (64 KB) | upper bound of one `processed` snapshot |
| `SITEINTEL_EXPIRE_DAYS` | `90` | how long a finished audit is reused |
| `SITEINTEL_URLSCAN_POLL_INTERVAL_S` | `10` | seconds between urlscan polls; clamped to ≥ 1 with a WARNING |
| `SITEINTEL_URLSCAN_POLL_BUDGET_S` | `60` | how long a result is awaited; clamped to ≥ one interval |
| `SITEINTEL_AUDIT_STUCK_MINUTES` | `30` | a `running` audit older than this is failed by the sweeper |
| `ENVIRONMENT` (host) | — | `"development"` registers the `test/` endpoints; anything else hides them |

## API keys

Keys are rows, not settings: one `ExternalApiKey` per source (`lighthouse`, `urlscan`), `is_active = True`,
entered in the Django admin (the list, and the change form's "key" field, only ever show `set` / `empty` —
the stored value is never rendered; leaving the field blank on save keeps the stored key). The PSI key is
sent in the `X-Goog-Api-Key` header, the urlscan key in `API-Key`. PSI works without a key at a low anonymous
quota — expect `upstream` failures under load; urlscan's submit needs one. `heuristic` needs none. Recording
mode sends no key.

## Bootstrap order

```
manage.py migrate                                  # Audit, Report, ExternalApiKey
# admin: add the lighthouse and urlscan ExternalApiKey rows
# start the worker (-Q …,siteintel_default) and beat
POST /api/siteintel/v2/admin/<channel>/audits/     # {"domain_or_url": "shop.example", "requested_by": "ops"}
GET  /api/siteintel/v2/admin/<channel>/audits/<id>/ # reports finish within seconds to about a minute
```

A report failing `ssrf` on the first audit means the guard refused a host — see `operations.md` § Outbound
fetches before touching `SITEINTEL_BLOCK_PRIVATE_HOSTS`.
