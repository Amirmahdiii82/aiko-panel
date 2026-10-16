"""Every test gets an empty data directory and a running app (all modules) with the two owner accounts."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AIKO_ENV_FILE", "/nonexistent")       # never read a developer's .env in tests
os.environ["BACKUP_TIME"] = ""
os.environ["CRAWL_TIMES"] = ""
os.environ["INITIAL_PASSWORD"] = "owner-pass"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth, config  # noqa: E402

H = {"x-aiko": "1"}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "BACKUP_TIME", "")
    auth._failed.clear()
    auth._last_touch.clear()
    return tmp_path


@pytest.fixture
def app(data_dir):
    from app.main import create_app
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(c, username="amir", password="owner-pass"):
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def owner(client):
    return login(client)


def make_user(c, username, grants, password="secret1", **extra):
    r = c.post("/api/team", json={"username": username, "name": username.title(), "password": password, "grants": grants, **extra},
               headers=H)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def as_user(c, username, password="secret1"):
    c.post("/api/logout", headers=H)
    c.cookies.clear()
    return login(c, username, password)
