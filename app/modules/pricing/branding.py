"""Picks up your store's name, logo and main color so the dashboard looks like your site."""
import re

from bs4 import BeautifulSoup

from . import config, db
from .sources.woocommerce import WooCommerceSource

# CSS variables that popular WordPress themes use for the brand color
_COLOR_VARS = [
    "--wd-primary-color", "--e-global-color-primary", "--wp--preset--color--primary", "--theme-color",
    "--primary-color", "--color-primary", "--porto-primary-color", "--fl-primary-color", "--accent-color",
    "--xts-primary-color", "--main-color",
]
_HEX = r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b"


def _expand(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h.lower()


def _usable(hex_color: str) -> bool:
    """Skip near-white / near-black / grey values that are not a brand accent."""
    h = _expand(hex_color).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) > 40 and 40 < (r + g + b) / 3 < 235


async def refresh_branding() -> dict:
    current = db.get_setting("branding", {}) or {}
    async with WooCommerceSource("own", config.OWN_SITE_NAME, config.OWN_SITE_URL) as site:
        info = await site.get(config.OWN_SITE_URL + "/wp-json/", expect_json=True, retries=1) or {}
        home = await site.get(config.OWN_SITE_URL + "/", retries=1) or ""
    branding = dict(current)
    if info.get("name"):
        branding["name"] = info["name"]
    if info.get("site_icon_url"):
        branding["icon"] = info["site_icon_url"]
    if home:
        soup = BeautifulSoup(home, "lxml")
        logo = soup.select_one("img.custom-logo, .site-logo img, .wd-logo img, header .logo img, a.logo img")
        if logo and (logo.get("src") or logo.get("data-src")):
            branding["logo"] = logo.get("src") or logo.get("data-src")
        meta = soup.select_one('meta[name="theme-color"]')
        color = meta.get("content") if meta and meta.get("content") and _usable(meta.get("content")) else None
        if not color:
            for var in _COLOR_VARS:
                m = re.search(re.escape(var) + r"\s*:\s*(" + _HEX + ")", home)
                if m and _usable(m.group(1)):
                    color = m.group(1)
                    break
        if color:
            branding["accent"] = _expand(color)
    db.set_setting("branding", branding)
    return branding
