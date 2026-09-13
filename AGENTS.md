# AGENTS.md

Domain intelligence for the Volkanos platform: Lighthouse, URLScan and heuristic audits per domain — distribution `entirius-django-siteintel`, Django app `django_siteintel`.

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest + pytest-django) |

## Conventions

- English only: code, docs, commits, branches, PRs.
- MPL-2.0: every non-trivial source file carries the license header (pre-commit inserts it).
- Toolchain: uv + ruff + hatchling + pytest; all config in `pyproject.toml`; `uv.lock` committed.
- Git flow: `master` (production) + `develop` (integration); changes land via PR; semver tag on `master`.
- Never rename the package / Django app_label / DB table prefix `django_siteintel` — it is a schema contract.
- Migrations are part of the public contract — never edit an already released migration.
- Default: do not commit — git is the user's call.

## Commit Message Format

**NEVER add `Co-Authored-By: Claude ...` (or any other Claude/Anthropic attribution) to commit messages.**

This overrides the default Claude Code behavior of appending a `Co-Authored-By` trailer. Commit messages MUST contain only the user's authored content — no robot footer, no "Generated with Claude Code" line, no co-author trailer.

Same rule applies to PR descriptions: no `Generated with [Claude Code]` footer.

## Architecture

Layers: API → services → sources → models. No leads, no companies: consumers listen to `report_ready`.
- `models/` — `Audit` (UUID, keyed by registrable `domain`, `channel_idx` text, `expires_at`), `Report` (unique per
  audit + source; `raw` server-side only, `processed` ≤ `SITEINTEL_PROCESSED_MAX_BYTES`), `ExternalApiKey` (per source).
- `services/audit_service` — `request_audit(*, domain_or_url, channel_idx, requested_by)` reuses the newest valid
  audit of the domain **in the same channel** (signal at once, no fetch) or creates one with a pending report per
  source; `rerun_audit` (new `run_id`; `AuditRunningError` while running), `expire_audits(now=None)`,
  `fail_stuck_audits(now=None)`, `run_now` (development). `report_service` runs/polls/fails reports and finishes the run.
- `sources/` — entry-point group `siteintel_sources`: `lighthouse` (PSI v5), `urlscan` (submit + poll), `heuristic`
  (own fetch). Every call goes through `security/url_guard` (lookup copy). `SourceError(code, detail)`, detail = host + class.
- **Recording mode**: a base URL other than the public API reads `{base}/{domain}.{strategy}.json` — psi
  `mobile|desktop` (a 404 strategy is `unavailable`, both missing → `recording_missing`), urlscan `submit|result`.
- `tasks/` (queue `siteintel_default`): `run_audit` → chord of `run_source` (retries only `upstream`, 3×, backoff)
  → `finish_audit` (sends `report_ready(audit, succeeded_sources)` once per run); `poll_urlscan` re-dispatches with a
  countdown until `SITEINTEL_URLSCAN_POLL_BUDGET_S`; `expire_audits`; `sweep_stuck_audits`. Never `time.sleep` (a test
  greps `src/`). Any non-`SourceError` exception in `run_source` fails the report `internal` (detail = class name) so
  the chord completes. `poll_urlscan` / `finish_audit` carry the audit's `run_id` and no-op once a rerun replaced it.
  Poll interval / budget are clamped at read time (`interval >= 1`, `budget >= interval`, WARNING when clamped).
  NUL characters are stripped from `raw` / `processed` before save (Postgres jsonb rejects U+0000).
- The PSI key travels in the `X-Goog-Api-Key` header, never in the URL; `safe_get` drops headers on a cross-host redirect.

## Admin API v2

Prefix `api/siteintel/v2/admin/<channel_idx>/`, `JWTAuthentication` + `IsAdminUser`: `GET audits/?domain=&status=&ordering=`,
`GET audits/<uuid>/` (reports with `processed`, never `raw` or keys), `POST audits/` `{domain_or_url, requested_by}`
→ 201 new / 200 reused (400 when the URL with its added scheme exceeds 2048 chars), `POST audits/<uuid>/rerun/` → 202
(409 while the audit is `running`). `ENVIRONMENT == "development"` only (else 404):
`POST test/run-now/<uuid>/` (sources inline, urlscan polled once) and `POST test/expire-now/` `{"now": iso|null}`.

## Host integration

- `INSTALLED_APPS += ["django_siteintel"]`; `urlpatterns.append(path("", include("django_siteintel.urls")))`; worker `-Q siteintel_default`.
- Beat: `CELERY_BEAT_SCHEDULE["siteintel-expire"] = {"task": "django_siteintel.expire_audits", "schedule": crontab(hour=3, minute=0)}`
  and `CELERY_BEAT_SCHEDULE["siteintel-sweep-stuck"] = {"task": "django_siteintel.sweep_stuck_audits", "schedule": crontab(minute="*/10")}`
  (fails audits `running` longer than `SITEINTEL_AUDIT_STUCK_MINUTES`, default 30).
- Settings `SITEINTEL_*` with defaults in `settings.py`; zeno sets base URLs to `fixtures:8000`, `ALLOWED_HOSTS = ["fixtures"]`.
- Entry points are read from installed metadata: re-install the package (zeno `make link`) after editing them.

## Testing end-to-end

- Host `make check && make test` (Postgres `localhost:5532` or `DATABASE_URL`; HTTP faked). Unit tests carry S-01…S-09.
- Zeno `make module-test MODULE=entirius-django-siteintel`; BDD `make bdd TAGS=@siteintel` (emporium `features/siteintel/`:
  S-01, S-08, S-09; recordings `fixtures/siteintel/`). Restart the worker after task changes; funnel E2E guide = plan 12.
