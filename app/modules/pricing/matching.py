"""Decides whether a competitor listing is the same product as one of ours.

Score (0..1) = weighted token overlap (rare words weigh more, Persian and English
spellings compared phonetically) x penalties for hard mismatches:
different brand, product type, size, shade code, skin type / texture, variant words (waterproof, mini, set...).
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from . import config
from . import textnorm as tn

# A listing that does not name the brand at all goes to the review queue at most.
MATCH_AUTO_CAP = config.MATCH_AUTO - 0.01

_FA_TO_LAT = {
    "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d",
    "ذ": "s", "ر": "r", "ز": "s", "ژ": "zh", "س": "s", "ش": "sh", "ص": "s", "ض": "s", "ط": "t",
    "ظ": "s", "غ": "g", "ف": "f", "ق": "g", "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n",
    "ع": "", "ء": "", "ا": "", "ه": "h",
}
_EN_RULES = [
    (r"tion", "shn"), (r"sion", "shn"), (r"ph", "f"), (r"ck", "k"), (r"c(?=[eiy])", "s"), (r"c", "k"),
    (r"q", "k"), (r"x", "ks"), (r"w", "v"), (r"th", "t"), (r"gh", "g"), (r"z", "s"),
]

_VARIANT_PATTERNS = {
    "waterproof": re.compile(r"waterproof|واترپروف|ضد\s*اب|water\s*proof"),
    "mini": re.compile(r"\bmini\b|مینی|\btravel\b|سفری"),
    "tester": re.compile(r"tester|تستر"),
    "set": re.compile(r"\bset\b|\bست\b|\bkit\b|کیت|\bپک\b|\bpack\b|باندل|bundle|\bجفتی\b"),
    "refill": re.compile(r"refill|ریفیل|یدک"),
}

# Product type phrases; longer phrases are matched first so "کرم پودر" is not read as "کرم".
_TYPES = {
    "shampoo": ["شامپو", "shampoo"], "conditioner": ["نرم کننده مو", "conditioner", "نرم کننده"],
    "hair_mask": ["ماسک مو", "hair mask"], "mask": ["ماسک", "mask"], "serum": ["سرم", "serum", "امپول"],
    "foundation": ["کرم پودر", "foundation"], "bb": ["بی بی کرم", "bb cream", "کرم پودر bb", "کرم bb"],
    "cc": ["سی سی کرم", "cc cream", "کرم پودر cc", "کرم cc"],
    "cream": ["کرم", "cream"], "lotion": ["لوسیون", "lotion"], "gel": ["ژل", "gel"], "foam": ["فوم", "foam"],
    "toner": ["تونر", "toner"], "micellar": ["میسلار", "micellar", "پاک کننده ارایش"],
    "mascara": ["ریمل", "mascara"], "lipstick": ["رژ لب", "رژلب", "lipstick"],
    "lipgloss": ["لیپ گلاس", "برق لب", "lip gloss", "گلاس"], "lip_liner": ["مداد لب", "خط لب", "lip liner"],
    "eyeliner": ["خط چشم", "eyeliner", "لاینر"], "eye_pencil": ["مداد چشم", "kohl"],
    "brow": ["مداد ابرو", "ژل ابرو", "سایه ابرو", "ریمل ابرو", "brow"],
    "eyeshadow": ["سایه چشم", "پالت سایه", "eyeshadow"], "blush": ["رژ گونه", "رژگونه", "blush"],
    "concealer": ["کانسیلر", "concealer"], "powder": ["پنکک", "پودر فیکس", "powder"],
    "primer": ["پرایمر", "primer"], "highlighter": ["هایلایتر", "highlighter"], "contour": ["کانتور", "contour"],
    "nail": ["لاک ناخن", "لاک", "nail polish"], "perfume": ["عطر", "ادکلن", "ادو پرفیوم", "perfume", "edp", "edt"],
    "deodorant": ["دئودورانت", "مام", "deodorant"], "body_spray": ["اسپری بدن", "بادی اسپلش", "body splash", "body mist"],
    "sunscreen": ["ضد افتاب", "sunscreen", "sunblock"], "oil": ["روغن", "oil"],
    "scrub": ["اسکراب", "لایه بردار", "scrub", "peeling"], "soap": ["صابون", "soap"], "shaver": ["شیور", "ریش تراش"],
    "fixer": ["اسپری فیکس", "فیکساتور", "setting spray"], "remover": ["ریموور", "remover"],
}
_TYPE_PHRASES = sorted(((tn.normalize(ph), t) for t, phs in _TYPES.items() for ph in phs), key=lambda x: -len(x[0]))
# Attribute groups: if both titles name a value from the same group and they differ, it is another SKU.
_ATTR_GROUPS = {
    "skin": {"چرب": "oily", "oily": "oily", "خشک": "dry", "dry": "dry", "حساس": "sensitive", "sensitive": "sensitive",
             "مختلط": "combo", "combination": "combo", "نرمال": "normal", "normal": "normal"},
    "texture": {"مایع": "liquid", "liquid": "liquid", "جامد": "solid", "stick": "solid", "پودری": "powder"},
}


def product_types(norm: str) -> set[str]:
    text, found = f" {norm} ", set()
    for phrase, t in _TYPE_PHRASES:
        if f" {phrase} " in text:
            found.add(t)
            text = text.replace(f" {phrase} ", " | ")
    return found


def _attrs(norm: str) -> dict[str, set[str]]:
    words = set(norm.split())
    return {g: {v for w, v in m.items() if w in words} for g, m in _ATTR_GROUPS.items()}


# Descriptive words that many different products share; they count little either way.
GENERIC = {tn.normalize(w) for w in """
ریمل رژ لب گونه کرم پنکک کانسیلر کانسیلیر پرایمر هایلایتر کانتور سایه چشم خط مداد ابرو لاک ناخن
ضد افتاب سرم تونر ماسک شامپو نرم کننده لوسیون ژل فوم پاک کننده میسلار اسپری بادی عطر ادکلن ادو پرفیوم
حجم دهنده بلند کننده بلندکننده حالت فر حجیم کننده حجم‌دهنده دهنده کننده مرطوب ابرسان آبرسان روشن تیره
مات براق مایع جامد پودری پودر کرمی ژله ای ماندگار ماندگاری بالا قوی طبیعی گیاهی ویتامین
پوست خشک چرب مختلط حساس نرمال معمولی صورت بدن دست مو موها مژه مژه‌ها زنانه مردانه
بی رنگ رنگی مشکی قهوه ای سفید قرمز صورتی نود بژ کالباسی
mascara lipstick lip gloss cream foundation concealer primer highlighter blush powder
eyeliner eyeshadow liner pencil brow serum toner mask shampoo lotion gel spray perfume edp edt
lengthening curling volumizing volume matte liquid long lasting waterproof skin face eye eyes
black brown oily dry sensitive normal all types
hair makeup make up cover full فول کاور
اب ضداب واترپروف waterproof والیوم ولوم اکستریم لیپگلاس لیپتینت لیپبام lipgloss lipliner liptint پاککن کن پاک
رژلب رژگونه ضدافتاب ضدریزش ضدلک ضدچروک ضدتعریق ضدجوش لیفت تثبیت فیکس فیکساتور فشرده استیکی
ایتالیا فرانسه المان ترکیه کره امریکا انگلیس لهستان چین ژاپن اسپانیا ایران سوئیس کانادا
""".split()}


def _dedupe(toks: list[str]) -> list[str]:
    """Drop repeats, including the same word written once in Persian and once in English."""
    out: list[str] = []
    for t in toks:
        if not any(_token_sim(t, o) >= 0.8 for o in out):
            out.append(t)
    return out


def skeleton(word: str) -> str:
    """Consonant skeleton so 'لش سنسیشنال' and 'lash sensational' land close together."""
    if re.search(r"[؀-ۿ]", word):
        out = []
        for i, ch in enumerate(word):
            if ch in ("و", "ی"):
                out.append(("v" if ch == "و" else "y") if i == 0 else "")
            elif ch == "ه" and i == len(word) - 1 and i > 0:
                out.append("")
            else:
                out.append(_FA_TO_LAT.get(ch, ch if ch.isdigit() else ""))
        s = "".join(out)
    else:
        s = word.lower()
        for pat, rep in _EN_RULES:
            s = re.sub(pat, rep, s)
        head, rest = s[:1], s[1:]
        if head == "y":
            head = "y"
        elif head in "aeiou":
            head = ""
        s = head + re.sub(r"[aeiouy]", "", rest)
    return re.sub(r"(.)\1+", r"\1", s)


def _token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a.isdigit() or b.isdigit():
        return 0.0
    r = fuzz.ratio(a, b) / 100
    if r >= 0.86:
        return r
    sa, sb = skeleton(a), skeleton(b)
    if sa and sa == sb:
        return 0.92
    if len(sa) >= 2 and len(sb) >= 2:
        rs = fuzz.ratio(sa, sb) / 100
        if rs >= 0.8:
            return rs * 0.95
    return 0.0


def _variants(norm: str) -> set[str]:
    return {k for k, pat in _VARIANT_PATTERNS.items() if pat.search(norm)}


@dataclass
class Candidate:
    """A competitor listing as returned by a source adapter."""
    site: str
    external_id: str
    title: str
    url: str
    price: int | None                      # Toman, final price the customer pays
    regular_price: int | None = None       # Toman, before discount
    in_stock: bool = True
    seller: str | None = None
    image: str | None = None
    brand: str | None = None
    barcode: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Own:
    id: int
    name: str
    brand: str | None
    sku: str | None = None


class Matcher:
    def __init__(self, catalog_titles: list[str]):
        df = Counter()
        for t in catalog_titles:
            df.update(set(tn.core_tokens(t)))
        self.n = max(len(catalog_titles), 1)
        self.df = df

    def weight(self, tok: str) -> float:
        # numbers and SPF are judged by the shade-code / size rules, not as identity words
        if tok in GENERIC or tok.isdigit() or re.fullmatch(r"spf\d+", tok):
            return 0.25
        return math.log(1 + self.n / (1 + self.df.get(tok, 0))) + 0.5

    def score(self, own: Own, cand: Candidate) -> tuple[float, list[str]]:
        reasons: list[str] = []
        if own.sku and cand.barcode and re.sub(r"\D", "", own.sku) == re.sub(r"\D", "", cand.barcode) \
                and len(re.sub(r"\D", "", own.sku)) >= 8:
            return 1.0, ["بارکد یکسان"]

        brand_forms = tn.brand_forms(own.brand) if own.brand else set()
        own_norm = tn.normalize(own.name)
        cand_text = f"{cand.title} {cand.brand or ''}"
        cand_norm = tn.normalize(cand_text)

        mine = [t for t in tn.core_tokens(own.name)]
        theirs = [t for t in tn.core_tokens(cand_text)]
        # brand words should not dominate the overlap; brand is judged separately below
        brand_words = {w for f in brand_forms for w in f.split()}
        brand_words |= _brandish_words(theirs, brand_forms)
        mine_c = _dedupe([t for t in mine if t not in brand_words] or mine)
        theirs_c = _dedupe([t for t in theirs if t not in brand_words] or theirs)
        if not mine_c or not theirs_c:
            return 0.0, ["عنوان خالی"]

        def coverage(src, dst):
            total = hit = 0.0
            for t in src:
                w = self.weight(t)
                total += w
                hit += w * max((_token_sim(t, d) for d in dst), default=0.0)
            return hit / total if total else 0.0

        cov_mine = coverage(mine_c, theirs_c)
        cov_theirs = coverage(theirs_c, mine_c)
        overall = fuzz.token_set_ratio(" ".join(mine_c), " ".join(theirs_c)) / 100
        score = 0.55 * cov_mine + 0.35 * cov_theirs + 0.10 * overall

        # Model words present on one side only (e.g. "Luscious", "Sky High") usually mean another SKU
        def unmatched(src, dst):
            return [t for t in src if t not in GENERIC and not t.isdigit() and len(t) > 1
                    and not re.fullmatch(r"spf\d+", t)
                    and max((_token_sim(t, d) for d in dst), default=0.0) < 0.8]

        def is_model_word(t, side_tokens):
            # Latin words are usually model names; a Persian word is too when the same title also
            # spells it in Latin ("کریزی ... Crazy"), otherwise it is usually a description
            return bool(re.search(r"[a-z]", t)) or any(
                re.search(r"[a-z]", o) and _token_sim(t, o) >= 0.8 for o in side_tokens)

        extra_theirs, extra_mine = unmatched(theirs_c, mine_c), unmatched(mine_c, theirs_c)
        extra = extra_theirs + extra_mine
        if extra:
            # Our own titles are long (Persian name + full English name + selling points) and shops
            # shorten them, so a word only we have is weaker evidence than a model word only they have;
            # cov_mine already charges for it.
            weight = sum(1.0 if is_model_word(t, theirs) else 0.3 for t in extra_theirs) \
                + sum(0.45 if is_model_word(t, mine) else 0.15 for t in extra_mine)
            score *= 0.84 ** min(weight, 3)
            reasons.append("کلمات متفاوت: " + "، ".join(extra[:4]))

        # Brand
        if brand_forms:
            if any(tn.contains_phrase(cand_norm, f) for f in brand_forms) or \
                    (cand.brand and tn.canonical_brand(cand.brand) == tn.canonical_brand(own.brand)) or \
                    _sounds_like_brand(cand_norm, brand_forms):
                reasons.append("برند یکسان")
            else:
                other = tn.detect_brand(cand_text)
                if other and other != tn.canonical_brand(own.brand):
                    score *= 0.35
                    reasons.append(f"برند متفاوت ({other})")
                else:
                    # could be another brand's product with the same model name: never auto-count it
                    score = min(score * 0.92, MATCH_AUTO_CAP)
                    reasons.append("برند در عنوان رقیب نیامده")

        # Size
        s_own, s_c = tn.sizes(own.name), tn.sizes(cand.title)
        if s_own and s_c:
            # 73 g vs 75 g is the same tube described differently; 30 ml vs 50 ml is not
            if any(u1 == u2 and abs(v1 - v2) <= 0.06 * max(v1, v2) for v1, u1 in s_own for v2, u2 in s_c):
                reasons.append("حجم یکسان")
            else:
                same_unit = {u for _, u in s_own} & {u for _, u in s_c}
                if same_unit:
                    score *= 0.5
                    reasons.append("حجم متفاوت")

        # Shade / model code
        c_own, c_c = tn.codes(own.name), tn.codes(cand.title)
        if c_own:
            if c_c and not (c_own & c_c):
                score *= 0.55
                reasons.append("شماره/کد رنگ متفاوت")
            elif not c_c:
                score *= 0.88
                reasons.append("شماره رنگ در عنوان رقیب نیست")
            else:
                reasons.append("شماره رنگ یکسان")

        # Piece / shade count (8-piece vs 13-piece brush set, 9 vs 12 colour palette)
        n_own, n_c = tn.counts(own.name), tn.counts(cand.title)
        if n_own and n_c and not (n_own & n_c):
            score *= 0.6
            reasons.append("تعداد تکه/رنگ متفاوت")

        # Product type (shampoo vs hair mask, gel vs foam ...)
        t_own, t_c = product_types(own_norm), product_types(cand_norm)
        if t_own and t_c and not (t_own & t_c):
            score *= 0.45
            reasons.append("نوع محصول متفاوت")

        # Skin type / texture
        a_own, a_c = _attrs(own_norm), _attrs(cand_norm)
        for group, label in (("skin", "نوع پوست متفاوت"), ("texture", "بافت متفاوت")):
            if a_own[group] and a_c[group] and not (a_own[group] & a_c[group]):
                score *= 0.65
                reasons.append(label)

        # Variant words (waterproof, mini, tester, set, refill)
        v_own, v_c = _variants(own_norm), _variants(cand_norm)
        diff = v_own ^ v_c
        if diff:
            score *= 0.7 ** len(diff)
            reasons.append("نوع متفاوت: " + "، ".join(sorted(diff)))

        return round(min(score, 1.0), 3), reasons


def type_phrase(text: str) -> str | None:
    """The Persian product-type phrase in a title, e.g. 'رژگونه', 'پالت سایه'."""
    norm = f" {tn.normalize(text)} "
    best = None
    for phrase, _ in _TYPE_PHRASES:
        if re.search(r"[\u0600-\u06FF]", phrase):
            i = norm.find(f" {phrase} ")
            if i >= 0 and (best is None or i < best[0]):
                best = (i, phrase)
    return best[1] if best else None


def _sounds_like_brand(cand_norm: str, brand_forms: set[str]) -> bool:
    """'ایپک' in a Persian title is the brand 'ipek' even if nobody told us the spelling."""
    return bool(_brandish_words(cand_norm.split(), brand_forms))


def _brandish_words(words: list[str], brand_forms: set[str]) -> set[str]:
    """Persian words that are the Latin brand written in Persian letters ('ایپک' = 'ipek')."""
    latin = [f for f in brand_forms if re.fullmatch(r"[a-z0-9 .&]+", f)]
    fa = [w for w in words if re.search(r"[\u0600-\u06FF]", w)]
    found = set()
    for f in latin:
        n = len(f.split())
        target = "".join(skeleton(w) for w in f.split())
        if len(target) < 2:
            continue
        for i in range(len(fa) - n + 1):
            sk = "".join(skeleton(w) for w in fa[i:i + n])
            if (sk == target) if len(target) < 4 else fuzz.ratio(sk, target) >= 88:
                found.update(fa[i:i + n])
    return found


def build_query(name: str, brand: str | None) -> str:
    """Short search query: identity words only (sizes and filler removed), at most 7 words."""
    toks = tn.core_tokens(name)
    # keep brand at the front if not already present
    if brand and not any(tn.contains_phrase(" ".join(toks), f) for f in tn.brand_forms(brand)):
        toks = tn.normalize(brand).split() + toks
    return " ".join(toks[:7])
