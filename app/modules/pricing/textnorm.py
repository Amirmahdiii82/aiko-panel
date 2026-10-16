"""Persian/English text normalization and feature extraction for product titles."""
import re

_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "ٱ": "ا", "ؤ": "و", "‌": " ", "‍": "", "‏": "", "‎": "", "ـ": "",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_NON_WORD = re.compile(r"[^0-9a-z؀-ۿ.]+")

# Words that carry no identity for matching
STOPWORDS = {
    "اصل", "اصلی", "اورجینال", "original", "orginal", "مدل", "model", "حجم", "وزن", "شماره", "کد",
    "no", "code", "رنگ", "color", "colour", "با", "و", "به", "از", "در", "برای", "the", "of", "for",
    "and", "with", "خرید", "قیمت", "ساخت", "کشور", "new", "جدید", "محصول", "عددی", "عدد", "یک",
    "ای", "های", "ها", "نسخه", "سری", "کالا", "اورجینالی", "ارجینال", "شرکتی", "فروشگاه",
    "ضمانت", "اصالت", "تضمین", "ارسال", "رایگان", "فوری", "تخفیف", "ویژه", "پلمپ", "اورجنال", "اصلی",
}

# Unit words that follow a number to describe size
_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(میلی\s*لیتر|میلی\s*لیتری|میل|میلی|ml|cc|سی\s+سی|گرم|گرمی|gr|g|کیلوگرم|kg|لیتر|l|عددی|عدد|ورق|برگ|اونس|oz|fl\s*oz)\b"
)
_UNIT_CLASS = {
    "میلی لیتر": "ml", "میلی لیتری": "ml", "میل": "ml", "میلی": "ml", "ml": "ml", "cc": "ml", "سی سی": "ml",
    "گرم": "g", "گرمی": "g", "gr": "g", "g": "g", "کیلوگرم": "kg", "kg": "kg", "لیتر": "l", "l": "l",
    "عددی": "pcs", "عدد": "pcs", "ورق": "pcs", "برگ": "pcs", "اونس": "oz", "oz": "oz", "fl oz": "oz",
}

# Common brands on the Iranian cosmetics market: Persian spelling(s) -> canonical English.
BRAND_ALIASES: dict[str, list[str]] = {
    "maybelline": ["میبلین", "میبیلین", "میبلن"], "loreal": ["لورال", "لورآل", "loreal paris", "l'oreal"],
    "essence": ["اسنس"], "catrice": ["کاتریس"], "golden rose": ["گلدن رز", "گلدنرز"],
    "flormar": ["فلورمار"], "pastel": ["پاستل"], "note": ["نوت"], "farmasi": ["فارماسی"],
    "nyx": ["نیکس", "ان وای ایکس"], "mac": ["مک"], "revolution": ["رولوشن", "ریولوشن", "makeup revolution"],
    "bourjois": ["بورژوا"], "rimmel": ["ریمل لندن", "rimmel london"], "max factor": ["مکس فکتور"],
    "dior": ["دیور"], "chanel": ["شنل"], "lancome": ["لانکوم"], "clinique": ["کلینیک"],
    "estee lauder": ["استی لادر", "استی لودر"], "huda beauty": ["هدی بیوتی", "هودا بیوتی"],
    "sheglam": ["شیگلم"], "kiko": ["کیکو", "kiko milano"], "pupa": ["پوپا"], "deborah": ["دبورا"],
    "vivienne sabo": ["ویوین سابو", "ویویان سابو"], "beauty creations": ["بیوتی کریشنز"],
    "too faced": ["توفیسد", "تو فیسد"], "benefit": ["بنفیت"], "nars": ["نارس"], "fenty": ["فنتی", "fenty beauty"],
    "charlotte tilbury": ["شارلوت تیلبری"], "rare beauty": ["رر بیوتی", "رare بیوتی"],
    "elf": ["e.l.f", "e.l.f."], "wet n wild": ["وت اند وایلد", "وت ان وایلد"],
    "inglot": ["اینگلات", "اینگلوت"], "isadora": ["ایزادورا"], "artdeco": ["آرت دکو", "ارت دکو"],
    "callista": ["کالیستا"], "my": ["مای"], "doucce": ["دوسه"], "lamel": ["لامل"], "rozhan": ["روژان"],
    "cinere": ["سینره"], "ariane": ["آریان", "اریان"], "noir": ["نویر"], "kaprin": ["کاپرین"],
    "kapra": ["کاپرا"], "maxxi": ["مکسی"], "cerave": ["سراوی"], "la roche posay": ["لاروش پوزای", "لاروش"],
    "bioderma": ["بایودرما"], "avene": ["اون ه", "آون"], "vichy": ["ویشی"], "eucerin": ["اوسرین"],
    "neutrogena": ["نوتروژینا"], "the ordinary": ["اوردینری", "د اوردینری"], "garnier": ["گارنیر"],
    "nivea": ["نیوآ", "نیوا"], "dove": ["داو"], "schwarzkopf": ["شوارتزکوف"], "pantene": ["پنتن"],
    "head & shoulders": ["هد اند شولدرز"], "sunsafe": ["سان سیف"], "hydroderm": ["هیدرودرم"],
    "fulica": ["فولیکا"], "comeon": ["کامان"], "dermalift": ["درمالیفت"], "seagull": ["سی گل", "سیگل"],
    "nouba": ["نوبا"], "vov": ["ووو"], "missha": ["میشا"], "cosrx": ["کوزارکس", "کوزرکس"],
    "some by mi": ["سام بای می"], "innisfree": ["اینیسفری"], "eveline": ["اولاین", "اولین"],
    "bell": ["بل"], "sleek": ["اسلیک"], "anastasia beverly hills": ["آناستازیا", "anastasia"],
    "dermacol": ["درماکول"], "yves rocher": ["ایوروشه"], "oriflame": ["اوریفلیم"], "avon": ["آوون", "اوون"],
    "lattafa": ["لطافه"], "bioaqua": ["بیوآکوا", "بیواکوا"], "images": ["ایمیجز"], "romantic": ["رومانتیک"],
    "kylie": ["کایلی"], "laura mercier": ["لورا مرسیه"], "urban decay": ["اربن دیکی"], "tarte": ["تارت"],
    "milani": ["میلانی"], "barry m": ["بری ام"], "w7": ["دبلیو سون"], "jute": ["ژوت"],
    "ardene": ["آردن", "اردن"], "geno biotic": ["ژنوبایوتیک"], "alpavit": ["آلپاویت", "الپاویت"],
    "nature's plenty": ["نیچرز پلنتی"], "pixi": ["پیکسی"], "covergirl": ["کاورگرل"], "yadah": ["یاداه"],
    "lovren": ["لورن"], "fix derma": ["فیکس درما"], "beautyfine": ["بیوتی فاین"],
    "gabrini": ["گابرینی"], "artskin": ["آرت اسکین", "آرتسکین", "ارت اسکین"], "anylady": ["انی لیدی", "آنی لیدی"],
    "miss lara": ["میس لارا"], "mehrona": ["مهرونا"], "olibolla": ["اولیبولا"], "drohoo": ["دروهو"],
    "rhode": ["روود", "رود بیوتی"], "borjouise": ["بورژویس"], "warda beauty": ["واردا بیوتی", "واردا"],
    "barin": ["بارین"], "umbrella": ["آمبرلا", "امبرلا"], "lightness": ["لایتنس"], "ipek": ["ایپک"],
    "tigi": ["تی جی"],
}


