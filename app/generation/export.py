from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TextIO

from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.evaluation.base import EvaluationBase
from app.generation.serialization import DatasetHasher, canonical_json

EXCLUDED_MANIFEST_TABLES = {"generation_run"}


def _table_rows(session: Session, metadata: MetaData) -> Iterable[tuple[str, dict[str, Any]]]:
    tables = sorted(metadata.tables.values(), key=lambda table: table.fullname)
    for table in tables:
        if table.name in EXCLUDED_MANIFEST_TABLES:
            continue
        primary_key = tuple(table.primary_key.columns)
        statement = select(table).order_by(*primary_key).execution_options(stream_results=True)
        for row in session.execute(statement).mappings().yield_per(1_000):
            schema_name = table.schema or "public"
            yield f"{schema_name}.{table.name}", dict(row)


def iter_dataset_rows(session: Session) -> Iterable[tuple[str, dict[str, Any]]]:
    yield from _table_rows(session, Base.metadata)
    yield from _table_rows(session, EvaluationBase.metadata)


def hash_dataset(session: Session) -> str:
    hasher = DatasetHasher()
    for namespace, row in iter_dataset_rows(session):
        hasher.add(namespace, row)
    return hasher.hexdigest()


def export_dataset(session: Session, output: TextIO) -> str:
    hasher = DatasetHasher()
    for namespace, row in iter_dataset_rows(session):
        serialized = canonical_json({"table": namespace, "row": row})
        output.write(serialized)
        output.write("\n")
        hasher.add(namespace, row)
    return hasher.hexdigest()