import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_URL = os.environ.get("FINN_DB_URL", f"sqlite:///{DATA_DIR / 'finn.db'}")

engine = create_engine(DB_URL, future=True)
Session = sessionmaker(engine, expire_on_commit=False)


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
