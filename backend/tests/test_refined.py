"""The experimental reading that hands the voice a few sentences at a time."""

from __future__ import annotations

from conftest import sign_in, wait_for

# Eight sentences of about 42 characters, one paragraph: enough that the
# default 350-character chunk holds several of them.
TEXT = " ".join(f"Sentence number {n} sits here in the middle." for n in range(1, 21))
BASE = {"title": "Twenty lines", "body": TEXT, "voice": "F1", "lang": "en", "speed": 1.05}


def new_entry(client, **overrides):
    response = client.post("/api/entries", json={**BASE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_reading_is_sentence_by_sentence_unless_asked_otherwise(client, engine):
    sign_in(client)
    entry = new_entry(client)
    reading = wait_for(client, entry["id"])

    assert reading["mode"] == "sentence"
    assert engine.calls[-1]["mode"] == "sentence"
    cues = client.get(f"/api/renditions/{reading['id']}").json()["cues"]
    assert len(cues) == reading["segments_total"] == 20


def test_a_refined_reading_groups_sentences_but_still_counts_them(client, engine):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    started = client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "full", "mode": "paragraph"}
    )
    assert started.status_code == 201, started.text
    assert started.json()["mode"] == "paragraph"

    reading = wait_for(client, entry["id"])
    assert engine.calls[-1]["mode"] == "paragraph"
    # Counted in sentences whichever way it was cut up, so coverage and the
    # progress bar mean the same thing in both modes.
    assert reading["segments_total"] == 20
    assert reading["document_segments"] == 20
    assert reading["complete"] is True

    cues = client.get(f"/api/renditions/{reading['id']}").json()["cues"]
    assert 1 < len(cues) < 20  # several sentences to a cue
    assert [cue["i"] for cue in cues] == sorted(cue["i"] for cue in cues)
    assert cues[0]["i"] == 0
    # Nothing is dropped and no sentence is cut in half.
    spoken = " ".join(cue["text"] for cue in cues)
    assert spoken == TEXT
    assert all(cue["text"].endswith(".") for cue in cues)


def test_a_refined_range_starts_where_the_reader_pointed(client, engine):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    client.post(
        f"/api/entries/{entry['id']}/renditions",
        json={"scope": "range", "mode": "paragraph", "start": 5, "end": 9},
    )
    reading = wait_for(client, entry["id"])

    assert reading["segments_total"] == 4
    cues = client.get(f"/api/renditions/{reading['id']}").json()["cues"]
    assert cues[0]["i"] == 5
    assert cues[0]["text"].startswith("Sentence number 6")
    assert " ".join(cue["text"] for cue in cues).endswith(
        "Sentence number 9 sits here in the middle."
    )


def test_the_subtitles_still_come_out(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])
    client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "full", "mode": "paragraph"}
    )
    reading = wait_for(client, entry["id"])

    srt = client.get(f"/api/renditions/{reading['id']}/subtitles.srt")
    assert srt.status_code == 200
    assert "-->" in srt.text
    assert "Sentence number 1 sits here in the middle." in srt.text


def test_a_refined_reading_can_be_estimated_first(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    plain = client.get(f"/api/entries/{entry['id']}/estimate?scope=full").json()
    refined = client.get(
        f"/api/entries/{entry['id']}/estimate?scope=full&mode=paragraph"
    ).json()

    # Same words, same count, and the pauses the voice makes itself are longer
    # than the ones we would have inserted between sentences.
    assert refined["characters"] == plain["characters"]
    assert refined["segments"] == plain["segments"]
    assert refined["audio_s"] > plain["audio_s"]


def test_an_unknown_mode_is_refused(client):
    sign_in(client)
    entry = new_entry(client)
    wait_for(client, entry["id"])

    assert client.get(f"/api/entries/{entry['id']}/estimate?mode=sing").status_code == 422
    assert (
        client.post(
            f"/api/entries/{entry['id']}/renditions", json={"scope": "full", "mode": "sing"}
        ).status_code
        == 422
    )
