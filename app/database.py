from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# For SQLite testing during local test suite, we handle check_same_thread
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def upgrade_db_schema():
    """
    Inspects the database schema and performs simple migrations 
    to add missing columns on the customer model if they do not exist.
    """
    inspector = inspect(engine)
    if "customers" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("customers")]
        new_cols = {
            "notifications_enabled": "BOOLEAN DEFAULT FALSE",
            "ticket_active": "BOOLEAN DEFAULT FALSE",
            "ticket_number": "VARCHAR",
            "last_ticket_activity": "TIMESTAMP",
            "bot_paused_until": "TIMESTAMP"
        }
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in columns:
                    try:
                        conn.execute(text(f"ALTER TABLE customers ADD COLUMN {col_name} {col_type}"))
                        import logging
                        logging.getLogger("app.database").info(f"Self-healed DB: added column {col_name} to customers table.")
                    except Exception as e:
                        import logging
                        logging.getLogger("app.database").error(f"Failed to add column {col_name}: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

