"""In-memory petition store.

Simple dict-based store keyed by petition_id.  Swap for SQLite / Redis
in production.
"""

from __future__ import annotations

from va_name_change.models import NameChangePetition

_store: dict[str, NameChangePetition] = {}


def save(petition: NameChangePetition) -> None:
    _store[petition.petition_id] = petition


def get(petition_id: str) -> NameChangePetition | None:
    return _store.get(petition_id)


def list_all() -> list[NameChangePetition]:
    return list(_store.values())
