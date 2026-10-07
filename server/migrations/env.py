from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# context is Alembic's runtime. config is the parsed alembic.ini
config = context.config

# applies the [loggers] section of alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.config import settings
from app.db.base import Base
from app.db import models

config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

# Run by Alembic directly
if context.is_offline_mode():
    run_migrations_offline()

else:
    run_migrations_online()