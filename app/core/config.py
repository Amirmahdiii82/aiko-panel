"""Process-wide settings, read once from the environment (and `.env` next to the app).

Only infrastructure lives here: paths, ports, cookies, which modules are switched on.
Anything an owner changes while the app runs (WooCommerce keys, bot token, OpenRouter key, ...)
is stored in the database and edited from the UI. Module-specific environment variables are read
by each module's own `config.py`.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = Path(os.getenv("AIKO_ENV_FILE", BASE_DIR / ".env"))
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    raw = env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a whole number (got {raw!r})")


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


APP_NAME = env("APP_NAME", "پنل آیکو")


def _deployed_version() -> str:
    """deploy.sh writes "<commit> <date>" to .deployed after each successful release."""
    f = BASE_DIR / ".deployed"
    try:
        return f.read_text(encoding="utf-8").split()[0][:12]
    except (OSError, IndexError):
        return ""


VERSION = env("APP_VERSION", "") or _deployed_version()   # empty in development: asset hashes are used instead

DATA_DIR = Path(env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOAD_DIR = Path(env("UPLOAD_DIR", str(DATA_DIR / "uploads"))).resolve()
BACKUP_DIR = Path(env("BACKUP_DIR", str(DATA_DIR / "backups"))).resolve()
BACKUP_KEEP_DAYS = env_int("BACKUP_KEEP_DAYS", 30)
BACKUP_TIME = env("BACKUP_TIME", "03:15")  # daily, Tehran time; empty = off

# Comma separated module ids in sidebar order. A module that is not listed is not imported at all.
MODULES = [m.strip() for m in env("MODULES", "erp,pricing,media").split(",") if m.strip()]

TIMEZONE = env("TIMEZONE", "Asia/Tehran")
HOST = env("HOST", "127.0.0.1")
PORT = env_int("PORT", 8000)
LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()

# Public address (https://panel.example.ir). Used for webhook URLs shown in the UI.
PUBLIC_URL = env("PUBLIC_URL", "").rstrip("/")
# Set when served over HTTPS so the session cookie is marked Secure.
COOKIE_SECURE = env_bool("COOKIE_SECURE", False)
SESSION_DAYS = env_int("SESSION_DAYS", 30)
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 12)

# First start on an empty database: these owners are created with full access.
# Format "username:Display name,username:Display name". Each should change the password after logging in.
ADMIN_USERS = env("ADMIN_USERS", "amir:امیر,tina:تینا")
INITIAL_PASSWORD = env("INITIAL_PASSWORD", "aiko1405")
