import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/frager",
)

# pool_pre_ping makes the pool check a connection before it hands it out.
# Without it the first request after a quiet period finds a connection that
# Neon (or the proxy in front of it) closed while it sat idle, and the request
# dies with a 500 instead of the page. pool_recycle replaces connections
# before they get that old. Both were added after a production probe caught
# the 500.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass
