from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import DATABASE_URL
from app.database import Base
# Every model module must be imported here. A module missing from this list is
# absent from Base.metadata, so autogenerate reads its live tables as deleted
# and writes drop_table into the next revision.
from app.models import entities  # noqa: F401 - core Phase 1 schema
from app.models import intelligence  # noqa: F401 - DOU AI, notifications, analytics
from app.models import salary  # noqa: F401 - salary structures and components
from app.models import merchant  # noqa: F401 - DOU Flex / Merchant Phase 2


config = context.config
url_opt = config.get_main_option("sqlalchemy.url")
if not url_opt or url_opt in ("sqlite:///./dou.db", "driver://"):
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
