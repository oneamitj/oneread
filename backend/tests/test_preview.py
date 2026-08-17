from __future__ import annotations

from conftest import sign_in

from oneread.config import Settings
from oneread.routers.preview import sample_line

SAMPLE = {"voice": "M3", "lang": "en", "speed": 1.1, "text": ""}


def test_preview_returns_playable_audio(client, engine):
    sign_in(client)
    response = client.post("/api/preview", json=SAMPLE)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert engine.calls[0]["voice"] == "M3"
    assert engine.calls[0]["speed"] == 1.1


def test_preview_reads_the_first_sentence_of_your_own_text(client, engine):
    sign_in(client)
    client.post(
        "/api/preview",
        json={**SAMPLE, "text": "Warm the pan first. Then the butter goes in later on."},
    )
    assert engine.calls[0]["text"] == "Warm the pan first."


def test_identical_settings_are_only_synthesized_once(client, engine):
    sign_in(client)
    client.post("/api/preview", json=SAMPLE)
    client.post("/api/preview", json=SAMPLE)
    assert len(engine.calls) == 1

    client.post("/api/preview", json={**SAMPLE, "voice": "F4"})
    assert len(engine.calls) == 2


def test_unknown_voice_is_refused(client):
    sign_in(client)
    response = client.post("/api/preview", json={**SAMPLE, "voice": "Z9"})
    assert response.status_code == 422
    assert "no voice called" in response.json()["message"]


def test_preview_needs_a_session_and_the_origin_header(client):
    assert client.post("/api/preview", json=SAMPLE).status_code == 401
    sign_in(client)
    blocked = client.post("/api/preview", json=SAMPLE, headers={"X-Requested-With": ""})
    assert blocked.status_code == 403


def test_preview_failure_is_reported(client, engine):
    sign_in(client)
    engine.fail_with = "These characters can't be spoken: '☃'"
    response = client.post("/api/preview", json=SAMPLE)
    assert response.status_code == 422
    assert "can't be spoken" in response.json()["message"]


def test_sample_line_falls_back_and_clips():
    settings = Settings(secret_key="x", preview_max_chars=40)
    assert sample_line("   ", settings) == settings.preview_sample_text
    assert sample_line("Short one.", settings) == "Short one."

    long_one = "word " * 40
    clipped = sample_line(long_one, settings)
    assert len(clipped) <= 41 and clipped.endswith("…")


def test_preview_flattens_markdown_before_picking_a_sentence(client, engine):
    sign_in(client)
    client.post(
        "/api/preview",
        json={**SAMPLE, "format": "markdown", "text": "# Title\n\nBody sentence here."},
    )
    # The heading is too short to be a cue on its own, so it keeps the sentence
    # after it. What matters is that no markdown syntax survives.
    spoken = engine.calls[0]["text"]
    assert spoken.startswith("Title.")
    assert "#" not in spoken


def test_spoken_text_endpoint_shows_what_will_be_read(client):
    sign_in(client)
    response = client.post(
        "/api/preview/text",
        json={"format": "markdown", "text": "# Hi\n\n- one\n- two"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Hi.\n\none.\n\ntwo."
    assert body["characters"] == len(body["text"])


def test_spoken_text_needs_a_session(client):
    assert client.post("/api/preview/text", json={"text": "hi"}).status_code == 401


def test_a_preview_of_more_text_than_an_entry_holds_is_refused(client, settings, engine):
    """Both routes keep one sentence, but reach it by parsing everything first."""
    sign_in(client)
    over = "word " * ((settings.max_text_chars // 5) + 1)

    response = client.post("/api/preview", json={**SAMPLE, "text": over})
    assert response.status_code == 422
    assert "limit" in response.json()["message"]
    assert engine.calls == []  # nothing was synthesized, nothing was segmented

    assert client.post("/api/preview/text", json={"text": over}).status_code == 422


def test_a_body_over_the_request_limit_is_refused_before_it_is_parsed(client, settings):
    sign_in(client)
    response = client.post(
        "/api/preview/text",
        content=b'{"text": "' + b"a" * (settings.max_request_bytes + 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "limit" in response.json()["message"]


def test_an_over_cap_body_without_a_length_is_refused_as_it_arrives(client, settings):
    """Leaving `Content-Length` off counts the bytes instead of trusting the header."""

    def streamed():
        yield b'{"text": "'
        for _ in range(settings.max_request_bytes // 4096 + 8):
            yield b"a" * 4096
        yield b'"}'

    sign_in(client)
    response = client.post(
        "/api/preview/text", content=streamed(), headers={"Content-Type": "application/json"}
    )
    # 413 in this app's own error shape, not whatever the cut-short body made
    # the route below think had happened.
    assert response.status_code == 413
    assert "limit" in response.json()["message"]
