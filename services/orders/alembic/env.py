"""
Alembic Environment Configuration for Orders Service

Handles both online (connected) and offline (SQL generation) migrations.
Supports schema-based multi-tenancy.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# Import models to ensure they're registered with Base.metadata
from database import Base
from models import Order, OrderItem, SCHEMA_NAME
from outbox import OutboxEvent

# Alembic Config object
config = context.config

# Setup logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate
target_metadata = Base.metadata

# Schema name for this service
SCHEMA = SCHEMA_NAME


def get_url() -> str:
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable not set")
    return url


def include_object(object, name, type_, reflected, compare_to):
    """
    Filter objects to only include those in our schema.
    This prevents Alembic from trying to manage tables from other services.
    """
    if type_ == "table":
        return object.schema == SCHEMA
    return True


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    Generates SQL scripts without connecting to the database.
    Useful for reviewing migrations before applying.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        version_table_schema=SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    Connects to the database and applies migrations directly.
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Ensure schema exists
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema=SCHEMA,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
