from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive datetimes are not valid in generated records")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


class DatasetHasher:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def add(self, namespace: str, row: dict[str, Any]) -> None:
        self._digest.update(namespace.encode("utf-8"))
        self._digest.update(b"\0")
        self._digest.update(canonical_json(row).encode("utf-8"))
        self._digest.update(b"\n")

    def hexdigest(self) -> str:
        return self._digest.hexdigest()