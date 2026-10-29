from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy import MetaData, select
from sqlalchemy.types import JSON
from sqlalchemy.orm import Session

from app.db.base import Base
from app.evaluation.base import EvaluationBase
from app.generation.serialization import DatasetHasher, canonical_json, canonical_value

EXCLUDED_MANIFEST_TABLES = {"generation_run"}
SQL_BATCH_SIZE = 250


def _table_rows(
    session: Session,
    metadata: MetaData,
    *,
    include_generation_manifest: bool = False,
) -> Iterable[tuple[str, dict[str, Any]]]:
    tables = sorted(metadata.tables.values(), key=lambda table: table.fullname)
    for table in tables:
        if not include_generation_manifest and table.name in EXCLUDED_MANIFEST_TABLES:
            continue
        primary_key = tuple(table.primary_key.columns)
        statement = select(table).order_by(*primary_key).execution_options(stream_results=True)
        for row in session.execute(statement).mappings().yield_per(1_000):
            schema_name = table.schema or "public"
            yield f"{schema_name}.{table.name}", dict(row)


def iter_dataset_rows(session: Session) -> Iterable[tuple[str, dict[str, Any]]]:
    yield from _table_rows(session, Base.metadata)
    yield from _table_rows(session, EvaluationBase.metadata)


def iter_operational_export_rows(session: Session) -> Iterable[tuple[str, dict[str, Any]]]:
    yield from _table_rows(session, Base.metadata, include_generation_manifest=True)


def hash_dataset(session: Session) -> str:
    hasher = DatasetHasher()
    for namespace, row in iter_dataset_rows(session):
        hasher.add(namespace, row)
    return hasher.hexdigest()


def export_dataset(session: Session, output: TextIO) -> str:
    hasher = DatasetHasher()
    for namespace, row in iter_operational_export_rows(session):
        serialized = canonical_json({"table": namespace, "row": row})
        output.write(serialized)
        output.write("\n")
        hasher.add(namespace, row)
    return hasher.hexdigest()


def _prepare_export_directory(output_dir: str | Path) -> Path:
    directory = Path(output_dir)
    if directory.exists():
        if not directory.is_dir():
            raise NotADirectoryError(directory)
        if any(directory.iterdir()):
            raise FileExistsError(f"Export directory must be empty: {directory}")
    else:
        directory.mkdir(parents=True)
    return directory


def _csv_value(value: Any, column_type: Any) -> str:
    if value is None:
        return r"\N"
    if isinstance(column_type, JSON):
        return canonical_json(value)
    normalized = canonical_value(value)
    if normalized == r"\N":
        return r"\\N"
    if isinstance(normalized, bool):
        return "true" if normalized else "false"
    return str(normalized)


def _sql_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f"E'{escaped}'"


def _sql_literal(value: Any, column_type: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(column_type, JSON):
        cast = "jsonb" if column_type.__class__.__name__ == "JSONB" else "json"
        return f"{_sql_quote(canonical_json(value))}::{cast}"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be exported to SQL")
        return repr(value)
    return _sql_quote(str(canonical_value(value)))


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _export_manifest(
    *,
    export_format: str,
    dataset_sha256: str,
    tables: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "format": export_format,
        "dataset_sha256": dataset_sha256,
        "evaluation_exported": False,
        "csv_null_sentinel": r"\N" if export_format == "csv" else None,
        "csv_literal_null_sentinel": r"\\N" if export_format == "csv" else None,
        "tables": tables,
    }


def export_csv(session: Session, output_dir: str | Path) -> str:
    directory = _prepare_export_directory(output_dir)
    hasher = DatasetHasher()
    table_manifest: list[dict[str, object]] = []

    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.fullname):
        namespace = f"{table.schema or 'public'}.{table.name}"
        relative_path = Path("operational") / f"{(table.schema or 'public')}__{table.name}.csv"
        output_path = directory / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        statement = select(table).order_by(*tuple(table.primary_key.columns))
        row_count = 0
        with output_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(column.name for column in table.columns)
            for mapping in session.execute(statement).mappings().yield_per(1_000):
                row = dict(mapping)
                writer.writerow(
                    _csv_value(row[column.name], column.type)
                    for column in table.columns
                )
                hasher.add(namespace, row)
                row_count += 1
        table_manifest.append(
            {
                "table": namespace,
                "path": relative_path.as_posix(),
                "row_count": row_count,
            }
        )

    dataset_sha256 = hasher.hexdigest()
    manifest = _export_manifest(
        export_format="csv",
        dataset_sha256=dataset_sha256,
        tables=table_manifest,
    )
    (directory / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return dataset_sha256


def _write_sql_table(session: Session, table: Any, output: TextIO, hasher: DatasetHasher) -> int:
    namespace = f"{table.schema or 'public'}.{table.name}"
    column_names = [column.name for column in table.columns]
    target = ".".join(
        _quote_identifier(part)
        for part in (table.schema or "public", table.name)
    )
    quoted_columns = ", ".join(_quote_identifier(name) for name in column_names)
    statement = select(table).order_by(*tuple(table.primary_key.columns))
    batch: list[dict[str, Any]] = []
    row_count = 0

    def write_batch(rows: list[dict[str, Any]]) -> None:
        values = []
        for row in rows:
            values.append(
                "(" + ", ".join(
                    _sql_literal(row[column.name], column.type)
                    for column in table.columns
                ) + ")"
            )
        output.write(f"INSERT INTO {target} ({quoted_columns}) VALUES\n")
        output.write(",\n".join(values))
        output.write(";\n")

    for mapping in session.execute(statement).mappings().yield_per(1_000):
        row = dict(mapping)
        hasher.add(namespace, row)
        batch.append(row)
        row_count += 1
        if len(batch) == SQL_BATCH_SIZE:
            write_batch(batch)
            batch.clear()
    if batch:
        write_batch(batch)
    return row_count


def export_sql(session: Session, output: TextIO) -> str:
    hasher = DatasetHasher()
    output.write("-- Operational data only; apply Alembic migrations before importing.\n")
    output.write("-- Evaluation data and ground-truth labels are intentionally excluded.\n")
    output.write("BEGIN;\n")
    for table in Base.metadata.sorted_tables:
        _write_sql_table(session, table, output, hasher)
    output.write("COMMIT;\n")
    return hasher.hexdigest()