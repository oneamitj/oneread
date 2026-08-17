"""The guards that aren't tied to one feature: CORS, the key file, text limits."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient

from oneread.config import Settings, _stored_secret
from oneread.main import create_app

# --- CORS --------------------------------------------------------------------


def test_wildcard_cors_origin_is_refused():
    """Sessions are cookies, so "*" would hand the library to any site.

    Starlette answers `allow_origins=["*"]` plus credentials by reflecting
    whichever origin asked, which also lifts the `X-Requested-With` guard: an
    allowed origin's preflight approves the header. So the wildcard has to fail
    at startup rather than quietly turn the same-origin policy off.
    """
    with pytest.raises(ValueError, match="can't be"):
        Settings(cors_origins="*")

    with pytest.raises(ValueError, match="can't be"):
        Settings(cors_origins="https://oneread.example,*")


def test_named_cors_origins_are_kept():
    settings = Settings(cors_origins="https://a.example, https://b.example")
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_only_the_named_origin_is_answered(settings):
    settings.cors_origins = ["https://oneread.example"]
    with TestClient(create_app(settings)) as client:
        allowed = client.options(
            "/api/entries",
            headers={
                "Origin": "https://oneread.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-requested-with",
            },
        )
        assert allowed.headers["access-control-allow-origin"] == "https://oneread.example"
        assert allowed.headers["access-control-allow-credentials"] == "true"

        stranger = client.options(
            "/api/entries",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-requested-with",
            },
        )
        assert "access-control-allow-origin" not in stranger.headers

        # The header list is spelled out rather than "*", so a preflight asking
        # for something that isn't on it comes back refused.
        odd = client.options(
            "/api/entries",
            headers={
                "Origin": "https://oneread.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-smuggled",
            },
        )
        assert odd.status_code == 400


# --- the signing key ---------------------------------------------------------


def test_the_key_file_is_never_readable_by_anyone_else(tmp_path: Path):
    """Created at 0600, not created and then narrowed.

    `write_text` opens under the process umask, so a chmod afterwards leaves a
    window where any local account can read the key — and the key is enough to
    sign a cookie naming any user.
    """
    before = os.umask(0o000)  # as permissive as it gets, to catch a umask reliance
    try:
        key = _stored_secret(tmp_path)
    finally:
        os.umask(before)

    path = tmp_path / "secret.key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().strip() == key


def test_an_existing_key_is_reused_not_replaced(tmp_path: Path):
    """Two workers starting together must not sign with different keys."""
    first = _stored_secret(tmp_path)
    assert _stored_secret(tmp_path) == first


# --- the routes that reflow text without making audio ------------------------


def test_spoken_text_is_rate_limited(client, settings):
    from oneread.routers import preview as preview_routes

    preview_routes._text_limiter = None
    settings.text_per_minute = 3
    sign_in(client)

    body = {"text": "Hello there.", "format": "plain"}
    seen = [client.post("/api/preview/text", json=body).status_code for _ in range(5)]
    assert 429 in seen
    preview_routes._text_limiter = None


@pytest.mark.parametrize("route", ["segments", "estimate"])
def test_measuring_an_entry_is_rate_limited(client, settings, route):
    """Neither route makes audio, so neither is held to the generation limit.

    Both segment the whole document on every call though, against one process.
    """
    from oneread.routers import entries as entry_routes

    sign_in(client)
    created = client.post("/api/entries", json={"title": "Long", "body": "One. Two. Three."})
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    entry_routes._text_limiter = None
    settings.text_per_minute = 3

    seen = [client.get(f"/api/entries/{entry_id}/{route}").status_code for _ in range(5)]
    assert 429 in seen
    entry_routes._text_limiter = None
