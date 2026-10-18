"""What a module needs to put buttons in the owners' bot, without knowing anything about Telegram or Bale.

`Module.bot` maps a command name to either
* `Report(label, fn)` — one tap, one message (`fn()` returns the text), or
* a `Flow` — a step-by-step conversation such as "record a sale".

A flow implements `start(user, state)` and `handle(user, state, text=None, data=None)`, both returning a `Reply`.
`state` is a dict the flow keeps its progress in (saved between messages); `data` is the inline button the owner
tapped, `text` what they typed. `user` is the panel owner bound to the chat. Flows are plain synchronous functions
(they may use the module's database); the core bot does all the messaging.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, NamedTuple

from .text import fa, fold, toman  # noqa: F401 — re-exported for flows

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
_THOUSANDS_DOTS = re.compile(r"\d{1,3}(?:\.\d{3})+")       # 540.000 / 1.250.000 written the Iranian way


@dataclass
class Reply:
    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)   # rows of (label, data)
    done: bool = False                                                    # flow finished: back to the main menu


class Report(NamedTuple):
    label: str
    fn: Callable[[], str]


class Flow:
    label = ""

    def start(self, user: dict, state: dict) -> Reply:
        raise NotImplementedError

    def handle(self, user: dict, state: dict, text: str | None = None, data: str | None = None) -> Reply:
        raise NotImplementedError


def parse_amount(text: str) -> int | None:
    """Toman from what people type: '۵۴۰,۰۰۰' / '540.000' / '540000' / '۵۴۰ هزار' / '1.5 میلیون' / '۱٫۲۵ میلیون'.
    Dots in groups of three are thousands separators ONLY without a unit; with هزار/میلیون, or with the Persian
    decimal sign ٫, they are a decimal point (so '1.500 میلیون' is 1.5 million, never 1.5 billion). None if not a number."""
    raw = (text or "").strip()
    persian_decimal = "٫" in raw
    t = raw.translate(_DIGITS).replace("٬", "").replace(",", "").replace("،", "").strip()
    m = re.fullmatch(r"([\d.]+)\s*(هزار تومان|هزارتومان|هزار|k|میلیون|م|m)?\s*(تومان|ت)?", t, re.I)
    if not m:
        return None
    num, unit = m.group(1), (m.group(2) or "").lower()
    if not unit and not persian_decimal and _THOUSANDS_DOTS.fullmatch(num):
        num = num.replace(".", "")
    try:
        n = float(num)
    except ValueError:
        return None
    if unit in ("هزار", "هزارتومان", "هزار تومان", "k"):
        n *= 1000
    elif unit in ("میلیون", "م", "m"):
        n *= 1_000_000
    return int(round(n))


def button_arg(data: str | None, prefix: str) -> str | None:
    """'p:12' with prefix 'p' → '12'; None for any other button (an old message, another step)."""
    if not data or not data.startswith(prefix + ":"):
        return None
    return data[len(prefix) + 1:] or None


def parse_int(text: str) -> int | None:
    t = (text or "").translate(_DIGITS).strip()
    return int(t) if t.isdigit() else None


def norm(text: str) -> str:
    return fold(text).strip()
