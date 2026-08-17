"""The public pages, and the switch that decides whether they invite anyone in.

Most of what matters here is the default. An instance nobody configured is
somebody's laptop, and it has to refuse crawlers without being told to.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oneread.config import Settings, get_settings, set_settings
from oneread.main import create_app
from oneread.routers import site

SCRIPT = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
ROBOTS_META = re.compile(r'<meta name="robots" content="([^"]*)"')


def build(tmp_path: Path, **overrides) -> TestClient:
    values = Settings(
        secret_key="test-secret-key",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "nowhere",
        preload_model=False,
        **overrides,
    )
    set_settings(values)
    # Rendered pages are cached per (public_url, public_site), and every test
    # here uses a different pairing.
    site._CACHE.clear()
    app = create_app(values)
    app.dependency_overrides[get_settings] = lambda: values
    return TestClient(app)


@pytest.fixture
def public(tmp_path: Path):
    client = build(tmp_path, public_site=True, public_url="https://oneread.example")
    yield client
    set_settings(None)


@pytest.fixture
def private(tmp_path: Path):
    client = build(tmp_path)
    yield client
    set_settings(None)


# --- the private default ------------------------------------------------------


def test_unconfigured_instance_turns_every_crawler_away(private: TestClient):
    body = private.get("/robots.txt").text
    assert "User-agent: *" in body
    assert "Disallow: /" in body
    assert "Allow:" not in body


def test_private_instance_has_no_sitemap(private: TestClient):
    assert private.get("/sitemap.xml").status_code == 404


def test_private_about_says_noindex(private: TestClient):
    response = private.get("/about")
    assert response.status_code == 200
    assert ROBOTS_META.search(response.text).group(1) == "noindex, nofollow"


def test_a_public_url_alone_is_not_permission_to_index(tmp_path: Path):
    """Naming the address is how links are built, not consent to be crawled."""
    client = build(tmp_path, public_url="https://oneread.example")
    try:
        assert "Disallow: /\n" in client.get("/robots.txt").text
        assert client.get("/sitemap.xml").status_code == 404
    finally:
        set_settings(None)


# --- once it is meant to be found ---------------------------------------------


def test_robots_names_the_assistant_crawlers(public: TestClient):
    body = public.get("/robots.txt").text
    for agent in ("GPTBot", "ClaudeBot", "PerplexityBot"):
        assert f"User-agent: {agent}" in body
    assert body.count("Disallow: /api/") == len(site.AI_AGENTS) + 1
    assert "Sitemap: https://oneread.example/sitemap.xml" in body


def test_robots_keeps_private_paths_out(public: TestClient):
    body = public.get("/robots.txt").text
    assert "Disallow: /e/" in body
    assert "Disallow: /api/" in body


def test_sitemap_lists_the_two_public_pages(public: TestClient):
    body = public.get("/sitemap.xml").text
    assert "<loc>https://oneread.example/</loc>" in body
    assert "<loc>https://oneread.example/about</loc>" in body


def test_about_is_indexable_and_canonical(public: TestClient):
    body = public.get("/about").text
    assert ROBOTS_META.search(body).group(1).startswith("index, follow")
    assert '<link rel="canonical" href="https://oneread.example/about" />' in body


def test_about_carries_the_prose_not_an_empty_shell(public: TestClient):
    """The whole point: a crawler that runs no JavaScript still gets the words."""
    body = public.get("/about").text
    assert "Supertonic" in body
    assert "docker compose up" in body
    assert body.count("<h3>") >= 15  # every feature and every question


# --- structured data ----------------------------------------------------------


def test_structured_data_parses_and_describes_the_software(public: TestClient):
    graph = json.loads(SCRIPT.search(public.get("/about").text).group(1))["@graph"]
    types = {node["@type"] for node in graph}
    assert {"SoftwareApplication", "FAQPage", "WebSite"} <= types

    software = next(n for n in graph if n["@type"] == "SoftwareApplication")
    assert software["offers"]["price"] == "0"
    assert software["url"] == "https://oneread.example/"

    faq = next(n for n in graph if n["@type"] == "FAQPage")
    assert len(faq["mainEntity"]) == len(site.seo.FAQ)


def test_the_inline_script_is_allowed_by_its_own_hash(public: TestClient):
    """Belt and braces on the one exception to "no inline scripts".

    Get the hash wrong and the structured data is blocked in the browser while
    still looking perfectly fine in the response body, which is the kind of bug
    nobody notices for a year.
    """
    response = public.get("/about")
    inline = SCRIPT.search(response.text).group(1)
    digest = base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode()

    policy = response.headers["content-security-policy"]
    script_src = next(d for d in policy.split("; ") if d.startswith("script-src"))
    assert f"'sha256-{digest}'" in script_src
    # Styles are inline by design; scripts are not, and the hash is what keeps
    # that true for the one script on the page.
    assert "unsafe-inline" not in script_src


# --- llms.txt -----------------------------------------------------------------


def test_llms_txt_points_at_the_long_form(public: TestClient):
    body = public.get("/llms.txt").text
    assert body.startswith("# oneread")
    assert "https://oneread.example/llms-full.txt" in body
    assert "https://github.com/oneamitj/oneread" in body


def test_llms_full_carries_every_feature_and_answer(public: TestClient):
    body = public.get("/llms-full.txt").text
    for heading, _ in site.seo.FEATURES:
        assert heading in body
    for question, _ in site.seo.FAQ:
        assert question in body


def test_llms_files_are_plain_text(public: TestClient):
    for path in ("/llms.txt", "/llms-full.txt", "/robots.txt"):
        assert public.get(path).headers["content-type"].startswith("text/plain")


# --- the trailing slash people will inevitably type ---------------------------


def test_a_trailing_slash_in_the_public_url_does_not_double_up(tmp_path: Path):
    client = build(tmp_path, public_site=True, public_url="https://oneread.example/")
    try:
        assert "https://oneread.example//" not in client.get("/about").text
        assert "<loc>https://oneread.example/about</loc>" in client.get("/sitemap.xml").text
    finally:
        set_settings(None)
