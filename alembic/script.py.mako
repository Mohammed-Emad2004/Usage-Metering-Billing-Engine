import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from alembic import command
from alembic.config import Config

def run_migration():
    alembic_cfg = Config("alembic.ini")
    command.revision(alembic_cfg, autogenerate=True, message="Initial migration with tenants, plans, subscriptions, and usage_events")

if __name__ == "__main__":
    run_migration()
