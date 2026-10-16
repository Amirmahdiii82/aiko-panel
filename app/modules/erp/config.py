"""ERP settings from the environment. Keys, bot token, default accounts, ... are edited in the app."""
from ...core import config as core

WOO_URL = core.env("WOO_URL", "https://aikocosmetics.ir").rstrip("/")
PUBLIC_URL = core.PUBLIC_URL
TIMEZONE = core.TIMEZONE