def normalize(text: str | None) -> str:
    if not text:
        return ""
    t = text.translate(_CHAR_MAP)
    t = _DIACRITICS.sub("", t).lower()
    t = t.replace("'", "").replace("’", "").replace("&", " & ")
    # split latin/persian glued together and digits glued to letters (e.g. 50ml -> 50 ml)
    t = re.sub(r"(?<=[a-z])(?=[؀-ۿ])|(?<=[؀-ۿ])(?=[a-z])", " ", t)
    t = re.sub(r"(?<=\d)(?=[؀-ۿ])|(?<=[؀-ۿ])(?=\d)", " ", t)
    t = re.sub(r"(?<=\d)(?=(ml|g|gr|cc|kg|oz)\b)", " ", t)
    t = _NON_WORD.sub(" ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"\bspf\s*(\d+)", r"spf\1", t)
    # same word written joined or apart: "رژ گونه" / "رژگونه", "ضد آب" / "ضدآب"
    t = re.sub(r"(?<![\u0600-\u06FF])رژ\s+(گونه|لب)(?![\u0600-\u06FF])", r"رژ\1", t)
    t = re.sub(r"(?<![\u0600-\u06FF])ضد\s+(?=[\u0600-\u06FF])", "ضد", t)
    t = re.sub(r"\blip\s+(gloss|liner|tint|stick)\b", r"lip\1", t)
    t = re.sub(r"(?<![\u0600-\u06FF])لیپ\s+(گلاس|تینت|لاینر|بام)(?![\u0600-\u06FF])", r"لیپ\1", t)
    t = re.sub(r"(?<![\u0600-\u06FF])پاک\s+کن(?![\u0600-\u06FF])", "پاککن", t)
    # "بی بی کرم" = "BB cream", "سی سی کرم" = "CC cream" (also "50 سی سی" = "50 cc", still a size)
    t = re.sub(r"(?<![\u0600-\u06FF])بی\s+بی(?![\u0600-\u06FF])", "bb", t)
    t = re.sub(r"(?<![\u0600-\u06FF])سی\s+سی(?![\u0600-\u06FF])", "cc", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list[str]:
    return [w for w in normalize(text).split() if w and w not in STOPWORDS]


def core_tokens(text: str) -> list[str]:
    """Identity words only: no sizes, no units, no stopwords."""
    t = _SIZE_RE.sub(" ", normalize(text))
    return [w for w in t.split() if w and w not in STOPWORDS and w not in _UNIT_CLASS]


def sizes(text: str) -> set[tuple[float, str]]:
    """Return {(value, unit_class)} e.g. {(50.0, 'ml')}."""
    t = normalize(text)
    out = set()
    for num, unit in _SIZE_RE.findall(t):
        unit = re.sub(r"\s+", " ", unit)
        cls = _UNIT_CLASS.get(unit)
        if cls:
            out.add((float(num), cls))
    return out


# "12 رنگ", "8 تکه", "12 colors": how many pieces/shades a palette or set has, not a shade code
_COUNT_RE = re.compile(r"\b(\d+)\s*(رنگ|رنگی|تکه|تیکه|تایی|پارچه|colou?rs?|pcs|pieces?|shades?)\b")


def counts(text: str) -> set[int]:
    """Piece / shade counts: '12 رنگ' -> {12}, '8 تکه' -> {8}."""
    return {int(n) for n, _ in _COUNT_RE.findall(normalize(text))}


def codes(text: str) -> set[str]:
    """Shade / model codes: tokens containing digits that are not sizes (e.g. 102, n12, 26u501)."""
    t = _COUNT_RE.sub(" ", _SIZE_RE.sub(" ", normalize(text)))
    t = re.sub(r"\bspf\d+\b", " ", t)  # sun protection factor, not a shade
    found = set()
    for w in t.split():
        if any(ch.isdigit() for ch in w) and w not in STOPWORDS:
            w = w.lstrip("0") or "0"
            if re.fullmatch(r"\d{5,}", w):  # long pure numbers are barcodes/ids, not shades
                continue
            if re.fullmatch(r"(spf)?\d+", w) and len(w) <= 1:
                continue
            found.add(w)
    return found


_ALIAS_INDEX: list[tuple[str, str]] = []  # (normalized alias, canonical)


def _build_alias_index():
    for canon, aliases in BRAND_ALIASES.items():
        for a in [canon, *aliases]:
            _ALIAS_INDEX.append((normalize(a), canon))
    _ALIAS_INDEX.sort(key=lambda x: -len(x[0]))


_build_alias_index()


def learn_brand(brand: str, alias: str) -> None:
    """Teach the alias table a spelling found in your own titles, e.g. "دروهو (Drohoo)"."""
    canon = canonical_brand(brand) or normalize(brand)
    alias_n = normalize(alias)
    if not canon or not alias_n or alias_n == canon:
        return
    known = BRAND_ALIASES.setdefault(canon, [])
    if alias_n not in (normalize(a) for a in known):
        known.append(alias)
        _ALIAS_INDEX.append((alias_n, canon))
        if normalize(canon) not in (a for a, _ in _ALIAS_INDEX):
            _ALIAS_INDEX.append((normalize(canon), canon))
        _ALIAS_INDEX.sort(key=lambda x: -len(x[0]))


def persian_brand_in_title(title: str, brand: str | None) -> str | None:
    """'ژل ابرو شیگلم (SHEGLAM) مدل ...' -> 'شیگلم' (as many words as the Latin brand has)."""
    if not brand or not re.search(r"[A-Za-z]", brand):
        return None
    n_words = len(brand.split())
    m = re.search(r"([^()]+?)\s*\(\s*" + re.escape(brand.strip()) + r"[^)]*\)", title, re.I)
    if not m:
        return None
    words = [w for w in m.group(1).split() if re.search(r"[\u0600-\u06FF]", w)]
    return " ".join(words[-n_words:]) if words else None


def canonical_brand(name: str | None) -> str | None:
    """Map a brand label (Persian or English) to the canonical key, if known."""
    n = normalize(name)
    if not n:
        return None
    for alias, canon in _ALIAS_INDEX:
        if n == alias:
            return canon
    return n


def brand_forms(brand: str | None) -> set[str]:
    """All normalized spellings we know for a brand."""
    if not brand:
        return set()
    canon = canonical_brand(brand)
    forms = {normalize(brand)}
    if canon in BRAND_ALIASES:
        forms |= {normalize(canon), *(normalize(a) for a in BRAND_ALIASES[canon])}
    elif canon:
        forms.add(canon)
    return {f for f in forms if f}


def contains_phrase(haystack_norm: str, phrase_norm: str) -> bool:
    return f" {phrase_norm} " in f" {haystack_norm} "


def detect_brand(title: str) -> str | None:
    """Best-effort brand detection from a title using the alias table (longest alias wins)."""
    n = normalize(title)
    for alias, canon in _ALIAS_INDEX:
        if len(alias) >= 3 and contains_phrase(n, alias):
            return canon
    return None


def parse_price(text) -> int | None:
    """'۱٫۲۵۰٫۰۰۰ تومان' -> 1250000"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    digits = re.sub(r"[^\d]", "", str(text).translate(_CHAR_MAP))
    return int(digits) if digits else None
