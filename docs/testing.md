---
title: Test suite map
description: Which test file covers what, and which edge-case IDs it carries.
---

Postgres only (`tests/settings.py`): `DATABASE_URL` wins (zeno container), else
`postgresql://entirius:entirius-dev@localhost:5532/entirius` (zeno's published port). HTTP is never real:
`tests/fake_http.py` patches `requests` and records every call; `recordings` (conftest) serves PSI / urlscan
recordings for `example-shop-1.test` and a synthetic page. `ENVIRONMENT = "development"`, so the `test/`
routes are mounted. Edge-case IDs (`S-01` … `S-09`) return in the test names.

| File | Covers |
|---|---|
| `test_audit_service.py` | a new audit has one pending report per source and queues a run; S-01 reuse (no fetch, signal at once) and reuse scoped to the channel; S-02 expiry keeps history; the shifted-clock expiry; S-09 rerun resets reports under the same id, refused while running, instance left unchanged; the stuck-audit sweeper fails and signals once; item7 two real threads racing `request_audit` for one domain/channel leave exactly one audit; item1 rerun refused while another audit is in flight; item2 a lost pending audit is swept and stops blocking; item4 a race loser never gets `None` |
| `test_tasks.py` | S-03 upstream retries then `partially_completed` with the succeeded sources; `ssrf` fails at once without retry; S-04 urlscan poll deadline → `timeout`, no sleep; task names and queues; a late worker run never reopens an audit finished by run-now; unexpected payload shape → `invalid`; unexpected exception → `internal`; NUL stripping; stale poll / stale `run_source` ignored after a rerun; a zero poll interval does not loop |
| `test_sources.py` | three entry points resolve; S-07 cleaning strips base64, trims lists, stays under 64 KB, and a snapshot still too large is `invalid`; S-08 heuristic facts differ per synthetic site; PSI recording mode (missing strategy `unavailable`, no recording at all); PSI key only in the header, never in the URL or an error detail; urlscan live submit and result-404-means-not-ready |
| `test_url_guard.py` | S-05 private host and redirect to 10.x refused on every hop; S-06 page over the cap → `partial(truncated)`; guard armed by default |
| `test_admin_api.py` | request 201 → run-now → request 200 with the same id; never `raw` or keys in a body; detail query count ≤ 3; list filters and the sort allowlist; rerun 202 and S-09 rerun 409; item1 rerun 409 while another audit is in flight; invalid domain 400, 401, 403; another channel's audit 404; `test/` routes absent outside development; an over-long domain without scheme is 400 |
| `test_domains.py` | registrable-domain table; `myshop` is not `shop`; unusable input raises |
| `test_package.py` | no `time.sleep` anywhere in `src/`; the OpenAPI document validates; migrations are complete |
| `test_admin.py` | item6 the `ExternalApiKey` change form never renders the stored key; a blank submit keeps it; a new value replaces it; the add form requires a key |
| `test_migrations.py` | item5 migration `0003` fails all but the newest duplicate in-flight audit before adding the constraint |

BDD (emporium `features/siteintel/siteintel_audit.feature`, tag `@siteintel`) covers S-01, S-08 and S-09
against zeno with the recordings in `fixtures/siteintel/`; the leads funnel (`@funnel`) exercises the module
end to end through a stage rule. See `AGENTS.md` § Testing end-to-end.
