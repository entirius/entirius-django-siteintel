# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Configuration health checks (tag ``entirius_config``, probes ``entirius_probe``), aggregated by django-munin.

Warnings only: a config gap must never stop ``runserver`` or ``migrate``. The key rows are read only when the
caller passes ``databases`` (``manage.py check --database default``, munin's endpoint) — never at boot — and
only once the table exists: ``migrate`` runs the checks with ``databases`` before it creates anything.
"""

from django.core import checks
from django.db import connections

from django_siteintel.services.source_status import (
    SOURCES,
    KeyedSource,
    SourceStatus,
    has_key,
    key_probe,
    recording_host,
)

SOURCES_CODE = "siteintel.sources"
KEYS_CODE = "siteintel.keys"
_DOCS = "https://github.com/entirius/entirius-django-siteintel/blob/master/docs/install.md"
SETTINGS_FIX_URL = f"{_DOCS}#settings"
KEYS_FIX_URL = f"{_DOCS}#api-keys"
# urlscan refuses every submit without a key; PSI runs anonymously on a quota that fails under load.
_MISSING_KEY = {
    "lighthouse": ("medium", "audits run on the anonymous PSI quota and fail with `upstream` under load."),
    "urlscan": ("high", "every urlscan submit fails with 401 (`upstream`)."),
}
_PROBE_FAILURES = (SourceStatus.AUTH_FAILED, SourceStatus.UNREACHABLE)


class _Subject(dict):
    """Row metadata munin reads as a dict; `manage.py check` prints `str(obj)` as the label, so name the subject."""

    def __str__(self) -> str:
        return self.get("scope") or "settings"


@checks.register("entirius_config", SOURCES_CODE)
def sources_configured(app_configs=None, databases=None, **kwargs) -> list[checks.CheckMessage]:
    """Recording mode per source (settings only); a missing key per live source (DB, guarded)."""
    live = [source for source in SOURCES if not recording_host(source)]
    recording = [_recording(source) for source in SOURCES if source not in live]
    if not live or not _key_table_ready(databases):
        return recording
    return recording + [_key_missing(source) for source in live if not has_key(source)]


@checks.register("entirius_probe", KEYS_CODE, deploy=True)
def keys_accepted(app_configs=None, databases=None, **kwargs) -> list[checks.CheckMessage]:
    """One authenticated call per active key (cached 60 s) — runs only on request, never at boot."""
    if not _key_table_ready(databases):  # keys live in the DB: `check --deploy` without --database, or before migrate
        return []
    failing = {source.name: state for source in SOURCES if (state := key_probe(source)) in _PROBE_FAILURES}
    return [_probe_failed(name, state) for name, state in failing.items()]


def _key_table_ready(databases) -> bool:
    from django_siteintel.models import ExternalApiKey

    return (
        "default" in (databases or ())
        and ExternalApiKey._meta.db_table in connections["default"].introspection.table_names()
    )


def _recording(source: KeyedSource) -> checks.Warning:
    return _warning(
        f"{source.name} audits read recorded answers",
        f"Audits read recorded answers from {recording_host(source)}, real sites are not audited. "
        f"Unset {source.setting} (default {source.public_url}).",
        _Subject(scope=source.name, state=SourceStatus.RECORDING, severity="high", fix_url=SETTINGS_FIX_URL),
    )


def _key_missing(source: KeyedSource) -> checks.Warning:
    severity, effect = _MISSING_KEY[source.name]
    return _warning(
        f"No active {source.name} API key",
        f"Add an active ExternalApiKey '{source.name}' in the Django admin; until then {effect}",
        _Subject(scope=source.name, state=SourceStatus.UNCONFIGURED, severity=severity, fix_url=KEYS_FIX_URL),
    )


def _probe_failed(name: str, state: SourceStatus) -> checks.Warning:
    if state == SourceStatus.AUTH_FAILED:
        title, detail = f"{name} rejects the API key", f"Replace the ExternalApiKey '{name}' in the Django admin."
    else:
        title, detail = f"{name} API unreachable", "No usable answer within 5 s: check outbound HTTPS from the server."
    subject = _Subject(scope=name, state=state, severity="high", fix_url=KEYS_FIX_URL)
    return _warning(title, detail, subject, code=KEYS_CODE)


def _warning(title: str, detail: str, subject: _Subject, code: str = SOURCES_CODE) -> checks.Warning:
    return checks.Warning(title, hint=detail, id=code, obj=subject)
