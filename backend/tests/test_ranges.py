"""Reading a slice, and choosing the voice at the moment you ask for it."""

from __future__ import annotations

from conftest import entry_of, sign_in, wait_for

TEXT = " ".join(f"Sentence number {n} sits here in the middle." for n in range(1, 21))
BASE = {"title": "Twenty lines", "body": TEXT, "voice": "F1", "lang": "en", "speed": 1.05}


def new_entry(client, **overrides):
    response = client.post("/api/entries", json={**BASE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_the_segment_list_is_what_the_picker_is_drawn_from(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    body = client.get(f"/api/entries/{entry['id']}/segments").json()
    assert len(body["segments"]) == 20
    assert body["segments"][0]["i"] == 0
    assert body["segments"][0]["text"] == "Sentence number 1 sits here in the middle."
    assert body["audio_s"] > 0
    assert body["measured"] is True

    # The timeline runs forwards, with a gap between one sentence and the next.
    first, second = body["segments"][0], body["segments"][1]
    assert first["start_s"] == 0.0
    assert second["start_s"] >= first["end_s"]
    assert body["segments"][-1]["end_s"] <= body["audio_s"] + 0.1


def test_a_range_reads_only_those_sentences(client, engine):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    started = client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "range", "start": 5, "end": 9},
    )
    assert started.status_code == 201
    assert started.json()["scope"] == "range"
    assert (started.json()["start_segment"], started.json()["end_segment"]) == (5, 9)

    reading = wait_for(client, entry["id"])
    assert engine.calls[-1]["start_segment"] == 5
    assert engine.calls[-1]["end_segment"] == 9
    assert reading["segments_total"] == 4
    assert reading["complete"] is False  # a slice is never the whole document

    cues = client.get(f"/api/renditions/{reading['id']}").json()["cues"]
    assert len(cues) == 4
    # Cue numbers point back at the document; the clock starts at zero.
    assert [c["i"] for c in cues] == [5, 6, 7, 8]
    assert cues[0]["start"] == 0.0
    assert cues[0]["text"] == "Sentence number 6 sits here in the middle."


def test_a_range_downloads_under_its_own_name(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])
    client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "range", "start": 2, "end": 4},
    )
    reading = wait_for(client, entry["id"])
    headers = client.get(f"/api/renditions/{reading['id']}/audio?download=1").headers
    assert 'filename="twenty-lines-extract.wav"' in headers["content-disposition"]


def test_a_backwards_range_is_refused(client):
    sign_in(client)
    entry = new_entry(client)
    for bad in ({"start": 9, "end": 4}, {"start": 3, "end": 3}, {"start": -1}):
        response = client.post(
            f"/api/entries/{entry['id']}/renditions", json={"scope": "range", **bad}
        )
        assert response.status_code == 422, bad


def test_a_range_past_the_end_says_so(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])
    response = client.get(
        f"/api/entries/{entry['id']}/estimate",
        params={"scope": "range", "start": 900, "end": 950},
    )
    assert response.status_code == 422
    assert "doesn't cover any text" in response.json()["message"]


def test_a_range_can_be_estimated_before_it_is_read(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    whole = client.get(f"/api/entries/{entry['id']}/estimate").json()
    part = client.get(
        f"/api/entries/{entry['id']}/estimate",
        params={"scope": "range", "start": 0, "end": 5},
    ).json()
    assert part["segments"] == 5
    assert part["audio_s"] < whole["audio_s"]


def test_the_voice_can_be_changed_at_the_moment_you_ask(client, engine):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])
    assert engine.calls[0]["voice"] == "F1"

    client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "full", "voice": "M4", "speed": 1.4, "lang": "na"},
    )
    reading = wait_for(client, entry["id"])

    assert (reading["voice"], reading["speed"], reading["lang"]) == ("M4", 1.4, "na")
    assert engine.calls[-1]["voice"] == "M4"
    assert engine.calls[-1]["speed"] == 1.4

    # And it sticks, so the next reading doesn't have to be told again.
    after = entry_of(client, entry["id"])
    assert (after["voice"], after["speed"], after["lang"]) == ("M4", 1.4, "na")


def test_an_unknown_voice_is_refused_here_too(client):
    sign_in(client)
    entry = new_entry(client)
    response = client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "full", "voice": "Z9"}
    )
    assert response.status_code == 422
    assert "no voice called" in response.json()["message"]


def test_a_sample_length_can_be_asked_for_directly(client, engine):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "sample", "minutes": 5}
    )
    reading = wait_for(client, entry["id"])
    assert reading["limit_s"] == 300
    assert engine.calls[-1]["limit_s"] == 300


def test_a_short_extract_does_not_become_the_entry_default(client):
    """A fifteen-second slice must not replace the minute the card was playing."""
    sign_in(client)
    entry = new_entry(client, body=" ".join(f"Line {n} here." for n in range(1, 200)))
    sample = wait_for(client, entry["id"])
    assert sample["complete"] is False  # too long to finish inside the sample
    assert sample["is_default"] is True

    client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "range", "start": 0, "end": 3},
    )
    extract = wait_for(client, entry["id"])
    assert extract["duration_s"] < sample["duration_s"]

    flags = {r["id"]: r["is_default"] for r in entry_of(client, entry["id"])["renditions"]}
    assert flags[sample["id"]] is True
    assert flags[extract["id"]] is False
    assert client.get("/api/entries").json()["entries"][0]["playable"]["id"] == sample["id"]

    # And the extract is removable, because it isn't what the entry leads with.
    assert client.delete(f"/api/renditions/{extract['id']}").status_code == 204


def test_a_reading_records_what_it_covers_and_how_it_opens(client):
    sign_in(client)
    entry = new_entry(client)
    sample = wait_for(client, entry["id"])

    assert sample["document_segments"] == 20
    assert sample["opening"] == "Sentence number 1 sits here in the middle."

    client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "range", "start": 12, "end": 16},
    )
    extract = wait_for(client, entry["id"])

    # A slice covers 4 of 20 sentences, starting at 12 — that's what the strip draws.
    assert extract["document_segments"] == 20
    assert extract["start_segment"] == 12
    assert extract["segments_done"] == 4
    assert extract["opening"] == "Sentence number 13 sits here in the middle."


def test_older_readings_get_their_coverage_filled_in(client, settings):
    """A library made before recordings tracked coverage still draws its bars."""
    from sqlalchemy import text as sql

    from oneread import db as db_module

    sign_in(client)
    entry = new_entry(client)
    reading = wait_for(client, entry["id"])

    # Rewind this one to how it would have been stored before.
    engine = db_module.session_factory().kw["bind"]
    with engine.begin() as conn:
        conn.execute(
            sql("UPDATE renditions SET document_segments = 0, opening = NULL")
        )
    del settings

    db_module.init_db(engine)

    after = entry_of(client, entry["id"])["renditions"][0]
    assert after["id"] == reading["id"]
    assert after["document_segments"] == 20
    assert after["opening"] == "Sentence number 1 sits here in the middle."
