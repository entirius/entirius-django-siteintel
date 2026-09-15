---
title: Admin API
description: Audits of a channel — list, detail, request, rerun; development-only run-now and expire-now. Shapes, auth, errors.
---

Endpoints under `/api/siteintel/v2/admin/<channel_idx>/` (the host mounts `django_siteintel.urls`). Every
audit is scoped to the channel in the path: an audit of another channel answers 404. The machine-readable
contract is `docs/openapi.yaml` (exported from the Volkanos service, filtered to this prefix, `test/` routes excluded).

Views are thin (`api/admin/views/`): parse into a Pydantic request schema, call `services.audit_service`,
serialise a response schema. The list and detail views read the ORM directly for filtering and pagination.

## Auth

| | |
|---|---|
| Authentication | `JWTAuthentication` — declared on the views, never inherited from service defaults |
| Permission | `IsAdminUser` (staff) |
| Throttle | none of its own — the host's defaults apply |

## Endpoints

| Method and path | Answer |
|---|---|
| `GET audits/?domain=&status=&ordering=&page=&page_size=` | 200 `AuditListResponse` — paginated, 20 per page, `page_size` ≤ 100 |
| `GET audits/<uuid>/` | 200 `AuditDetailResponse` — the audit plus one `ReportResponse` per source, sorted by source |
| `POST audits/` | 201 `AuditResponse` (new, `pending`) or 200 (the valid audit of the domain, reused — nothing fetched) |
| `POST audits/<uuid>/rerun/` | 202 `AuditResponse` (same id, `pending`); 409 while the audit is `running` |
| `POST test/run-now/<uuid>/` | development only — every source inline, urlscan polled once, audit finished; 200 `AuditDetailResponse` |
| `POST test/expire-now/` | development only — `expire_audits(now)`; 200 `{"expired": N}` |

The two `test/` routes are registered only when `settings.ENVIRONMENT == "development"` at URL import time,
and their views answer 404 in any other environment even when a host mounts them anyway. They exist so BDD
can finish an audit without waiting for the worker and reset the reuse window without waiting 90 days.

## Requests

| Schema | Field | Rules |
|---|---|---|
| list query | `domain` | ≤ 2048; a domain or URL, matched on its registrable domain (`https://www.shop.example/x` finds `shop.example`) |
| | `status` | an `AuditStatus` value |
| | `ordering` | `created_at`, `domain` or `status`, optional `-`; default `-created_at` |
| `AuditCreateRequest` | `domain_or_url` | required, 1–2048; `https://` is added when no scheme is given, and the result must still fit 2048 |
| | `requested_by` | required, 1–200; a subject reference such as `leads.Company:42` |
| `AuditRerunRequest` | `requested_by` | optional, 1–200; defaults to `admin:<username>` |
| `ExpireNowRequest` | `now` | ISO datetime or null (server time) |

Create, rerun and expire-now forbid unknown fields; the list query ignores them.

## Responses

`AuditResponse`: `id`, `domain`, `url`, `channel_idx`, `status`, `requested_by`, `expires_at`, `created_at`,
`modified_at`. `AuditDetailResponse` adds `reports`.

`ReportResponse`:

| Key | Meaning |
|---|---|
| `source` | `lighthouse`, `urlscan`, `heuristic` (or a host-registered source) |
| `status` | `pending`, `running`, `completed`, `partial`, `failed` |
| `processed` | the cleaned snapshot (`concept.md` § Sources) — bounded to `SITEINTEL_PROCESSED_MAX_BYTES` |
| `retry_count` | upstream retries made |
| `duration_s` | fetch-to-result seconds, or null |
| `error_code`, `error_detail` | empty on success; otherwise the code and "host: error class" |
| `modified_at` | last change |

`Report.raw` and `ExternalApiKey` values never appear in any response.

## Errors

| Status | Cause |
|---|---|
| 400 | schema validation (`raise_pydantic_as_drf`, v2 shape); `domain_or_url` / `domain` without a usable host, or over 2048 characters with the scheme added |
| 401 | no or invalid JWT |
| 403 | authenticated but not staff |
| 404 | audit id unknown or in another channel; `test/` routes outside development |
| 409 | `rerun/` while the audit is `running` (`audit_running`); `rerun/` while another audit of the same domain is `pending` or `running` on the channel (`audit_in_flight`) |

## OpenAPI

Every view is `@extend_schema`-annotated (tags `Siteintel` and `Siteintel (development)`, operation ids
`siteintel_*`) and generates without warnings when the host sets `OAS_VERSION = "3.1.0"`. `docs/openapi.yaml`
carries the three production routes; the development-only `test/` routes are left out.
