"""Validation of generation requests before anything is sent to OpenRouter (and money is spent).

Ported from the standalone Node server: only allow-listed fields, shapes checked rather than frozen
value lists (the UI only offers values the live capability endpoints advertise), HTTPS-only asset URLs.
"""
import math
import re
from urllib.parse import urlparse


class ValidationError(ValueError):
    pass


ALLOWED_VIDEO_FIELDS = {"model", "prompt", "aspect_ratio", "duration", "resolution", "size", "generate_audio", "seed",
                        "frame_images", "input_references", "provider"}
ALLOWED_IMAGE_FIELDS = {"model", "prompt", "n", "aspect_ratio", "resolution", "size", "quality", "output_format",
                        "background", "output_compression", "seed", "input_references", "provider"}
MAX_IMAGES_PER_REQUEST = 10

ASPECT_RATIO = re.compile(r"^\d{1,3}(?:\.\d{1,2})?:\d{1,3}(?:\.\d{1,2})?$")
VIDEO_RESOLUTION = re.compile(r"^(?:\d{3,4}p|\d{1,2}K)$")
IMAGE_RESOLUTION = re.compile(r"^(?:\d{3,4}p?|\d{1,2}K)$")
SIZE = re.compile(r"^\d{2,5}x\d{2,5}$")
IMAGE_QUALITIES = {"auto", "low", "medium", "high"}
IMAGE_BACKGROUNDS = {"auto", "transparent", "opaque"}
IMAGE_OUTPUT_FORMATS = {"png", "jpeg", "webp", "svg"}
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
FORBIDDEN_KEYS = {"__proto__", "prototype", "constructor"}


def _fail(message: str):
    raise ValidationError(message)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_aspect_ratio(value) -> bool:
    if not isinstance(value, str) or not ASPECT_RATIO.match(value):
        return False
    w, h = (float(x) for x in value.split(":"))
    return w > 0 and h > 0


def _pixel_size(value: str, field: str) -> None:
    w, h = (int(x) for x in value.split("x"))
    if not (64 <= w <= 8192 and 64 <= h <= 8192):
        _fail(f"{field}: ابعاد باید بین ۶۴ تا ۸۱۹۲ پیکسل باشد.")


def _required_string(body: dict, field: str, max_len: int) -> str:
    value = body.get(field)
    if not isinstance(value, str):
        _fail(f"{field} باید متن باشد.")
    if not value.strip():
        _fail(f"{field} نباید خالی باشد." if field != "prompt" else "متن درخواست (پرامپت) را بنویسید.")
    if len(value) > max_len:
        _fail(f"{field} خیلی طولانی است.")
    if "\x00" in value:
        _fail(f"{field} کاراکتر نامعتبر دارد.")
    return value


