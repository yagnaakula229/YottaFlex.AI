from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.generation.config import GenerationConfig, ProfileName
from app.generation.export import export_dataset, hash_dataset
from app.generation.pipeline import generate_dataset
from app.generation.reset import rebuild_schema, validate_destructive_target


def _reference_time(value: str | None, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Reference timestamp must include a timezone offset.")
    return parsed


def _build_config(arguments: argparse.Namespace) -> GenerationConfig:
    settings = get_settings()
    reference_time = _reference_time(arguments.reference_time, settings.scenario_as_of)
    return GenerationConfig(
        profile=arguments.profile,
        reference_time=reference_time,
        seed=arguments.seed,
        batch_size=arguments.batch_size,
    )


def _database_settings() -> tuple[str, int]:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required.")
    return settings.database_url, settings.database_connect_timeout_seconds


def _verify_connection(database_url: str, timeout: int) -> None:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": timeout},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _write_summary(summary) -> None:
    print(
        json.dumps(
            {
                "generation_run_id": summary.generation_run_id,
                "configuration_hash": summary.configuration_hash,
                "dataset_sha256": summary.dataset_sha256,
                "requested_counts": summary.requested_counts,
                "actual_counts": summary.actual_counts,
                "already_generated": summary.already_generated,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _generate(arguments: argparse.Namespace, *, rebuild: bool) -> int:
    settings = get_settings()
    config = _build_config(arguments)
    database_url, timeout = _database_settings()
    if rebuild:
        database_name = validate_destructive_target(
            database_url,
            settings.environment,
            arguments.confirm_destructive,
        )
        print(f"Rebuilding local development database: {database_name}", file=sys.stderr)
        _verify_connection(database_url, timeout)
        rebuild_schema(database_name)
    else:
        _verify_connection(database_url, timeout)

    factory = get_session_factory(database_url, timeout)
    with factory.begin() as session:
        summary = generate_dataset(session, config)
    _write_summary(summary)
    return 0


def _hash() -> int:
    database_url, timeout = _database_settings()
    factory = get_session_factory(database_url, timeout)
    with factory() as session:
        print(hash_dataset(session))
    return 0


def _export(output_path: str) -> int:
    database_url, timeout = _database_settings()
    factory = get_session_factory(database_url, timeout)
    if output_path == "-":
        output = sys.stdout
        close_output = False
    else:
        output = Path(output_path).open("w", encoding="utf-8", newline="\n")
        close_output = True
    try:
        with factory() as session:
            digest = export_dataset(session, output)
    finally:
        if close_output:
            output.close()
    print(f"sha256={digest}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic YottaFlex synthetic data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("generate", "rebuild"):
        generation_parser = subparsers.add_parser(command_name)
        generation_parser.add_argument("--profile", choices=("small", "scale"), required=True)
        generation_parser.add_argument("--seed", type=int, default=20261022)
        generation_parser.add_argument("--reference-time")
        generation_parser.add_argument("--batch-size", type=int, default=1_000)
        if command_name == "rebuild":
            generation_parser.add_argument("--confirm-destructive", action="store_true")

    subparsers.add_parser("hash")
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--output", default="-")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        if arguments.command == "generate":
            return _generate(arguments, rebuild=False)
        if arguments.command == "rebuild":
            return _generate(arguments, rebuild=True)
        if arguments.command == "hash":
            return _hash()
        return _export(arguments.output)
    except Exception as exc:
        parser.exit(2, f"generation failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())