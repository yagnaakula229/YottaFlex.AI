from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session


def insert_batches(
    session: Session,
    model: type,
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int,
    counts: dict[str, int],
    namespace: str | None = None,
) -> int:
    table_namespace = namespace or model.__tablename__
    buffer: list[dict[str, Any]] = []
    inserted = 0

    for row in rows:
        buffer.append(row)
        if len(buffer) >= batch_size:
            session.execute(insert(model), buffer)
            inserted += len(buffer)
            buffer.clear()

    if buffer:
        session.execute(insert(model), buffer)
        inserted += len(buffer)

    counts[table_namespace] = counts.get(table_namespace, 0) + inserted
    return inserted