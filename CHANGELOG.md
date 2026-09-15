# Changelog

## 0.1.0 (unreleased)

First release. Domain intelligence for Volkanos: one audit per registrable domain and channel, one cleaned
report per source, reused while valid, announced by the `report_ready` signal.

- **Audits and reports.** `Audit` keyed by registrable domain (eTLD+1 from a short multi-part suffix list,
  never substring matching), `Report` unique per audit and source, `ExternalApiKey` per source.
  `audit_service.request_audit` reuses the newest valid audit of the domain in the same channel — nothing is
  fetched and `report_ready` is sent at once — or creates a pending audit with one report per source.
  `rerun_audit` keeps the id and resets the reports (refused while running); `expire_audits` keeps history.
- **Sources** through the entry-point group `siteintel_sources`: PageSpeed Insights v5 (mobile and desktop;
  key in the `X-Goog-Api-Key` header), urlscan.io (submit, then countdown polling — no sleep in the worker),
  and a heuristic fetch of the page (title, meta, images without alt, inline scripts, bytes, redirects,
  viewport). Recording mode reads `{base}/{domain}.{strategy}.json` when a base URL is not the public API.
- **Run lifecycle** on queue `siteintel_default`: `run_audit` → chord of `run_source` → `finish_audit`,
  `report_ready` once per run. Only `upstream` errors retry (3×, backoff); any unexpected exception fails the
  report `internal` so the chord always completes. Every task carries the audit's `run_id` and ignores a run
  a rerun replaced. `sweep_stuck_audits` (beat, 10 min) fails audits running longer than
  `SITEINTEL_AUDIT_STUCK_MINUTES` and signals once. Poll interval and budget are clamped at read time.
- **Safety.** SSRF guard on every outbound request (every redirect hop re-validated, headers never sent to
  another host, body capped); `processed` snapshots stripped of base64 and screenshots, lists trimmed, bounded
  to 64 KB; NUL characters removed before save; `raw` and keys never returned.
- **Admin API v2** under `api/siteintel/v2/admin/<channel_idx>/`: list, detail, request (201 new / 200 reused;
  400 for a URL over 2048 characters), rerun (202; 409 while running). Development-only `test/run-now/` and
  `test/expire-now/`.
- **Docs.** `docs/` — `concept.md`, `install.md`, `api.md`, `operations.md`, `gotchas.md`, `testing.md`,
  `openapi.yaml`, `erd-config.yaml`.
- **Edge cases covered:** S-01 … S-09 in the unit suite; S-01, S-08, S-09 also in the emporium BDD feature
  `@siteintel`.
