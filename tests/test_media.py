"""Media studio: request validation, image/video lifecycle against a mocked OpenRouter, files, budget."""
import base64
import json
import time

import httpx
import pytest

from app.modules.media import openrouter, validation

from .conftest import H

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture
def upstream(monkeypatch):
    calls = {"polls": 0, "requests": []}

    def handler(req: httpx.Request):
        calls["requests"].append((req.method, req.url.path, req.headers.get("authorization")))
        p = req.url.path
        if p == "/api/v1/images" and req.method == "POST":
            body = json.loads(req.content)
            fmt = body.get("output_format")
            item = {"b64_json": base64.b64encode(b"<svg/>").decode(), "media_type": "image/svg+xml"} if fmt == "svg" else {"b64_json": PNG}
            return httpx.Response(200, json={"data": [item] * body.get("n", 1), "usage": {"cost": 0.04}})
        if p == "/api/v1/videos" and req.method == "POST":
            return httpx.Response(200, json={"id": "job_1", "status": "pending"})
        if p == "/api/v1/videos/job_1":
            calls["polls"] += 1
            return httpx.Response(200, json={"id": "job_1", "status": "completed" if calls["polls"] > 1 else "in_progress",
                                             "usage": {"cost": 0.5}})
        if p == "/api/v1/videos/job_1/content":
            return httpx.Response(200, content=b"v" * 1000, headers={"content-type": "video/mp4"})
        if p == "/api/v1/videos/models":
            return httpx.Response(200, json={"data": [{"id": "google/veo-3", "name": "Veo 3"}]})
        return httpx.Response(404, json={"error": {"message": "nope"}})

    real = openrouter._client

    def fake(timeout):
        c = real(timeout)
        return httpx.AsyncClient(base_url=openrouter.ORIGIN, transport=httpx.MockTransport(handler), headers=c.headers)
    monkeypatch.setattr(openrouter, "_client", fake)
    return calls


def _configure(c, **kw):
    r = c.put("/api/media/settings", json={"api_key": "sk-or-test-9876", **kw}, headers=H)
    assert r.status_code == 200
    return r.json()


def _wait(c, gid, status, tries=40):
    for _ in range(tries):
        g = c.get(f"/api/media/generations/{gid}").json()
        if g["status"] == status:
            return g
        time.sleep(0.05)
    raise AssertionError(f"generation {gid} stuck in {g['status']}")


# ---------------------------------------------------------------- validation (ported from the Node server tests)
def test_video_payload_keeps_only_allowed_fields():
    out = validation.video_payload({"model": "google/veo-3", "prompt": "a lipstick", "duration": 8, "aspect_ratio": "16:9",
                                    "generate_audio": False, "seed": 7})
    assert out == {"model": "google/veo-3", "prompt": "a lipstick", "duration": 8, "aspect_ratio": "16:9", "generate_audio": False, "seed": 7}


@pytest.mark.parametrize("body", [
    {"model": "x/y", "prompt": "a", "callback_url": "https://evil"},                    # unknown field
    {"model": "x/y", "prompt": " "},                                                     # empty prompt
    {"model": "../etc", "prompt": "a"},                                                  # bad model id
    {"model": "x/y", "prompt": "a", "duration": 0},
    {"model": "x/y", "prompt": "a", "duration": True},                                   # bool is not an int
    {"model": "x/y", "prompt": "a", "size": "1280x720", "resolution": "720p"},          # size excludes resolution
    {"model": "x/y", "prompt": "a", "frame_images": [{"type": "image_url", "image_url": {"url": "http://x"}, "frame_type": "first_frame"}]},
    {"model": "x/y", "prompt": "a", "input_references": [{"type": "image_url", "image_url": {"url": "https://u:p@x"}}]},
    {"model": "x/y", "prompt": "a", "provider": {"__proto__": {}}},
])
def test_video_payload_rejects(body):
    with pytest.raises(validation.ValidationError):
        validation.video_payload(body)


