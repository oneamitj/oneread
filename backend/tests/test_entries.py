from __future__ import annotations

from conftest import entry_of, sign_in, wait_for

ENTRY = {
    "title": "Kitchen notes",
    "body": "Warm the pan first. Then the butter goes in.",
    "tags": ["cooking", "Cooking", " kitchen "],
    "voice": "M2",
    "lang": "en",
    "speed": 1.2,
}


def create(client, **overrides):
    payload = {**ENTRY, **overrides}
    response = client.post("/api/entries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_dedupes_tags_and_starts_a_sample(client):
    sign_in(client)
    entry = create(client)
    assert entry["tags"] == ["cooking", "kitchen"]
    assert len(entry["renditions"]) == 1
    assert entry["renditions"][0]["scope"] == "sample"
    assert entry["renditions"][0]["limit_s"] == 60

    reading = wait_for(client, entry["id"])
    assert reading["duration_s"] > 0
    assert reading["complete"] is True  # the whole thing fits inside the sample


def test_audio_and_subtitles_download(client):
    sign_in(client)
    entry = create(client)
    reading = wait_for(client, entry["id"])
    rid = reading["id"]

    audio = client.get(f"/api/renditions/{rid}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert "content-disposition" not in audio.headers

    download = client.get(f"/api/renditions/{rid}/audio?download=1")
    # Downloads say which reading they are, so a sample never masquerades as the
    # whole book in someone's downloads folder.
    assert 'filename="kitchen-notes-sample.wav"' in download.headers["content-disposition"]

    srt = client.get(f"/api/renditions/{rid}/subtitles.srt")
    assert srt.status_code == 200
    assert srt.text.startswith("1\n00:00:00,000 --> ")
    assert 'filename="kitchen-notes-sample.srt"' in srt.headers["content-disposition"]

    assert client.get(f"/api/renditions/{rid}/subtitles.vtt").text.startswith("WEBVTT")

    detail = client.get(f"/api/renditions/{rid}").json()
    assert len(detail["cues"]) == 2
    assert detail["cues"][0]["text"] == "Warm the pan first."
    assert abs(detail["cues"][-1]["end"] - reading["duration_s"]) < 0.01


def test_a_failed_reading_says_why(client, engine):
    sign_in(client)
    engine.fail_with = "There is no text to read."
    entry = create(client)
    failed = wait_for(client, entry["id"], status="failed")
    assert "no text to read" in failed["error"]
    assert client.get(f"/api/renditions/{failed['id']}/audio").status_code == 409


def test_an_unplanned_failure_does_not_repeat_the_libraries_own_words(client, engine, caplog):
    """A break we have no sentence for gets a plain one, not the internals.

    Whatever a library says on the way down names paths and objects inside the
    server. That belongs in the log, which is what the reader is pointed at.
    """
    inner = "onnxruntime: failed to load /opt/supertonic/models/decoder.onnx (errno 13)"
    engine.crash_with = RuntimeError(inner)
    sign_in(client)

    with caplog.at_level("ERROR", logger="oneread.worker"):
        entry = create(client)
        failed = wait_for(client, entry["id"], status="failed")

    assert "Something went wrong while generating audio." in failed["error"]
    for leaked in ("onnxruntime", "/opt/supertonic", "errno", "RuntimeError"):
        assert leaked not in failed["error"]
    # And the promise the message makes is kept: the detail is in the log.
    assert inner in caplog.text
    assert "Traceback" in caplog.text


def test_search_covers_title_body_and_tags(client):
    sign_in(client)
    create(client, title="Kitchen notes", body="Warm the pan first.", tags=["cooking"])
    create(client, title="Bike repair", body="The chain needs oil.", tags=["garage"])

    def titles(query):
        response = client.get("/api/entries", params={"q": query})
        assert response.status_code == 200
        return [e["title"] for e in response.json()["entries"]]

    assert titles("kitchen") == ["Kitchen notes"]
    assert titles("chain") == ["Bike repair"]
    assert titles("garage") == ["Bike repair"]
    assert titles("kitc") == ["Kitchen notes"]  # prefix match while typing
    assert titles("zzzz") == []


def test_search_survives_fts_punctuation(client):
    sign_in(client)
    create(client, title="Quoted", body='He said "hello" loudly.')
    for query in ['"', "AND", "*", "he said*"]:
        assert client.get("/api/entries", params={"q": query}).status_code == 200


def test_tag_filter(client):
    sign_in(client)
    create(client, title="One", tags=["a", "b"])
    create(client, title="Two", tags=["b"])

    response = client.get("/api/entries", params={"tag": ["a"]})
    assert [e["title"] for e in response.json()["entries"]] == ["One"]
    assert response.json()["tags"] == ["a", "b"]

    both = client.get("/api/entries", params={"tag": ["a", "b"]})
    assert len(both.json()["entries"]) == 1


def test_editing_text_makes_a_fresh_sample_but_editing_tags_does_not(client, engine):
    sign_in(client)
    entry = create(client)
    wait_for(client, entry["id"])
    assert len(engine.calls) == 1

    tags_only = client.put(
        f"/api/entries/{entry['id']}", json={**ENTRY, "tags": ["new"], "title": "Renamed"}
    )
    assert tags_only.status_code == 200
    assert len(tags_only.json()["renditions"]) == 1
    assert len(engine.calls) == 1

    changed = client.put(
        f"/api/entries/{entry['id']}", json={**ENTRY, "body": "Something else entirely."}
    )
    assert len(changed.json()["renditions"]) == 2
    wait_for(client, entry["id"])
    assert len(engine.calls) == 2


def test_delete_takes_the_audio_with_it(client):
    from pathlib import Path

    sign_in(client)
    entry = create(client)
    reading = wait_for(client, entry["id"])
    path = Path(client.get(f"/api/renditions/{reading['id']}").json() and "")

    detail = entry_of(client, entry["id"])
    assert detail["renditions"][0]["status"] == "ready"

    audio = client.get(f"/api/renditions/{reading['id']}/audio")
    assert audio.status_code == 200
    del path

    assert client.delete(f"/api/entries/{entry['id']}").status_code == 204
    assert client.get(f"/api/entries/{entry['id']}").status_code == 404
    assert client.get(f"/api/renditions/{reading['id']}/audio").status_code == 404


def test_entries_are_private_to_their_owner(client):
    sign_in(client, "ada.lovelace")
    mine = create(client)
    reading = wait_for(client, mine["id"])

    client.post("/api/auth/logout")
    sign_in(client, "grace.hopper", "compilers1906")

    assert client.get("/api/entries").json()["entries"] == []
    assert client.get(f"/api/entries/{mine['id']}").status_code == 404
    assert client.get(f"/api/renditions/{reading['id']}").status_code == 404
    assert client.get(f"/api/renditions/{reading['id']}/audio").status_code == 404
    assert client.delete(f"/api/entries/{mine['id']}").status_code == 404


def test_text_length_limit(client, settings):
    sign_in(client)
    settings.max_text_chars = 40
    response = client.post("/api/entries", json={**ENTRY, "body": "word " * 20})
    assert response.status_code == 422
    assert "limit for one entry is 40" in response.json()["message"]


def test_queue_depth_is_capped(client, settings):
    sign_in(client)
    settings.max_queued_per_user = 1
    client.worker.stop()  # nothing drains, so the queue stays full
    create(client)
    response = client.post("/api/entries", json=ENTRY)
    assert response.status_code == 429
    assert "Wait for one to finish" in response.json()["message"]


def test_meta_lists_voices_and_limits(client):
    body = client.get("/api/meta").json()
    assert {v["id"] for v in body["voices"]} >= {"F1", "M1"}
    assert "en" in body["languages"]
    assert body["max_text_chars"] > 0
    assert body["sample_minutes"] == 1
    assert body["sample_minute_choices"] == [1, 3, 5]
    assert client.get("/healthz").json() == {"status": "ok"}


def test_anonymous_visitors_see_nothing(client):
    assert client.get("/api/entries").status_code == 401
    assert client.post("/api/entries", json=ENTRY).status_code == 401


MARKDOWN = """# Weeknight pasta

Boil the water first.

- salt the water
- keep the pasta moving

| Step | Minutes |
|------|---------|
| Boil | 10 |
"""


def test_markdown_entries_are_flattened_before_they_are_read(client, engine):
    sign_in(client)
    entry = create(client, title="Pasta", body=MARKDOWN, format="markdown")
    reading = wait_for(client, entry["id"])

    spoken = engine.calls[0]["text"]
    assert "#" not in spoken and "|" not in spoken
    assert spoken.startswith("Weeknight pasta.")
    assert "Step: Boil. Minutes: 10." in spoken

    assert reading["format"] == "markdown"
    assert entry_of(client, entry["id"])["spoken"] == spoken
    lines = [cue["text"] for cue in client.get(
        f"/api/renditions/{reading['id']}").json()["cues"]]
    assert "salt the water." in lines
    assert "Table with columns: Step, Minutes." in lines


def test_plain_is_the_default_and_keeps_every_character(client, engine):
    sign_in(client)
    entry = create(client, body="Read **this** exactly. Hashes # too.")
    reading = wait_for(client, entry["id"])
    assert reading["format"] == "plain"
    assert engine.calls[0]["text"] == "Read **this** exactly. Hashes # too."


def test_switching_format_reads_it_again(client, engine):
    sign_in(client)
    entry = create(client, body=MARKDOWN)
    wait_for(client, entry["id"])
    assert len(engine.calls) == 1

    switched = client.put(
        f"/api/entries/{entry['id']}",
        json={**ENTRY, "body": MARKDOWN, "format": "markdown"},
    )
    assert len(switched.json()["renditions"]) == 2
    wait_for(client, entry["id"])
    assert len(engine.calls) == 2
    assert "#" not in engine.calls[1]["text"]


def test_an_unknown_format_is_refused(client):
    sign_in(client)
    response = client.post("/api/entries", json={**ENTRY, "format": "rst"})
    assert response.status_code == 422
    assert "plain, markdown" in response.json()["message"]


def test_markdown_with_no_words_fails_with_a_reason(client):
    sign_in(client)
    entry = create(client, body="---\n\n***\n", format="markdown")
    failed = wait_for(client, entry["id"], status="failed")
    assert "no words left to read" in failed["error"]


def test_characters_a_voice_cannot_say_do_not_fail_the_reading(client, engine):
    """A stray arrow in pasted text is dropped, not turned into an error."""
    sign_in(client)
    entry = create(client, body="Warm the pan ↳ first. Then 🧈 goes in.")
    reading = wait_for(client, entry["id"])
    assert reading["error"] is None
    assert engine.calls[-1]["text"] == "Warm the pan first. Then goes in."
