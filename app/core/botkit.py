"""What a module needs to offer a step-by-step flow in the owners' bot (e.g. "record a sale"), without knowing
anything about Telegram or Bale.

A flow is an object with `label` (its keyboard button), `start(user, state)` and
`handle(user, state, text=None, data=None)`; both return a `Reply`. `state` is a dict the flow keeps its progress in
(saved between messages). `data` is the value of an inline button the owner tapped, `text` what they typed.
Flows are plain synchronous functions (they may use the module's database); the core bot does all the messaging.
"""
import re
from dataclasses import dataclass, field

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AR = str.maketrans({"ي": "ی", "ك": "ک", "‌": " "})


@dataclass
class Reply:
    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)   # rows of (label, data)
    done: bool = False                                                    # flow finished: back to the main menu


def parse_amount(text: str) -> int | None:
    """'۵۴۰,۰۰۰' / '540000' / '۵۴۰ هزار' / '1.5 میلیون' → Toman. None when it is not a number."""
    t = (text or "").translate(_DIGITS).replace("٬", "").replace(",", "").replace("،", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(هزار|هزارتومان|هزار تومان|k|میلیون|م|m)?\s*(تومان|ت)?", t, re.I)
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("هزار", "هزارتومان", "هزار تومان", "k"):
        n *= 1000
    elif unit in ("میلیون", "م", "m"):
        n *= 1_000_000
    return int(round(n))


def parse_int(text: str) -> int | None:
    t = (text or "").translate(_DIGITS).strip()
    return int(t) if t.isdigit() else None


def norm(text: str) -> str:
    return (text or "").translate(_AR).translate(_DIGITS).strip().lower()


def fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def toman(n) -> str:
    return f"{int(round(n or 0)):,}".replace(",", "٬").translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) + " تومان"
