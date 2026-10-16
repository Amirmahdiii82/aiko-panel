"""Login, sessions and permissions for the whole app.

* Passwords: scrypt (same format the old ERP used, so migrated users keep their passwords).
* Sessions: random token in an HttpOnly SameSite=Lax cookie; only its SHA-256 is stored.
* CSRF: every state-changing request must carry `X-Aiko: 1`, which a cross-site form cannot send.
* Permissions: `is_admin` users (owners) can open everything. Everyone else gets a role per module
  (`user_modules`), e.g. erp=seller, pricing=viewer. Routes declare what they need:

      User = Depends(auth.require("pricing"))             # any pricing role
      Editor = Depends(auth.require("pricing", "editor"))  # editor or higher

  The dependency returns the user dict with `role` set to the user's role *in that module*,
  so module code can keep checking `user["role"] == "admin"`.
"""
import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from . import config, db
from .modules import loaded as modules

COOKIE = "aiko_session"
_failed: dict[str, list[float]] = {}
_last_touch: dict[str, float] = {}


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, digest = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    test = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=len(digest))
    return hmac.compare_digest(test, digest)


def check_password_strength(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(400, "رمز باید حداقل ۶ حرف باشد")


# ---------------------------------------------------------------- login throttling
def client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")


def check_rate_limit(ip: str) -> None:
    """At most 8 failed logins per IP in 10 minutes."""
    window = time.time() - 600
    attempts = [t for t in _failed.get(ip, []) if t > window]
    _failed[ip] = attempts
    if len(attempts) >= 8:
        raise HTTPException(429, "تلاش زیاد برای ورود. چند دقیقه دیگر دوباره امتحان کنید.")


def record_failure(ip: str) -> None:
    _failed.setdefault(ip, []).append(time.time())


# ---------------------------------------------------------------- sessions
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(db.TZ) + timedelta(days=config.SESSION_DAYS)).replace(microsecond=0).isoformat()
    ip = client_ip(request) if request else None
    ua = (request.headers.get("user-agent") or "")[:200] if request else None
    with db.core.tx() as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
        con.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at, ip, user_agent) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (_hash_token(token), user_id, db.now(), expires, db.now(), ip, ua))
        con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (db.now(), user_id))
    return token


def delete_session(token: str) -> None:
    with db.core.tx() as con:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


def delete_user_sessions(con, user_id: int) -> None:
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    th = _hash_token(token)
    with db.core.read() as con:
        user = db.one(con.execute(
            """SELECT u.id, u.username, u.name, u.is_admin, u.notif_seen
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""", (th, db.now())))
        if not user:
            return None
        grants = {r["module"]: r["role"] for r in con.execute(
            "SELECT module, role FROM user_modules WHERE user_id = ?", (user["id"],))}
    user["is_admin"] = bool(user["is_admin"])
    user["modules"] = module_access(user["is_admin"], grants)
    # remember activity at most every 10 minutes per session (cheap "last seen")
    if time.time() - _last_touch.get(th, 0) > 600:
        _last_touch[th] = time.time()
        with db.core.tx() as con:
            con.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (db.now(), th))
    return user


def module_access(is_admin: bool, grants: dict[str, str]) -> dict[str, str]:
    """{module_id: role} for the modules this user can open (only modules that are switched on)."""
    out = {}
    for mid, mod in modules.items():
        if is_admin:
            out[mid] = mod.top_role
        elif mid in grants and grants[mid] in mod.roles:
            out[mid] = grants[mid]
    return out


# ---------------------------------------------------------------- dependencies
def current_user(request: Request) -> dict:
    user = user_from_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "ابتدا وارد شوید")
    # every state-changing request must come from our own page (CSRF guard on top of SameSite=Lax)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-aiko") != "1":
        raise HTTPException(403, "درخواست نامعتبر")
    return user


def admin_user(request: Request) -> dict:
    user = current_user(request)
    if not user["is_admin"]:
        raise HTTPException(403, "این بخش فقط برای مدیرهای کل است")
    return user


def require(module_id: str, min_role: str | None = None):
    """Dependency factory: the user must have access to `module_id` (and at least `min_role`)."""
    def dep(request: Request) -> dict:
        user = current_user(request)
        role = user["modules"].get(module_id)
        if role is None:
            raise HTTPException(403, "به این بخش دسترسی ندارید")
        mod = modules[module_id]
        if min_role and mod.role_rank(role) > mod.role_rank(min_role):
            raise HTTPException(403, "این کار با سطح دسترسی شما ممکن نیست")
        return {**user, "role": role}
    dep.__name__ = f"require_{module_id}_{min_role or 'any'}"
    return dep


# ---------------------------------------------------------------- first start
def bootstrap() -> list[str]:
    """On an empty core database create the owner accounts from ADMIN_USERS. Returns created usernames."""
    created = []
    with db.core.tx() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return created
        pw = hash_password(config.INITIAL_PASSWORD)
        for item in config.ADMIN_USERS.split(","):
            username, _, name = item.strip().partition(":")
            if not username:
                continue
            con.execute("INSERT INTO users (username, name, password_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
                        (username.strip(), (name or username).strip(), pw, db.now()))
            created.append(username.strip())
    return created
