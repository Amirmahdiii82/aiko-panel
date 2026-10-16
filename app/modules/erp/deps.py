"""Who is calling an ERP endpoint: the core user plus their ERP role and staff profile."""
from fastapi import Depends, Request

from ...core import auth
from . import db

_require_any = auth.require("erp")
_require_admin = auth.require("erp", "admin")


def _with_profile(user: dict) -> dict:
    with db.read() as con:
        row = db.one(con.execute("SELECT partner_id, account_id, commission_pct FROM staff WHERE user_id = ?",
                                 (user["id"],))) or {}
    return {**user, "partner_id": row.get("partner_id"), "account_id": row.get("account_id"),
            "commission_pct": row.get("commission_pct") or 0}


def erp_user(request: Request) -> dict:
    return _with_profile(_require_any(request))


def erp_admin(request: Request) -> dict:
    return _with_profile(_require_admin(request))


User = Depends(erp_user)
Admin = Depends(erp_admin)
