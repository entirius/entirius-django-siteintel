# AGENTS.md

entirius-django-siteintel — domain intelligence for Volkanos: PageSpeed Insights, urlscan.io and a heuristic
fetch per registrable domain, reused while valid, announced by one signal. App label `django_siteintel`,
table prefix `django_siteintel_`.

## Quick Reference

- Python ≥ 3.11, Django ≥ 4.2, DRF + simplejwt + drf-spectacular, Pydantic 2, Celery, PostgreSQL, `uv`, ruff,
  hatchling, MPL-2.0.
- Read first: `docs/install.md` (host) · `docs/api.md` (caller) · `docs/concept.md` (why) ·
  `docs/gotchas.md` (before editing). This file is the map; it explains nothing twice.

## Commands

| Command | Meaning |
|---|---|
| `make install` | `uv sync --all-extras` |
| `make test` | pytest — Postgres only, see Testing |
| `make check` / `fix` | ruff lint + format (+ canonical `.gitleaks.toml` guard) |
| in zeno: `make module-test MODULE=entirius-django-siteintel` | the same suite inside the service container |

## Conventions

- English only; MPL-2.0 header on every `.py` (`insert-license`); no Claude attribution trailers.
- Layered: `models/` · `sources/` (fetch → validate → process) · `services/` · `schemas/` · `api/admin/` ·
  `tasks/`. No logic in models; the API never exposes `Report.raw` or key values.
- No imports from leads, communicator or catalog modules — consumers call `request_audit` and listen to
  `report_ready`.
- Never rename the package, the app label or the table prefix; never edit a released migration.
- Git flow: `develop` + `master`, PRs. Do not commit by default — the operator decides.

## Map

```
src/django_siteintel/
├── apps.py  enums.py (statuses, ErrorCode)  settings.py (value(), clamped poll settings, recording_mode)
├── models/        audit.py (Audit, run_id)  report.py (Report)  external_api_key.py
├── schemas/       requests.py  responses.py
├── api/admin/     urls.py  views/_base.py (AdminView: JWT + IsAdminUser)  audit_views.py  test_views.py (development)
├── urls.py        api/siteintel/v2/admin/<channel_idx>/ → api.admin.urls
├── migrations/    0001 initial · 0002 Audit.run_id + ErrorCode.internal
├── sources/       base.py (SourceFetcher, SourceError — the contract)  registry.py (entry points `siteintel_sources`)
│                  lighthouse.py (PSI v5)  urlscan.py (submit + poll)  heuristic.py (own fetch)
├── services/      audit_service (request, rerun, expire, sweep, run_now)  report_service (run, poll, fail, finish)
│                  cleaning_service (snapshot trimming, NUL strip)
├── security/      url_guard.py (safe_get, safe_post — a copy of lookup's guard)
├── signals/       report_ready(audit, succeeded_sources)
├── tasks/         run_audit  run_source  poll_urlscan  finish_audit  expire_audits  sweep_stuck_audits
├── utils/         domains.py (registrable domain, 2048-char URL bound)
└── admin.py       Audit (+ report inline, no raw), ExternalApiKey (masked in the list)
```

Flow: `request_audit` → reuse a valid audit of the domain in the channel (`report_ready` at once) or create
`Audit` + one `Report` per source → `run_audit` → chord of `run_source` (`poll_urlscan` for urlscan) →
`finish_audit` → status + `report_ready` once per run.

## Where things live

| Question | Answer |
|---|---|
| A setting's name, default, meaning | `settings.py`; the table in `docs/install.md` |
| Request / response shape, auth, errors | `docs/api.md`; `schemas/`; `docs/openapi.yaml` |
| The source protocol, recording mode | `sources/base.py`; `docs/concept.md` § Sources |
| What a status or an `error_code` means | `enums.py`; `docs/concept.md` § Lifecycle; `docs/operations.md` § Reading a failed report |
| Why reuse, rerun, expiry and the sweeper behave as they do | `docs/concept.md` § Reuse, rerun, expiry |
| Tasks, schedules, the SSRF guard, adding a source | `docs/operations.md` |
| Snapshot size rules | `services/cleaning_service.py`; `docs/concept.md` § Snapshot cleaning |
| Which test file covers what | `docs/testing.md` |
| What changed and why | `CHANGELOG.md` |
| ERD groupings | `docs/erd-config.yaml` |

## Testing

- Postgres only (`tests/settings.py`): `DATABASE_URL` wins (zeno container), else
  `postgresql://entirius:entirius-dev@localhost:5532/entirius`. Migrations run in tests.
- HTTP is faked (`tests/fake_http.py`); `recordings` in `tests/conftest.py` serves PSI / urlscan answers for
  `example-shop-1.test`. Celery runs eagerly where a test needs the chord (`eager_celery`).
- `ENVIRONMENT = "development"` in test settings — the `test/` routes are mounted at import.

## Testing end-to-end

| ID | Unit (`tests/`) | BDD (emporium `features/siteintel/siteintel_audit.feature`) |
|---|---|---|
| S-01 reuse of a valid audit, no fetch | `test_audit_service` (+ channel scope) | yes |
| S-02 expired audit → new audit, history kept | `test_audit_service` | — |
| S-03 PSI 429/5xx → retries → partially completed | `test_tasks` | — |
| S-04 urlscan poll budget → timeout, no sleep | `test_tasks` | — |
| S-05 private host / redirect to 10.x refused | `test_url_guard` | — |
| S-06 page over the byte cap → partial(truncated) | `test_url_guard` | — |
| S-07 base64 stripped, lists trimmed, < 64 KB | `test_sources` | — |
| S-08 heuristic differs per synthetic site | `test_sources` | yes |
| S-09 re-audit refreshes reports (409 while running) | `test_audit_service`, `test_admin_api` | yes |

- `make bdd TAGS=@siteintel` in zeno. Not one-shot: the Background expires every valid audit through
  `test/expire-now/`, so the feature re-runs on one seed. Recordings: emporium `fixtures/siteintel/`;
  zeno points both base URLs at the `fixtures` container (recording mode).
- The module also runs inside the leads funnel (`@funnel`, one-shot per seed): stage rule → audit →
  `report_ready` → intel. Guides: portal `guides/leads-end-to-end-testing.md`, emporium
  `docs/e2e-leads-funnel.md`.
- Restart the worker after task changes — Celery has no autoreload.

## Gotchas

`docs/gotchas.md` — the only list. Read it before touching tasks, sources, the guard or the API.
