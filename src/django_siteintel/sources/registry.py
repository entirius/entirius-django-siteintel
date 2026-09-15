# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Entry-point discovery of sources (group `siteintel_sources`) — the atlas connector registry pattern."""

from importlib import metadata

from django_siteintel.sources.base import SourceFetcher

_ENTRY_POINTS_GROUP = "siteintel_sources"
_REGISTRY: dict[str, type[SourceFetcher]] = {}


def discover_sources() -> dict[str, type[SourceFetcher]]:
    if _REGISTRY:
        return _REGISTRY
    for entry_point in metadata.entry_points(group=_ENTRY_POINTS_GROUP):
        source_cls = entry_point.load()
        if not isinstance(source_cls, type) or not issubclass(source_cls, SourceFetcher):
            raise TypeError(f"Entry point '{entry_point.name}' did not resolve to a SourceFetcher subclass")
        _REGISTRY[source_cls.name] = source_cls
    return _REGISTRY


def reset_registry_for_tests() -> None:
    """Test helper — clear the cache so fresh discovery runs after monkeypatch."""
    _REGISTRY.clear()


def get_source(name: str) -> SourceFetcher:
    registry = discover_sources()
    try:
        return registry[name]()
    except KeyError as exc:
        raise KeyError(f"source '{name}' is not registered") from exc


def list_sources() -> list[str]:
    return sorted(discover_sources())
