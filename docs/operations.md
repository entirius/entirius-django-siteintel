---
title: Operations
description: Day 2 — Celery tasks and schedules, reading a failed report, outbound fetches (SSRF guard), recording mode, adding a source.
---

Install-time facts — prerequisites, wiring, the settings table, API keys — are in `install.md`. This file
starts after the first audit finished.

## Celery tasks

Every task runs on queue **`siteintel_default`** with `acks_late=True`. None of them sleeps: waiting is a
countdown re-dispatch.

| Task | Trigger | Does |
|---|---|---|
| `django_siteintel.run_audit(audit_id)` | `request_audit` / `rerun_audit`, after commit | claims a `pending` audit (→ `running`), fans out a chord of `run_source`, callback `finish_audit`; a non-pending audit is left alone |
| `django_siteintel.run_source(audit_id, source, run_id)` | chord header | runs one report; retries `upstream` 3× with backoff; schedules `poll_urlscan` for a polling source; never raises past its retries |
| `django_siteintel.poll_urlscan(report_id, uuid, deadline_iso, run_id)` | `run_source`, then itself | one poll; re-dispatched every `SITEINTEL_URLSCAN_POLL_INTERVAL_S` until the result arrives or the deadline passes (`timeout`) |
| `django_siteintel.finish_audit(audit_id, run_id, attempt)` | chord callback, then itself | closes the run when every report is finished and sends `report_ready`; re-checks for one poll budget plus one interval, then fails what is still running |
| `django_siteintel.expire_audits()` | beat, daily | valid audits past `expires_at` → `expired`; returns the count |
| `django_siteintel.sweep_stuck_audits()` | beat, every 10 min | audits `pending`/`running` longer than `SITEINTEL_AUDIT_STUCK_MINUTES` → `failed`, `report_ready` once; returns the count |

Tasks of a replaced run (a rerun drew a new `run_id`) find nothing and return. A `run_source` message without
`run_id` — queued by an older release — is treated as stale too.

## Reading a failed report

`Report.error_code` names the class of failure; `error_detail` names the host and the exception class, never
a body or a key. `raw` stays in the database — neither the Django admin nor the API shows it.

| `error_code` | Cause | Retried | What to do |
|---|---|---|---|
| `upstream` | connection error, DNS failure, HTTP 4xx/5xx from the source (429 included) | 3× with backoff | check the key row and quota; rerun later |
| `ssrf` | the guard refused a host — private address, or a redirect hop to one | no | nothing, unless the host is yours: `SITEINTEL_ALLOWED_HOSTS` |
| `truncated` | the body passed `SITEINTEL_MAX_PAGE_BYTES` | no | heuristic: report is `partial` with the facts of the first bytes; PSI / urlscan: report `failed` |
| `timeout` | urlscan result not ready within the poll budget; or the sweeper / `finish_audit` closed a report still running | no | rerun; raise `SITEINTEL_URLSCAN_POLL_BUDGET_S` when urlscan is routinely slow |
| `invalid` | not JSON, not an object, a required key missing, an unexpected shape, or a snapshot still too large after trimming | no | inspect `raw`; a source format change needs a code change |
| `recording_missing` | recording mode, no recorded file for the domain | no | add the recording, or point the base URL at the public API |
| `internal` | any other exception in `run_source` (detail = class name) | no | worker log; it is a bug |

An audit with at least one succeeded report is `partially_completed` and is reused like a completed one; a
consumer decides from `succeeded_sources` whether that is enough. Use `POST audits/<id>/rerun/` to refresh it.

## Outbound fetches (SSRF guard)

`security/url_guard.py` — a sibling copy of lookup's guard, never a shared import:

- `http` / `https` only; a hostname resolving to a private, loopback, link-local, reserved, multicast or
  unspecified address is refused unless listed in `SITEINTEL_ALLOWED_HOSTS`.
- Redirects are never auto-followed: each hop is re-validated, at most 3 (`MAX_REDIRECTS`); request headers
  (the PSI key) are sent only while the hop stays on the original host.
- `safe_post` (the urlscan submission) refuses any redirect.
- The body is streamed and capped at `SITEINTEL_MAX_PAGE_BYTES`; `BodyTooLarge` keeps the received bytes, which
  is how the heuristic source still reports on a truncated page.

`SITEINTEL_BLOCK_PRIVATE_HOSTS = False` drops the IP check wholesale — only for a harness whose recordings
and synthetic sites live on a private network.

## Recording mode

A base URL other than the public API makes the source read files instead of calling the service:

| Source | Files under the base URL |
|---|---|
| `lighthouse` | `<domain>.mobile.json`, `<domain>.desktop.json` — one may be missing (`"unavailable"`) |
| `urlscan` | `<domain>.submit.json` (must carry `uuid`), `<domain>.result.json` |

`<domain>` is the registrable domain of the audit. Recording mode sends no API key and still goes through the
SSRF guard, so a private recording host needs `SITEINTEL_ALLOWED_HOSTS`. The heuristic source always fetches
the audited URL.

## Adding a source

1. Subclass `SourceFetcher` (`sources/base.py`): `name`, `fetch_raw`, `validate`, `process`; for a polling
   source `polls = True`, `fetch_result`, and a `fetch_raw` that returns `{"submit": {"uuid": ...}}` — the
   runner polls every polling source through `poll_urlscan` and reads that key. Fetch through `safe_get` / `safe_post` with `fetch_options()`;
   raise `SourceError` with an `ErrorCode`.
2. Register it in the distribution's `[project.entry-points."siteintel_sources"]` and reinstall the package —
   entry points are read from installed metadata.
3. New audits get a report for it; existing audits get none until they are recreated (a rerun resets only
   the reports the audit already has).
