"""Media storage: data/media.db for generation records, data/media/ for the files."""
from pathlib import Path

from ...core import config as core_config
from ...core import db as core_db

database = core_db.Database("media", migrations=Path(__file__).resolve().parent / "migrations")


def files_dir() -> Path:
    return core_config.DATA_DIR / "media"
