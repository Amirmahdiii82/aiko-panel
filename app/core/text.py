"""Persian text and numbers, shared by every module: digits, Toman amounts, and folding the many ways one Persian
word can be typed (Arabic ي/ك, ة, أ/إ, ۀ, zero-width non-joiner, Persian/Arabic digits) into one form for matching."""

_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا", "‌": " ", "‍": "",
    **{d: str(i) for i, d in enumerate("۰۱۲۳۴۵۶۷۸۹")}, **{d: str(i) for i, d in enumerate("٠١٢٣٤٥٦٧٨٩")},
})


def fa(n) -> str:
    """Western digits → Persian digits."""
    return str(n).translate(_TO_FA)


def toman(amount) -> str:
    """1234567 → '۱٬۲۳۴٬۵۶۷ تومان'."""
    return f"{int(round(amount or 0)):,}".replace(",", "٬").translate(_TO_FA) + " تومان"


def fold(text: str | None) -> str:
    """One spelling for matching: Arabic letter forms → Persian, ZWNJ → space, every digit → 0-9, lower case."""
    return (text or "").translate(_FOLD).lower()