def test_image_payload_limits():
    assert validation.image_payload({"model": "a/b", "prompt": "p", "n": 10, "output_format": "webp"})["n"] == 10
    for bad in ({"n": 11}, {"quality": "ultra"}, {"output_compression": 101}, {"aspect_ratio": "wide"},
                {"input_references": [{"type": "video_url", "video_url": {"url": "https://x"}}]}):
        with pytest.raises(validation.ValidationError):
            validation.image_payload({"model": "a/b", "prompt": "p", **bad})


# ---------------------------------------------------------------- lifecycle
def test_settings_never_return_the_key(owner):
    s = _configure(owner)
    assert s["key_set"] and s["key_hint"] == "…9876" and "api_key" not in s
    cfg = owner.get("/api/media/config").json()
    assert cfg["configured"] and "sk-or" not in json.dumps(cfg)


def test_generate_requires_a_key(owner, upstream):
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "a/b"}], "fields": {"prompt": "p"}}, headers=H)
    assert r.status_code == 200
    g = _wait(owner, r.json()["items"][0]["id"], "failed")
    assert g["error"]["code"] == "missing_api_key"


def test_image_generation_saves_files(owner, upstream):
    _configure(owner)
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "openai/gpt-image-1", "name": "GPT"}],
                                                 "fields": {"prompt": "lipstick", "n": 2}}, headers=H)
    g = _wait(owner, r.json()["items"][0]["id"], "completed")
    assert g["cost"] == 0.04 and len(g["outputs"]) == 2
    f = owner.get(g["outputs"][1]["url"])
    assert f.status_code == 200 and f.content.startswith(b"\x89PNG")
    assert upstream["requests"][0][2] == "Bearer sk-or-test-9876"


def test_svg_output_is_served_as_attachment(owner, upstream):
    _configure(owner)
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "a/b"}], "fields": {"prompt": "logo", "output_format": "svg"}},
                   headers=H)
    g = _wait(owner, r.json()["items"][0]["id"], "completed")
    f = owner.get(g["outputs"][0]["url"])
    assert f.headers["content-type"].startswith("image/svg+xml") and f.headers["content-disposition"].startswith("attachment")


def test_video_job_is_polled_and_downloaded_by_the_server(owner, upstream):
    _configure(owner)
    r = owner.post("/api/media/generate", json={"kind": "video", "models": [{"id": "google/veo-3", "name": "Veo"}],
                                                 "fields": {"prompt": "orbit", "duration": 5}}, headers=H)
    gid = r.json()["items"][0]["id"]
    _wait(owner, gid, "pending")
    assert owner.post(f"/api/media/generations/{gid}/refresh", headers=H).json()["status"] == "in_progress"
    g = owner.post(f"/api/media/generations/{gid}/refresh", headers=H).json()
    assert g["status"] == "completed" and g["cost"] == 0.5 and g["outputs"][0]["bytes"] == 1000
    part = owner.get(g["outputs"][0]["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    time.sleep(0.1)
    feed = owner.get("/api/activity?module=media").json()
    assert feed and feed[0]["kind"] == "video_done"


def test_monthly_budget_blocks_new_generations(owner, upstream):
    _configure(owner, monthly_limit_usd=0.03)
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "a/b"}], "fields": {"prompt": "p"}}, headers=H)
    _wait(owner, r.json()["items"][0]["id"], "completed")                 # costs 0.04 → over the cap
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "a/b"}], "fields": {"prompt": "p"}}, headers=H)
    assert r.status_code == 400 and "سقف" in r.json()["detail"]


def test_invalid_request_spends_nothing(owner, upstream):
    _configure(owner)
    r = owner.post("/api/media/generate", json={"kind": "video", "models": [{"id": "a/b"}], "fields": {"prompt": "p", "duration": 999}},
                   headers=H)
    assert r.status_code == 400
    assert not [x for x in upstream["requests"] if x[0] == "POST"]


def test_only_creator_or_owner_can_delete(owner, upstream):
    from .conftest import as_user, make_user
    _configure(owner)
    r = owner.post("/api/media/generate", json={"kind": "image", "models": [{"id": "a/b"}], "fields": {"prompt": "p"}}, headers=H)
    gid = r.json()["items"][0]["id"]
    _wait(owner, gid, "completed")
    make_user(owner, "omid", {"media": "creator"})
    as_user(owner, "omid")
    assert owner.delete(f"/api/media/generations/{gid}", headers=H).status_code == 403
