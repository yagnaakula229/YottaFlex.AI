import csv
import json
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.evaluation.base import EvaluationBase
from app.evaluation.models import EvaluationRun, GroundTruthLabel
from app.generation.config import GenerationConfig
from app.generation.export import export_csv, export_dataset, export_sql, hash_dataset
from app.generation.pipeline import GENERATION_ORDER, generate_dataset
from app.models import (
    Campaign,
    CampaignTemplate,
    Cart,
    CartEvent,
    CartLine,
    Consent,
    ConsentEvent,
    Customer,
    CustomerSession,
    GenerationRun,
    MessageEvent,
    MessageTemplate,
    Order,
    SendAttempt,
    SendSchedule,
)

pytestmark = pytest.mark.integration
REFERENCE_TIME = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def generation_session():
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

    engine = create_engine(settings.test_database_url, pool_pre_ping=True)
    all_tables = [*Base.metadata.tables.values(), *EvaluationBase.metadata.tables.values()]
    qualified_tables = ", ".join(
        f'"{table.schema or "public"}"."{table.name}"' for table in all_tables
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {qualified_tables} CASCADE"))

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()
    engine.dispose()


def test_small_generation_manifest_relations_and_truth_separation(generation_session: Session) -> None:
    config = GenerationConfig(profile="small", reference_time=REFERENCE_TIME)
    first = generate_dataset(generation_session, config)

    assert GENERATION_ORDER == (
        "customers_and_consent",
        "sessions",
        "campaigns_templates_mappings",
        "carts_lines_events",
        "orders",
        "schedules_attempts_message_events",
        "evaluation_truth_labels",
        "generation_manifest",
    )
    assert first.requested_counts["carts"] == 100
    assert first.actual_counts["cart"] == 100
    assert first.actual_counts["operationally_abandoned_carts"] == 40
    assert first.actual_counts["orders"] == 10
    assert first.actual_counts["attribution"] == 0
    assert first.actual_counts["send_attempt"] <= 10_000
    assert "MSG--01" not in {
        row[0]
        for row in generation_session.execute(
            select(Cart.business_id).where(Cart.business_id == "MSG--01")
        )
    }

    manifest = generation_session.get(GenerationRun, first.generation_run_id)
    assert manifest is not None
    assert manifest.seed == 20261022
    assert manifest.profile == "small"
    assert manifest.configuration_hash == config.configuration_hash
    assert manifest.generator_version
    assert manifest.requested_counts == config.requested_counts
    assert manifest.actual_counts["dataset_sha256"] == first.dataset_sha256
    assert manifest.reference_timestamp == REFERENCE_TIME
    assert hash_dataset(generation_session) == first.dataset_sha256

    second = generate_dataset(generation_session, config)
    assert second.already_generated is True
    assert second.dataset_sha256 == first.dataset_sha256

    cutoff = REFERENCE_TIME - timedelta(minutes=config.inactivity_minutes)
    operationally_abandoned = generation_session.scalar(
        select(func.count(Cart.business_id))
        .outerjoin(Order, Order.cart_id == Cart.business_id)
        .where(Cart.updated_at <= cutoff, Cart.status == "abandoned", Order.business_id.is_(None))
    )
    assert operationally_abandoned == 40

    sends_without_consent = generation_session.scalar(
        select(func.count(SendSchedule.business_id))
        .join(
            Consent,
            (Consent.customer_id == SendSchedule.customer_id)
            & (Consent.channel == SendSchedule.channel),
        )
        .where(Consent.state != "granted")
    )
    assert sends_without_consent == 0
    schedules_per_customer = (
        select(func.count(SendSchedule.business_id).label("schedule_count"))
        .group_by(SendSchedule.customer_id)
        .subquery()
    )
    max_schedules_per_customer = generation_session.scalar(
        select(func.max(schedules_per_customer.c.schedule_count))
    )
    assert max_schedules_per_customer in (None, 1)

    orphaned_attempts = generation_session.scalar(
        select(func.count(SendAttempt.business_id)).outerjoin(
            SendSchedule, SendSchedule.business_id == SendAttempt.schedule_id
        ).where(SendSchedule.business_id.is_(None))
    )
    assert orphaned_attempts == 0
    orphaned_events = generation_session.scalar(
        select(func.count(MessageEvent.business_id)).where(
            ~MessageEvent.send_attempt_id.in_(select(SendAttempt.business_id))
        )
    )
    assert orphaned_events == 0

    relationships = (
        (Consent.customer_id, Customer.business_id),
        (ConsentEvent.customer_id, Customer.business_id),
        (CustomerSession.customer_id, Customer.business_id),
        (Cart.customer_id, Customer.business_id),
        (CartLine.cart_id, Cart.business_id),
        (CartEvent.cart_id, Cart.business_id),
        (CampaignTemplate.campaign_id, Campaign.business_id),
        (CampaignTemplate.template_id, MessageTemplate.business_id),
        (Order.cart_id, Cart.business_id),
    )
    for child_column, parent_column in relationships:
        parent_model = parent_column.class_
        child_model = child_column.class_
        orphan_count = generation_session.scalar(
            select(func.count(child_column))
            .select_from(child_model)
            .outerjoin(parent_model, child_column == parent_column)
            .where(parent_column.is_(None))
        )
        assert orphan_count == 0, f"Orphan rows in {child_model.__tablename__}"

    assert "evaluation.evaluation_run" not in Base.metadata.tables
    assert "evaluation.ground_truth_label" not in Base.metadata.tables
    assert set(EvaluationBase.metadata.tables) == {
        "evaluation.evaluation_run",
        "evaluation.ground_truth_label",
    }
    assert generation_session.scalar(select(func.count()).select_from(EvaluationRun)) == 1
    labels = generation_session.scalars(select(GroundTruthLabel)).all()
    assert len(labels) == 4
    assert all(label.expected is False for label in labels)


def test_csv_and_sql_exports_are_separated_and_relationally_consistent(
    generation_session: Session,
) -> None:
    generate_dataset(
        generation_session,
        GenerationConfig(profile="small", reference_time=REFERENCE_TIME),
    )
    template = generation_session.scalar(
        select(MessageTemplate).order_by(MessageTemplate.business_id).limit(1)
    )
    assert template is not None
    template.content = 'Quoted, "text"; O\'Reilly\nsecond line'
    generation_session.flush()

    jsonl_output = StringIO()
    export_dataset(generation_session, jsonl_output)
    jsonl_rows = [json.loads(line) for line in jsonl_output.getvalue().splitlines()]
    assert all(not row["table"].startswith("evaluation.") for row in jsonl_rows)
    assert any(row["table"] == "public.generation_run" for row in jsonl_rows)

    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        csv_directory = root / "csv"
        csv_digest = export_csv(generation_session, csv_directory)
        manifest = json.loads((csv_directory / "export-manifest.json").read_text(encoding="utf-8"))

        assert manifest["format"] == "csv"
        assert manifest["evaluation_exported"] is False
        assert manifest["csv_null_sentinel"] == r"\N"
        assert manifest["csv_literal_null_sentinel"] == r"\\N"
        assert all(not table["table"].startswith("evaluation.") for table in manifest["tables"])
        assert not (csv_directory / "evaluation").exists()
        exported_tables = {}
        for table in manifest["tables"]:
            with (csv_directory / table["path"]).open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            assert len(rows) == table["row_count"]
            exported_tables[table["table"]] = rows

        customers = {row["business_id"] for row in exported_tables["public.customer"]}
        campaigns = {row["business_id"] for row in exported_tables["public.campaign"]}
        carts = {row["business_id"]: row for row in exported_tables["public.cart"]}
        schedules = {row["business_id"]: row for row in exported_tables["public.send_schedule"]}
        attempts = {row["business_id"]: row for row in exported_tables["public.send_attempt"]}
        assert len(customers) == 50
        assert len(carts) == 100
        assert len(campaigns) == 3
        assert all(row["customer_id"] in customers for row in carts.values())
        assert all(row["cart_id"] in carts for row in exported_tables["public.cart_line"])
        assert all(row["customer_id"] in customers for row in exported_tables["public.orders"])
        assert all(row["cart_id"] in carts for row in exported_tables["public.orders"])
        assert all(row["campaign_id"] in campaigns for row in schedules.values())
        assert all(row["schedule_id"] in schedules for row in attempts.values())
        assert all(
            row["send_attempt_id"] in attempts
            for row in exported_tables["public.message_event"]
        )
        assert exported_tables["public.message_template"][0]["content"] == template.content
        line_totals: dict[str, Decimal] = {}
        for row in exported_tables["public.cart_line"]:
            line_totals[row["cart_id"]] = line_totals.get(row["cart_id"], Decimal("0")) + Decimal(
                row["line_total"]
            )
        assert all(Decimal(cart["total_amount"]) == line_totals[cart_id] for cart_id, cart in carts.items())

        repeated_csv_directory = root / "csv-repeat"
        assert export_csv(generation_session, repeated_csv_directory) == csv_digest
        for table in manifest["tables"]:
            assert (csv_directory / table["path"]).read_bytes() == (
                repeated_csv_directory / table["path"]
            ).read_bytes()

        sql_output = StringIO()
        sql_digest = export_sql(generation_session, sql_output)
        sql_text = sql_output.getvalue()
        assert sql_digest
        assert sql_text.startswith("-- Operational data only;")
        assert "evaluation." not in sql_text
        assert 'INSERT INTO "public"."customer"' in sql_text
        assert 'INSERT INTO "public"."generation_run"' in sql_text
        assert "O''Reilly\\nsecond line" in sql_text
        assert sql_text.index('INSERT INTO "public"."customer"') < sql_text.index(
            'INSERT INTO "public"."cart"'
        ) < sql_text.index('INSERT INTO "public"."cart_line"')
        repeated_sql = StringIO()
        assert export_sql(generation_session, repeated_sql) == sql_digest
        assert repeated_sql.getvalue() == sql_text

        connection = generation_session.connection()
        connection.exec_driver_sql('CREATE SCHEMA "export_operational"')
        translated_connection = connection.execution_options(
            schema_translate_map={None: "export_operational"}
        )
        Base.metadata.create_all(translated_connection)
        pending_statement: list[str] = []
        for line in sql_text.splitlines():
            if line in {"BEGIN;", "COMMIT;"} or line.startswith("--"):
                continue
            pending_statement.append(line)
            if line.rstrip().endswith(";"):
                statement = "\n".join(pending_statement).replace(
                    '"public".', '"export_operational".'
                )
                connection.exec_driver_sql(statement)
                pending_statement.clear()
        assert pending_statement == []
        assert connection.exec_driver_sql(
            'SELECT count(*) FROM "export_operational"."cart"'
        ).scalar_one() == 100
        assert connection.exec_driver_sql(
            'SELECT count(*) FROM "export_operational"."orders"'
        ).scalar_one() == 10
        assert connection.exec_driver_sql(
            'SELECT count(*) FROM "export_operational"."send_attempt" a '
            'LEFT JOIN "export_operational"."send_schedule" s '
            'ON s.business_id = a.schedule_id WHERE s.business_id IS NULL'
        ).scalar_one() == 0