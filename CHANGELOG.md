# Changelog

## 0.1.0 (unreleased)

- Audits per registrable domain with reuse while valid, rerun and daily expiry; `report_ready` signal.
- Sources via entry points `siteintel_sources`: PageSpeed Insights, urlscan.io (countdown polling), heuristic fetch;
  recording mode for recorded answers.
- SSRF guard on every outbound request; cleaned, size-bounded `processed` snapshots.
- Admin API v2 (list, detail, request, rerun) and development-only `test/run-now/`, `test/expire-now/`.
- Channel-scoped reuse; rerun refused (409) while running, stale tasks of a replaced run ignored (`run_id`);
  unexpected source errors and a 10-minute stuck-audit sweeper never leave an audit `running`; clamped poll settings;
  PSI key in a header; over-long URLs are a 400.
