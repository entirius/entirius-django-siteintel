---
title: Gotchas
description: The one list of rules that bite — read before touching the run lifecycle, sources, the guard or the API.
---

Install-time traps (result backend, `siteintel_default` queue, beat schedules, OAS 3.1, keys as rows) live in
`install.md`. Each item below: the rule, then where it is enforced.

## Run lifecycle

- **A task that raises breaks the chord and `finish_audit` never runs.** `run_source` catches everything:
  `SourceError` maps to its code, any other exception fails the report `internal`. Keep it that way when
  adding code paths (`tasks/run_source.py`; `test_run_source_unexpected_error_fails_report`).
- **`complete` wraps `process` in a catch of `AttributeError`, `KeyError`, `TypeError`, `ValueError`** → `invalid`.
  A new source whose `process` can raise anything else ends as `internal` instead.
- **Never `time.sleep` in the package.** Polling is a countdown re-dispatch; `test_no_sleep_in_package` greps
  `src/`.
- **Every task of a run carries `run_id`.** A rerun draws a new one; a task whose `run_id` no longer matches
  returns without writing. A new task that touches reports must take and check it too.
- **A finished report is never reopened.** `report_service._save` updates only unfinished rows; a write that
  lost the race returns `False`. Do not replace it with `report.save()`.
- **`report_ready` goes out once per run.** `finish` sends it after the locked transaction; the sweeper sends it
  `on_commit`; reuse sends it synchronously inside the caller's call. Receivers must be cheap and queue their
  own work.
- **Every polling source is polled through `poll_urlscan`** and must return `{"submit": {"uuid": ...}}` from
  `fetch_raw` — the runner (`run_source._schedule_poll`, `audit_service._run_inline`) reads that key.
- **The stuck-audit cutoff reads `Audit.modified_at`**, which a report write does not touch. An audit is
  "stuck" by time since it was claimed, not since its last progress.

## Sources and the guard

- **Headers never follow a redirect to another host** (`safe_get`) — the PSI key cannot leak to a redirect
  target. It is sent as `X-Goog-Api-Key`, never `?key=` (urllib3 logs request lines at DEBUG).
- **`SourceError.detail` is host plus error class only.** Never put a body, a URL with a key or `str(exc)` of a
  requests error there — it is returned by the API.
- **Error classification is string-based** (`sources/base.source_error`): "internal host" → `ssrf`,
  "exceeds the cap" → `truncated`, everything else → `upstream`, which retries. A DNS failure or a bad scheme
  therefore retries three times. Changing a guard message changes the classification.
- **`SITEINTEL_MAX_PAGE_BYTES` caps PSI and urlscan JSON too.** A PSI answer over 5 MB fails `truncated`; only
  the heuristic source turns the cap into a `partial` report.
- **Recording mode is inferred from the base URL** — any value other than the public constant, a trailing slash
  aside. A typo in a production base URL silently switches to reading `{base}/{domain}.{strategy}.json`.
- **Sources come from installed entry-point metadata**, cached per process (`sources/registry.py`). Editing
  `pyproject.toml` needs a reinstall (zeno: `make link`) and a worker restart.
- **urlscan without an `ExternalApiKey` row sends an empty `API-Key`**; the submit fails `upstream` and retries.

## Domains and reuse

- **Reuse is per channel.** The same domain requested from two channels makes two audits and two fetches.
- **The registrable domain is a short suffix list, not the PSL** (`utils/domains.MULTI_PART_SUFFIXES`). A
  missing multi-part suffix merges unrelated shops under one key — add it there, with a test row.
- **One in-flight audit per (domain, channel) is a database constraint, not an application lock.** Two
  concurrent first requests both miss `find_valid_audit` and both call `create()`; the second raises
  `IntegrityError`, which `request_audit` catches to return the first request's audit instead. A caller that
  bypasses `request_audit` and calls `Audit.objects.create()` directly loses that protection.
- **`URLField(max_length=2048)` is checked after the scheme is added** (`normalise_domain`) — a 2048-character
  domain without scheme is a 400, not a database error.

## API

- **The `test/` routes are decided at URL import time.** `override_settings(ENVIRONMENT=...)` does not add or
  remove them in a running process; the view guard (404 outside development) is what a test can flip.
- **`raw` and key values never leave the server.** Response schemas have no field for them; the admin shows
  only `set` / `empty` for a key in the list and hides `raw` in the report inline.
- **`POST audits/` answers 200 only for a reused audit** — decided by status (`completed` /
  `partially_completed`), not by a flag from the service.

## Module boundaries

- **siteintel imports nothing from leads, communicator or any catalog module.** Consumers call
  `audit_service.request_audit` and connect to `report_ready`.
- **The URL guard is a copy of lookup's**, not an import — siteintel must not depend on lookup.
- **The worker has no autoreload** — restart it after any change to `tasks/` or what they call.
