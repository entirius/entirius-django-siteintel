# entirius-django-siteintel

A Django module for domain intelligence in Entirius, the open-source modular ecommerce platform.
It audits a website per registrable domain with PageSpeed Insights, urlscan.io and its own heuristic fetch,
and announces the finished audit with one signal.

[![PyPI](https://img.shields.io/pypi/v/entirius-django-siteintel.svg)](https://pypi.org/project/entirius-django-siteintel/)
[![Python](https://img.shields.io/pypi/pyversions/entirius-django-siteintel.svg)](https://pypi.org/project/entirius-django-siteintel/)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](https://github.com/entirius/entirius-django-siteintel/blob/develop/LICENSE)

## What it does

- Audits a domain with three sources: PageSpeed Insights (Lighthouse), urlscan.io and a heuristic page fetch.
- Reuses the valid audit of a domain within a channel instead of fetching again; audits expire on a schedule.
- Announces every finished run once through the `report_ready` signal, with the sources that succeeded.
- Guards its own fetches against private hosts and oversized pages, and trims stored snapshots.
- Loads sources from the `siteintel_sources` entry-point group, so a host can add its own.
- Exposes an admin API (JWT, Pydantic schemas, OpenAPI) for the CMS.

## Installation

```shell
uv add entirius-django-siteintel
pip install entirius-django-siteintel
```

```python
INSTALLED_APPS = [
    # ...
    "django_utils",
    "django_siteintel",
]

# main/urls.py
urlpatterns.append(path("", include("django_siteintel.urls")))
```

The module needs a Celery worker consuming the `siteintel_default` queue and two beat entries. The
`SITEINTEL_*` settings, the API keys of the sources and the bootstrap order: `docs/install.md` —
https://github.com/entirius/entirius-django-siteintel/blob/develop/docs/install.md

## Quick start

```python
from django_siteintel.services.audit_service import request_audit

audit = request_audit(
    domain_or_url="example.com",
    channel_idx="my-channel",
    requested_by="leads.Company:42",
)
```

The call returns the valid audit of the domain or queues a new run. Connect a receiver to
`django_siteintel.signals.report_ready` (`audit`, `succeeded_sources`) to act on the result.

## Requirements

- Python 3.11 or newer, Django 4.2 or newer.
- PostgreSQL.
- A Celery worker consuming the `siteintel_default` queue, and Celery beat.
- Entirius packages pulled in: `entirius-django-utils`.

## Documentation

- Module docs: https://github.com/entirius/entirius-django-siteintel/tree/develop/docs
- Entirius documentation: https://docs.entirius.com/
- Changelog: https://github.com/entirius/entirius-django-siteintel/blob/develop/CHANGELOG.md

## Part of Entirius

This module runs inside the Entirius backend service (Volkanos); the leads module requests audits from it.

- Backend service: https://github.com/entirius/entirius-service-volkanos
- Docker harness: https://github.com/entirius/entirius-zeno
- Sibling modules: https://github.com/entirius/entirius-django-leads, https://github.com/entirius/entirius-django-communicator,
  https://github.com/entirius/entirius-django-utils

## Development

```shell
make install     # sync dependencies (uv, incl. extras)
make check       # lint + format check (ruff)
make test        # test suite (pytest; PostgreSQL through DATABASE_URL)
```

Development and agent instructions: https://github.com/entirius/entirius-django-siteintel/blob/develop/AGENTS.md

## License

Mozilla Public License 2.0 (MPL-2.0) — see https://github.com/entirius/entirius-django-siteintel/blob/develop/LICENSE.
