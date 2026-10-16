"""Registry of competitor sites. To add a WooCommerce competitor, add one line to COMPETITORS."""
from .base import SiteBlocked, Source
from .digikala import DigikalaSource
from .others import BasalamSource, ElanzaSource, KhanoumiSource, RojashopSource
from .torob import TorobSource
from .woocommerce import WooCommerceSource

COMPETITORS = [
    # key, display name, factory
    ("khanoumi", "خانومی", KhanoumiSource),
    ("digikala", "دیجی‌کالا", DigikalaSource),
    ("torob", "ترب", TorobSource),
    ("basalam", "باسلام", BasalamSource),
    ("rojashop", "رژا", RojashopSource),
    ("elanza", "النزا", ElanzaSource),
    ("pinkcosmetic", "پینک", lambda: WooCommerceSource("pinkcosmetic", "پینک", "https://pinkcosmetic.ir")),
    ("sheen", "شین", lambda: WooCommerceSource("sheen", "شین", "https://sheenbeautyhouse.ir")),
    ("belaran", "بلاران", lambda: WooCommerceSource("belaran", "بلاران", "https://belaranlux.com")),
    ("bellaa", "بلا", lambda: WooCommerceSource("bellaa", "بلا", "https://bellaa.ir")),
]

HOMEPAGES = {
    "khanoumi": "https://www.khanoumi.com", "digikala": "https://www.digikala.com", "torob": "https://torob.com",
    "basalam": "https://basalam.com", "rojashop": "https://rojashop.com", "elanza": "https://elanza.com",
    "pinkcosmetic": "https://pinkcosmetic.ir", "sheen": "https://sheenbeautyhouse.ir",
    "belaran": "https://belaranlux.com", "bellaa": "https://bellaa.ir",
}
MARKETPLACES = {"digikala", "torob", "basalam"}
SITE_NAMES = {k: n for k, n, _ in COMPETITORS}


def make(key: str) -> Source:
    for k, _, factory in COMPETITORS:
        if k == key:
            return factory()
    raise KeyError(key)


__all__ = ["COMPETITORS", "HOMEPAGES", "MARKETPLACES", "SITE_NAMES", "SiteBlocked", "Source", "make", "WooCommerceSource"]
