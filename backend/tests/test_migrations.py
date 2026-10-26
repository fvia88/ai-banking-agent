"""Upgrade real disposable schemas; never use the configured application database."""
import importlib.util
import os
import uuid

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa

from app.db.migrate import BACKEND_ROOT, upgrade_database
from app.db.models import Base


@pytest.fixture(params=["sqlite", "postgresql"])
def migration_engine(tmp_path, request):
    if request.param == "sqlite":
        engine = sa.create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
        yield engine
        engine.dispose()
        return
    url = os.getenv("MIGRATION_TEST_POSTGRES_ADMIN_URL")
    if not url:
        pytest.skip("Set MIGRATION_TEST_POSTGRES_ADMIN_URL to test disposable PostgreSQL databases")
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    database = "migration_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    engine = sa.create_engine(sa.engine.make_url(url).set(database=database))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE "{database}"'))
        admin.dispose()


def run_to(engine, revision):
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table: connection.execute(sa.text('SELECT ' + ', '.join(
                '"' + column["name"] + '"' for column in sa.inspect(connection).get_columns(table)
                if column["name"] != "daily_transfer_date"
            ) + f' FROM "{table}"')).all()
            for table in ("users", "accounts", "transactions", "audit_logs")
        }


@pytest.mark.parametrize("schema", ["legacy", "manual", "current"])
def test_upgrade_preserves_data_and_repeats(migration_engine, schema):
    engine = migration_engine
    if schema == "current":
        Base.metadata.create_all(engine)  # Existing create_all installation without version tracking.
    else:
        run_to(engine, "0001_legacy_schema")
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE alembic_version"))
            if schema == "manual":
                for name in ("mfa_issued_at", "mfa_expires_at", "mfa_consumed_at"):
                    connection.execute(sa.text(f"ALTER TABLE action_approvals ADD COLUMN {name} TIMESTAMP"))
                connection.execute(sa.text("ALTER TABLE action_approvals ADD COLUMN audit_id VARCHAR(64)"))
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users VALUES ('u', 'Preserve me', false, '2026-10-24')"))
        connection.execute(sa.text("INSERT INTO accounts (account_id, user_id, account_number, currency, balance, daily_transfer_total, created_at) VALUES ('a', 'u', '123', 'CNY', 123.45, 20.00, '2026-10-24')"))
        connection.execute(sa.text("INSERT INTO transactions VALUES ('t', 'a', '2026-10-24T00:00:00+00:00', 20.00, 'debit', 'Bob', 'Transfers')"))
        connection.execute(sa.text("INSERT INTO audit_logs VALUES ('aud', 'act', 'u', 'TRANSFER', 'digest', 'OK', 'Keep audit', '2026-10-24')"))
        connection.execute(sa.text("""INSERT INTO action_approvals
            (action_id, user_id, tool, tier, payload_json, action_digest, status,
             failed_attempts, created_at, expires_at)
            VALUES ('act', 'u', 'request_transfer', 'YELLOW', '{}', 'digest',
                    'COMPLETED', 0, '2026-10-24', '2026-10-25')"""))
    before = snapshot(engine)
    upgrade_database(engine)
    upgrade_database(engine)
    assert snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0004_transfer_day"
        assert connection.scalar(sa.text("SELECT daily_transfer_date FROM accounts WHERE account_id='a'")) is not None
        assert connection.execute(sa.text("SELECT status, mfa_issued_at, mfa_expires_at, mfa_consumed_at, audit_id FROM action_approvals")).one() == ("COMPLETED", None, None, None, None)
    # Full ORM select previously failed when even one mapped column was absent.
    with sa.orm.Session(engine) as session:
        from app.db.models import ActionApprovalModel
        assert session.get(ActionApprovalModel, "act").status == "COMPLETED"


def test_fresh_database_matches_current_models(migration_engine):
    upgrade_database(migration_engine)
    inspector = sa.inspect(migration_engine)
    for table in Base.metadata.sorted_tables:
        actual = {c["name"] for c in inspector.get_columns(table.name)}
        assert actual == set(table.columns.keys())


