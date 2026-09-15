---
title: Concept
description: Audits keyed by registrable domain, one report per source, the run lifecycle, reuse and expiry, and the report_ready signal.
---

django-siteintel answers one question for any module that needs to know what a shop's website looks like:
"what do PageSpeed Insights, urlscan.io and a plain fetch of the page say about this domain?" It fetches each
source once, keeps a cleaned, size-bounded snapshot per source, reuses the result while it is valid and tells
consumers through one signal. It knows nothing about leads, companies or messages — consumers (today
`django_leads`) call `request_audit` and listen to `report_ready`.

## The model

| Model | Key | Holds |
|---|---|---|
| `Audit` | UUID; indexed by (`domain`, `status`) | the registrable `domain`, the `url` as requested, `channel_idx`, `status`, `requested_by`, `expires_at`, `run_id` |
| `Report` | unique (`audit`, `source`) | one source's result: `status`, `raw` (server-side only), `processed` (the consumer payload), `retry_count`, `duration_s`, `error_code`, `error_detail` |
| `ExternalApiKey` | unique `source` | the API key of one source, `is_active`; read at fetch time, never logged, never returned |

`domain` is the eTLD+1 of the requested host (`utils/domains.py`): the last two labels, or three when the
last two form a known multi-part suffix (`shop.com.pl`, `shop.co.uk`). `www.shop.pl/pl` and `shop.pl` are one
audit; `myshop.pl` is another — never substring matching. A host without a dot (`fixtures`) and an IP literal
are their own key. There is no public-suffix download, so an unlisted multi-part suffix collapses to its last
two labels.

## Sources

A source is a `SourceFetcher` subclass (`sources/base.py`) registered under the entry-point group
`siteintel_sources`. The contract is three steps: `fetch_raw(audit)` (network) → `validate(raw)` →
`process(raw)` (pure, returns the snapshot). A polling source sets `polls = True`, returns the submission from
`fetch_raw` and delivers the result through `fetch_result(audit, uuid)` (`None` while not ready).
`SourceError(code, detail)` is the only failure the runner maps; `detail` carries host and error class only —
never a body, a key or a URL that holds one.

| Source | Fetches | `processed` |
|---|---|---|
| `lighthouse` | PageSpeed Insights v5 `runPagespeed`, strategies `mobile` and `desktop` | `strategies.<mobile\|desktop>`: `final_url_host`, `scores` per category, `vitals` (FCP, LCP, CLS, TBT, speed index, interactive), `field_data`, `top_issues` (audits scoring < 0.9, lowest first) — or `"unavailable"` |
| `urlscan` | urlscan.io `POST /scan/` (visibility `unlisted`), then `GET /result/<uuid>/` | `page` (url, domain, ip, country, server, status, title, TLS issuer/validity), `verdict`, `stats`, request / cookie / console-message counts |
| `heuristic` | the audited URL itself | `title`, `meta_description`, `inline_script_count`, `images_without_alt`, `image_count`, `page_bytes`, `redirect_count`, `has_viewport_meta` |

Every outbound request — PSI, urlscan and the page — goes through `security/url_guard.py`
(`operations.md` § Outbound fetches).

**Recording mode.** A source whose base URL is not the public API reads recorded answers instead:
`{base}/{domain}.{strategy}.json`. PSI uses `mobile` / `desktop` — a missing strategy (404) is
`"unavailable"`, both missing fail the report `recording_missing`; urlscan uses `submit` / `result`. Recording
mode sends no API key. This is how the test harness runs the module without network or quota.

## Snapshot cleaning

`processed` is what consumers read and what may reach a prompt, so it is bounded
(`services/cleaning_service.py`, a port of the prototype's "Remove Trash"): keys containing `screenshot` or
`thumbnail` are dropped, `data:` strings and whitespace-free strings over 512 characters are dropped as blobs,
nesting is cut at depth 6, lists are trimmed to 3 items. When the JSON is still not below
`SITEINTEL_PROCESSED_MAX_BYTES` (64 KB) lists are trimmed to 1; if that is not enough the report fails
`invalid`. NUL characters are stripped from `raw` and `processed` before every save (Postgres `jsonb` rejects
U+0000).

## Lifecycle of a run

```
request_audit ──► Audit(pending) + Report(pending) per registered source ──on_commit──► run_audit
run_audit: claim pending → running; chord( run_source × sources ) → finish_audit
run_source: report running → fetch → validate → process → completed | partial | failed
            polling source → poll_urlscan (countdown re-dispatch until the poll budget) → completed | failed(timeout)
finish_audit: every report finished? → audit completed | partially_completed | failed → report_ready (once)
```

| Audit status | Meaning |
|---|---|
| `pending` | created or rerun, run queued |
| `running` | claimed by `run_audit` (or the development `run-now`) |
| `completed` | every report `completed` or `partial` |
| `partially_completed` | at least one report succeeded, at least one failed |
| `failed` | no report succeeded, or the stuck-audit sweeper failed it |
| `expired` | was valid, `expires_at` passed; kept as history |

| Report status | Meaning |
|---|---|
| `pending` / `running` | not finished |
| `completed` | snapshot stored |
| `partial` | snapshot stored from a truncated page (`error_code = truncated`) |
| `failed` | `error_code` ∈ `ssrf`, `timeout`, `upstream`, `truncated`, `invalid`, `recording_missing`, `internal` |

Retries: only `upstream` errors retry — three times, exponential backoff with jitter (capped at 600 s),
`retry_count` counts them. `ssrf`, `timeout`, `invalid`, `truncated` and `recording_missing` fail at once. Any
other exception in `run_source` fails the report `internal` with the exception class as detail, so the chord
always completes. A finished report is never reopened: every write is conditional on the report being
unfinished, which makes a late worker run next to a development `run-now` harmless.

**Run identity.** Every run carries the audit's `run_id`. A rerun draws a new one; `run_source`,
`poll_urlscan` and `finish_audit` of the previous run find no matching row and do nothing, so a stale retry
or poll never writes into the new run.

## Reuse, rerun, expiry

- **Reuse.** `request_audit(domain_or_url, channel_idx, requested_by)` returns the newest audit of the domain
  **in the same channel** that is `completed` or `partially_completed` and not past `expires_at`. It fetches
  nothing and sends `report_ready` immediately with the sources that succeeded. Another channel's audit of the
  same domain is never returned.
- **Rerun.** `rerun_audit(audit, requested_by)` keeps the audit id, resets every report to `pending` (raw,
  processed, retries and errors cleared), extends `expires_at` and queues a new run. It is refused with
  `AuditRunningError` while the audit is `running`; the caller's instance is left untouched.
- **Expiry.** `expire_audits(now=None)` marks valid audits past `expires_at` as `expired`
  (`SITEINTEL_EXPIRE_DAYS`, default 90). Rows and reports stay; the next request creates a new audit.
- **Stuck audits.** `fail_stuck_audits(now=None)` fails audits `running` longer than
  `SITEINTEL_AUDIT_STUCK_MINUTES` (default 30), marks their unfinished reports `failed(timeout)` and sends
  `report_ready` once, after the commit. A lost poll task is also bounded inside the run: `finish_audit`
  re-checks for one poll budget plus one interval, then fails whatever is still running.

## The `report_ready` signal

`django_siteintel.signals.report_ready`, sender `Audit`, arguments `audit` and `succeeded_sources`
(sorted source names). Sent exactly once per finished run, once per stuck-audit sweep, and synchronously on
every reuse. It is the module's only outward contract besides the admin API — a consumer that needs to do
work (analysis, a prompt) queues its own task from the receiver.
