"""Price checker settings from the environment (same variable names as the standalone app, so its .env carries over)."""
from ...core import config as core

env, env_int = core.env, core.env_int

# Your own WooCommerce store (read through the public Store API — no key needed)
OWN_SITE_URL = env("OWN_SITE_URL", "https://aikocosmetics.ir").rstrip("/")
OWN_SITE_NAME = env("OWN_SITE_NAME", "آیکو کازمتیکس")
# Limit how many own products are processed (0 = all). Handy for a first test run.
PRODUCT_LIMIT = env_int("PRODUCT_LIMIT", 0)

# Automatic crawl schedule, Tehran time, comma separated HH:MM (empty = manual only)
CRAWL_TIMES = [t.strip() for t in env("CRAWL_TIMES", "").split(",") if t.strip()]
TIMEZONE = core.TIMEZONE
RUN_ON_STARTUP = core.env_bool("RUN_ON_STARTUP", False)

# Matching thresholds (0..1). >= AUTO is counted automatically, >= REVIEW goes to the review queue.
MATCH_AUTO = float(env("MATCH_AUTO", "0.80"))
MATCH_REVIEW = float(env("MATCH_REVIEW", "0.55"))

# Politeness: per-site concurrent requests and delay between requests (seconds)
SITE_CONCURRENCY = env_int("SITE_CONCURRENCY", 2)
REQUEST_DELAY = float(env("REQUEST_DELAY", "1.2"))
REQUEST_TIMEOUT = float(env("REQUEST_TIMEOUT", "40"))
HTTP_PROXY = env("HTTP_PROXY_URL", "") or None
# Read every shop's price on Torob product pages (more requests -> more captchas)
TOROB_SELLERS = core.env_bool("TOROB_SELLERS", False)

USER_AGENT = env(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
)