def test_incompatible_manual_column_fails_without_version_advance(migration_engine):
    run_to(migration_engine, "0001_legacy_schema")
    with migration_engine.begin() as connection:
        connection.execute(sa.text("ALTER TABLE action_approvals ADD COLUMN mfa_issued_at VARCHAR(10)"))
    with pytest.raises(RuntimeError, match="Incompatible existing"):
        upgrade_database(migration_engine)
    with migration_engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0001_legacy_schema"


def test_startup_failure_does_not_start_server(monkeypatch):
    spec = importlib.util.spec_from_file_location("backend_start", BACKEND_ROOT / "start.py")
    startup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(startup)
    monkeypatch.setattr("sys.argv", ["start.py"])
    def fail():
        raise RuntimeError("migration failed")
    monkeypatch.setattr("app.db.seed.seed_database", fail)
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append(kw))
    with pytest.raises(RuntimeError, match="migration failed"):
        startup.main()
    assert calls == []


def test_previous_head_upgrade_and_restart_preserve_subscription_state(migration_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.db import seed
    from app.db.models import AccountModel, SubscriptionModel, UserModel
    from decimal import Decimal
    run_to(migration_engine, "0002_mfa_lifecycle")
    sessions = sessionmaker(bind=migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users VALUES ('usr_demo_01', 'Alice', false, '2026-10-24')"))
        connection.execute(sa.text("INSERT INTO accounts (account_id, user_id, account_number, currency, balance, daily_transfer_total, created_at) VALUES ('acc_cny_001', 'usr_demo_01', 'preserve', 'CNY', 987.65, 123.00, '2026-10-24')"))
    monkeypatch.setattr(seed, "engine", migration_engine)
    monkeypatch.setattr(seed, "SessionLocal", sessions)
    seed.seed_database()
    with sessions() as db:
        row = db.get(SubscriptionModel, "sub_iQIYI_01")
        assert row.status == "active"
        row.status = "cancelled"
        db.commit()
    seed.seed_database()  # Same path as a backend restart, using new sessions.
    with sessions() as db:
        assert db.get(SubscriptionModel, "sub_iQIYI_01").status == "cancelled"
        account = db.get(AccountModel, "acc_cny_001")
        assert account.balance == Decimal("987.65") and account.daily_transfer_total == Decimal("123.00")


def test_fresh_startup_seeds_owned_subscription_records(migration_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.db import seed
    from app.db.models import SubscriptionModel
    sessions = sessionmaker(bind=migration_engine)
    monkeypatch.setattr(seed, "engine", migration_engine)
    monkeypatch.setattr(seed, "SessionLocal", sessions)
    seed.seed_database()
    with sessions() as db:
        assert db.get(SubscriptionModel, "sub_streambox").account_id == "account_001"
        assert db.get(SubscriptionModel, "sub_cloudmusic").cancellation_supported is False
        assert db.get(SubscriptionModel, "sub_iQIYI_01").account_id == "acc_cny_001"


def test_transfer_day_upgrade_preserves_existing_money(migration_engine):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from sqlalchemy.orm import Session
    from app.db.models import AccountModel
    run_to(migration_engine, "0003_subscriptions")
    with migration_engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users VALUES ('u', 'Old counter', false, '2026-10-24')"))
        connection.execute(sa.text("INSERT INTO accounts VALUES ('a', 'u', 'old', 'CNY', 987.65, 1800.00, '2026-10-24')"))
    upgrade_database(migration_engine)
    upgrade_database(migration_engine)
    with Session(migration_engine) as db:
        row = db.get(AccountModel, "a")
        assert row.balance == Decimal("987.65") and row.daily_transfer_total == Decimal("1800.00")
        assert row.daily_transfer_date == datetime.now(timezone(timedelta(hours=8))).date()
