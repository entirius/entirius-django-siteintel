# AGENTS.md

entirius-django-siteintel (Django app `django_siteintel`) — domain intelligence module of Entirius: PageSpeed
Insights, urlscan.io and a heuristic fetch per registrable domain, reused while valid, announced by one signal.
Table prefix `django_siteintel_`.

## Commands

| Command | Meaning |
|---|---|
| `make install` | `uv sync --all-extras` |
| `make test` | pytest — PostgreSQL only: `DATABASE_URL`, else the default in `tests/settings.py` (`docs/testing.md`) |
| `make check` / `fix` | ruff lint + format (+ canonical `.gitleaks.toml` guard) |

## Conventions

- English only; MPL-2.0 header on every `.py` (`insert-license`); no Claude attribution trailers.
- Layered: `models/` · `sources/` (fetch → validate → process) · `services/` · `schemas/` · `api/admin/` ·
  `tasks/`. No logic in models; the API never exposes `Report.raw` or key values.
- No imports from leads, communicator or catalog modules — consumers call `request_audit` and listen to
  `report_ready`.
- Never rename the package, the app label or the table prefix; never edit a released migration.
- Access: areas live on the AppConfig (`access_areas`, `access_route_rules`), every admin view carries
  `access_area`; a new admin route without one fails `tests/test_access_ownership.py`.
- Git flow: `develop` + `master`, PRs. Do not commit by default — the operator decides.

## Architecture

Read first: `docs/install.md` (host) · `docs/api.md` (caller) · `docs/concept.md` (why) ·
`docs/gotchas.md` (before editing).

```
src/django_siteintel/
├── apps.py  enums.py (statuses, ErrorCode)  settings.py (value(), clamped poll settings, recording_mode)
├── checks.py      config health: siteintel.sources (recording / missing key), siteintel.keys (probe)
├── models/        audit.py (Audit, run_id)  report.py (Report)  external_api_key.py
├── schemas/       requests.py  responses.py
├── api/admin/     urls.py  views/_base.py (AdminView: JWT + IsAdminUser)  audit_views.py  test_views.py (development)
├── urls.py        api/siteintel/v2/admin/<channel_idx>/ → api.admin.urls
├── migrations/    0001 initial · 0002 Audit.run_id + ErrorCode.internal
├── sources/       base.py (SourceFetcher, SourceError — the contract)  registry.py (entry points `siteintel_sources`)
│                  lighthouse.py (PSI v5)  urlscan.py (submit + poll)  heuristic.py (own fetch)
├── services/      audit_service (request, rerun, expire, sweep, run_now)  report_service (run, poll, fail, finish)
│                  cleaning_service (snapshot trimming, NUL strip)  source_status (recording, key, cached key probe)
├── security/      url_guard.py (safe_get, safe_post — a copy of lookup's guard)
├── signals/       report_ready(audit, succeeded_sources)
├── tasks/         run_audit  run_source  poll_urlscan  finish_audit  expire_audits  sweep_stuck_audits
├── utils/         domains.py (registrable domain, 2048-char URL bound)
└── admin.py       Audit (+ report inline, no raw), ExternalApiKey (masked in the list)
```

Flow: `request_audit` → reuse a valid audit of the domain in the channel (`report_ready` at once) or create
`Audit` + one `Report` per source → `run_audit` → chord of `run_source` (`poll_urlscan` for urlscan) →
`finish_audit` → status + `report_ready` once per run.

| Topic | Where |
|---|---|
| A setting's name, default, meaning | `settings.py`; the table in `docs/install.md` |
| Request / response shape, auth, errors | `docs/api.md`; `schemas/`; `docs/openapi.yaml` |
| The source protocol, recording mode | `sources/base.py`; `docs/concept.md` § Sources |
| What a status or an `error_code` means | `enums.py`; `docs/concept.md` § Lifecycle; `docs/operations.md` § Reading a failed report |
| Why reuse, rerun, expiry and the sweeper behave as they do | `docs/concept.md` § Reuse, rerun, expiry |
| Tasks, schedules, the SSRF guard, adding a source | `docs/operations.md` |
| Snapshot size rules | `services/cleaning_service.py`; `docs/concept.md` § Snapshot cleaning |
| Which test file covers what; BDD in the entirius-zeno harness | `docs/testing.md` |
| What changed and why | `CHANGELOG.md` |
| ERD groupings | `docs/erd-config.yaml` |

## Gotchas

- `docs/gotchas.md` is the only list. Read it before touching tasks, sources, the guard or the API.