def https_url(value, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        _fail(f"{field} باید یک آدرس HTTPS معتبر باشد.")
    try:
        parsed = urlparse(value)
    except ValueError:
        _fail(f"{field} باید یک آدرس HTTPS معتبر باشد.")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        _fail(f"{field} باید آدرس HTTPS عمومی و بدون نام کاربری/رمز باشد.")
    return value


def _exact_keys(value: dict, allowed: set, field: str) -> None:
    for key in value:
        if key not in allowed:
            _fail(f"{field} فیلد پشتیبانی‌نشده دارد: {key}")


def _asset(value, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{path} باید شیء باشد.")
    _exact_keys(value, {"url"}, path)
    if "url" not in value:
        _fail(f"{path}.url لازم است.")
    return {"url": https_url(value["url"], f"{path}.url")}


def frame_images(value) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        _fail("frame_images باید یک یا دو تصویر فریم داشته باشد.")
    used, out = set(), []
    for i, item in enumerate(value):
        path = f"frame_images[{i}]"
        if not isinstance(item, dict):
            _fail(f"{path} باید شیء باشد.")
        _exact_keys(item, {"type", "image_url", "frame_type"}, path)
        if item.get("type") != "image_url":
            _fail(f"{path}.type باید image_url باشد.")
        if item.get("frame_type") not in ("first_frame", "last_frame"):
            _fail(f"{path}.frame_type باید first_frame یا last_frame باشد.")
        if item["frame_type"] in used:
            _fail(f"frame_images دو بار {item['frame_type']} دارد.")
        used.add(item["frame_type"])
        out.append({"type": "image_url", "image_url": _asset(item.get("image_url"), f"{path}.image_url"),
                    "frame_type": item["frame_type"]})
    return out


def input_references(value, *, images_only: bool = False) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        _fail("input_references باید بین ۱ تا ۱۶ مرجع داشته باشد.")
    allowed = {"image_url"} if images_only else {"image_url", "audio_url", "video_url"}
    out = []
    for i, item in enumerate(value):
        path = f"input_references[{i}]"
        if not isinstance(item, dict):
            _fail(f"{path} باید شیء باشد.")
        kind = item.get("type")
        if kind not in allowed:
            _fail(f"{path}.type باید یکی از {', '.join(sorted(allowed))} باشد.")
        _exact_keys(item, {"type", kind}, path)
        if kind not in item:
            _fail(f"{path}.{kind} لازم است.")
        out.append({"type": kind, kind: _asset(item[kind], f"{path}.{kind}")})
    return out


def _provider_value(value, state: dict, depth: int = 0, path: str = "provider"):
    if depth > 8:
        _fail(f"{path} بیش از حد تودرتو است.")
    state["n"] += 1
    if state["n"] > 500:
        _fail("provider مقدارهای زیادی دارد.")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            _fail(f"{path} عدد نامعتبر دارد.")
        return value
    if isinstance(value, str):
        if len(value) > 10_000 or "\x00" in value:
            _fail(f"{path} متن نامعتبر دارد.")
        return value
    if isinstance(value, list):
        if len(value) > 100:
            _fail(f"{path} آرایه خیلی بزرگ دارد.")
        return [_provider_value(v, state, depth + 1, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        if len(value) > 100:
            _fail(f"{path} فیلدهای زیادی دارد.")
        out = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k or len(k) > 100 or k in FORBIDDEN_KEYS:
                _fail(f"{path} نام فیلد نامعتبر دارد.")
            out[k] = _provider_value(v, state, depth + 1, f"{path}.{k}")
        return out
    _fail(f"{path} مقدار پشتیبانی‌نشده دارد.")


def _common(body: dict, allowed: set, output: dict) -> None:
    for key in body:
        if key not in allowed:
            _fail(f"فیلد پشتیبانی‌نشده: {key}")
    model = _required_string(body, "model", 200)
    if not MODEL_ID.match(model):
        _fail("شناسه مدل معتبر نیست.")
    output["model"] = model
    output["prompt"] = _required_string(body, "prompt", 50_000)


def _seed(body: dict, output: dict) -> None:
    if "seed" not in body:
        return
    if not _is_int(body["seed"]) or not -2_147_483_648 <= body["seed"] <= 4_294_967_295:
        _fail("seed باید یک عدد صحیح ۳۲ بیتی باشد.")
    output["seed"] = body["seed"]


def _provider(body: dict, output: dict) -> None:
    if "provider" not in body:
        return
    if not isinstance(body["provider"], dict):
        _fail("provider باید شیء JSON باشد.")
    output["provider"] = _provider_value(body["provider"], {"n": 0})


def video_payload(body: dict) -> dict:
    if not isinstance(body, dict):
        _fail("درخواست نامعتبر است.")
    out: dict = {}
    _common(body, ALLOWED_VIDEO_FIELDS, out)
    if "aspect_ratio" in body:
        if not is_aspect_ratio(body["aspect_ratio"]):
            _fail("نسبت تصویر باید به شکل عرض:ارتفاع باشد.")
        out["aspect_ratio"] = body["aspect_ratio"]
    if "duration" in body:
        if not _is_int(body["duration"]) or not 1 <= body["duration"] <= 300:
            _fail("مدت ویدیو باید بین ۱ تا ۳۰۰ ثانیه باشد.")
        out["duration"] = body["duration"]
    if "resolution" in body:
        if not isinstance(body["resolution"], str) or not VIDEO_RESOLUTION.match(body["resolution"]):
            _fail("کیفیت (resolution) پشتیبانی نمی‌شود.")
        out["resolution"] = body["resolution"]
    if "size" in body:
        if not isinstance(body["size"], str) or not SIZE.match(body["size"]):
            _fail("اندازه باید به شکل عرضxارتفاع پیکسل باشد.")
        _pixel_size(body["size"], "size")
        if "resolution" in body or "aspect_ratio" in body:
            _fail("اندازه دقیق را نمی‌شود با کیفیت یا نسبت تصویر ترکیب کرد.")
        out["size"] = body["size"]
    if "generate_audio" in body:
        if not isinstance(body["generate_audio"], bool):
            _fail("generate_audio باید بله/خیر باشد.")
        out["generate_audio"] = body["generate_audio"]
    _seed(body, out)
    if "frame_images" in body:
        out["frame_images"] = frame_images(body["frame_images"])
    if "input_references" in body:
        out["input_references"] = input_references(body["input_references"])
    _provider(body, out)
    return out


def image_payload(body: dict) -> dict:
    if not isinstance(body, dict):
        _fail("درخواست نامعتبر است.")
    out: dict = {}
    _common(body, ALLOWED_IMAGE_FIELDS, out)
    if "n" in body:
        if not _is_int(body["n"]) or not 1 <= body["n"] <= MAX_IMAGES_PER_REQUEST:
            _fail(f"تعداد تصویر باید بین ۱ تا {MAX_IMAGES_PER_REQUEST} باشد.")
        out["n"] = body["n"]
    if "aspect_ratio" in body:
        if body["aspect_ratio"] != "auto" and not is_aspect_ratio(body["aspect_ratio"]):
            _fail("نسبت تصویر باید auto یا عرض:ارتفاع باشد.")
        out["aspect_ratio"] = body["aspect_ratio"]
    if "resolution" in body:
        if not isinstance(body["resolution"], str) or not IMAGE_RESOLUTION.match(body["resolution"]):
            _fail("کیفیت (resolution) پشتیبانی نمی‌شود.")
        out["resolution"] = body["resolution"]
    if "size" in body:
        if not isinstance(body["size"], str):
            _fail("size باید متن باشد.")
        if SIZE.match(body["size"]):
            _pixel_size(body["size"], "size")
        elif not IMAGE_RESOLUTION.match(body["size"]):
            _fail("size باید سطح کیفیت یا عرضxارتفاع پیکسل باشد.")
        if "resolution" in body or "aspect_ratio" in body:
            _fail("اندازه دقیق را نمی‌شود با کیفیت یا نسبت تصویر ترکیب کرد.")
        out["size"] = body["size"]
    for field, allowed in (("quality", IMAGE_QUALITIES), ("output_format", IMAGE_OUTPUT_FORMATS),
                           ("background", IMAGE_BACKGROUNDS)):
        if field in body:
            if not isinstance(body[field], str) or body[field] not in allowed:
                _fail(f"{field} پشتیبانی نمی‌شود.")
            out[field] = body[field]
    if "output_compression" in body:
        if not _is_int(body["output_compression"]) or not 0 <= body["output_compression"] <= 100:
            _fail("output_compression باید بین ۰ تا ۱۰۰ باشد.")
        out["output_compression"] = body["output_compression"]
    _seed(body, out)
    if "input_references" in body:
        out["input_references"] = input_references(body["input_references"], images_only=True)
    _provider(body, out)
    return out


def job_id(value: str) -> str:
    if not JOB_ID.match(value or "") or value in (".", ".."):
        _fail("شناسه کار نامعتبر است.")
    return value


def model_segment(value: str) -> str:
    if not JOB_ID.match(value or "") or not MODEL_ID.match(value) or value in (".", ".."):
        _fail("شناسه مدل نامعتبر است.")
    return value
