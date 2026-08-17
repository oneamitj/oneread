"""Sampling, full readings, stopping, and estimates."""

from __future__ import annotations

import threading

from conftest import entry_of, sign_in, wait_for

BASE = {"title": "Long one", "body": "First sentence here.", "voice": "F1", "lang": "en"}
LONG = "This is one sentence of many, long enough to take a moment. " * 200


def new_entry(client, **overrides):
    response = client.post("/api/entries", json={**BASE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_creation_only_reads_the_first_few_minutes(client, engine):
    sign_in(client)
    entry = new_entry(client, body=LONG)
    sample = wait_for(client, entry["id"])

    assert sample["scope"] == "sample"
    assert engine.calls[0]["limit_s"] == 60
    assert sample["complete"] is False
    assert sample["segments_done"] < sample["segments_total"]
    assert 60 <= sample["duration_s"] < 70  # stops on the sentence that crosses it


def test_a_short_document_is_finished_by_its_sample(client):
    sign_in(client)
    entry = new_entry(client, body="Just a couple of sentences. Then it ends.")
    sample = wait_for(client, entry["id"])
    assert sample["complete"] is True
    assert sample["segments_done"] == sample["segments_total"]


def test_the_sample_length_can_be_chosen(client, engine):
    sign_in(client)
    entry = new_entry(client, body=LONG, sample_minutes=5)
    reading = wait_for(client, entry["id"])
    assert engine.calls[0]["limit_s"] == 300
    assert reading["limit_s"] == 300
    assert 300 <= reading["duration_s"] < 310


def test_an_estimate_comes_back_before_committing(client):
    sign_in(client)
    entry = new_entry(client, body=LONG)
    wait_for(client, entry["id"])

    guess = client.get(f"/api/entries/{entry['id']}/estimate").json()
    assert guess["scope"] == "full"
    assert guess["audio_s"] > 300
    assert guess["wall_s"] >= 0  # the fake engine is instant, so this can be 0
    assert guess["segments"] > 10
    # The sample already ran, so the numbers come from this machine's own pace.
    assert guess["measured"] is True

    sample = client.get(
        f"/api/entries/{entry['id']}/estimate", params={"scope": "sample", "minutes": 2}
    ).json()
    assert sample["audio_s"] == 120
    assert sample["wall_s"] <= guess["wall_s"]


def test_the_first_estimate_is_a_guess_not_a_measurement(client):
    sign_in(client)
    client.worker.stop()  # nothing has been read yet
    entry = new_entry(client, body=LONG)
    assert client.get(f"/api/entries/{entry['id']}/estimate").json()["measured"] is False


def test_the_full_reading_is_a_separate_request(client, engine):
    sign_in(client)
    entry = new_entry(client, body=LONG)
    wait_for(client, entry["id"])

    started = client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    assert started.status_code == 201
    assert started.json()["scope"] == "full"
    assert started.json()["limit_s"] is None

    full = wait_for(client, entry["id"])
    assert full["complete"] is True
    assert full["duration_s"] > 300
    assert engine.calls[-1]["limit_s"] is None
    assert len(entry_of(client, entry["id"])["renditions"]) == 2


def test_an_entry_is_frozen_while_it_is_being_read_in_full(client, engine):
    sign_in(client)
    engine.hold = threading.Event()
    entry = new_entry(client, body=LONG)

    client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    # The sample is still holding the worker, so the full reading sits pending.
    assert entry_of(client, entry["id"])["locked"] is True

    blocked = client.put(f"/api/entries/{entry['id']}", json={**BASE, "body": "New text."})
    assert blocked.status_code == 409
    assert "Stop that first" in blocked.json()["message"]
    assert client.delete(f"/api/entries/{entry['id']}").status_code == 409

    second = client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    assert second.status_code == 409

    summary = client.get("/api/entries").json()["entries"][0]
    assert summary["locked"] is True

    engine.hold.set()


def test_stopping_keeps_what_was_read(client, engine):
    sign_in(client)
    entry = new_entry(client, body=LONG)
    wait_for(client, entry["id"])

    engine.started.clear()
    engine.hold = threading.Event()
    engine.hold_at = 2  # let a couple of sentences land before we interrupt
    full = client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "full"}
    ).json()
    assert engine.started.wait(5)

    stopped = client.post(f"/api/renditions/{full['id']}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["stop_requested"] is True

    engine.hold.set()
    reading = wait_for(client, entry["id"], status="stopped")

    assert reading["id"] == full["id"]
    assert reading["complete"] is False
    assert reading["duration_s"] > 0
    assert "kept" in reading["error"]

    # And it plays, which is the whole point of keeping it.
    assert client.get(f"/api/renditions/{reading['id']}/audio").status_code == 200
    assert client.get(f"/api/renditions/{reading['id']}/subtitles.srt").status_code == 200
    partial = client.get(f"/api/renditions/{reading['id']}/audio?download=1")
    assert "long-one-partial.wav" in partial.headers["content-disposition"]

    assert entry_of(client, entry["id"])["locked"] is False


def test_a_finished_reading_cannot_be_stopped(client):
    sign_in(client)
    entry = new_entry(client, body="Short one here.")
    reading = wait_for(client, entry["id"])
    response = client.post(f"/api/renditions/{reading['id']}/stop")
    assert response.status_code == 409
    assert "already finished" in response.json()["message"]


def test_readings_pile_up_and_can_be_thrown_away_one_at_a_time(client):
    sign_in(client)
    entry = new_entry(client, body="A short document. Two sentences long.")
    first = wait_for(client, entry["id"])
    client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    second = wait_for(client, entry["id"])

    assert len(entry_of(client, entry["id"])["renditions"]) == 2
    assert first["id"] != second["id"]

    assert client.delete(f"/api/renditions/{first['id']}").status_code == 204
    remaining = entry_of(client, entry["id"])["renditions"]
    assert [r["id"] for r in remaining] == [second["id"]]
    assert client.get(f"/api/renditions/{first['id']}").status_code == 404


def test_a_running_reading_cannot_be_deleted(client, engine):
    sign_in(client)
    engine.hold = threading.Event()
    entry = new_entry(client, body=LONG)
    reading = entry_of(client, entry["id"])["renditions"][0]

    response = client.delete(f"/api/renditions/{reading['id']}")
    assert response.status_code == 409
    assert "Stop this reading" in response.json()["message"]
    engine.hold.set()


def test_the_list_leaves_the_text_and_the_cues_behind(client):
    sign_in(client)
    body = "This is one sentence of many. " * 400
    created = new_entry(client, body=body)
    wait_for(client, created["id"])

    summary = client.get("/api/entries").json()["entries"][0]
    assert "body" not in summary and "spoken" not in summary
    assert "cues" not in summary["playable"]
    assert summary["body_chars"] == len(body.strip())
    assert summary["rendition_count"] == 1
    assert summary["playable"]["status"] == "ready"
    assert len(summary["excerpt"]) < 400
    assert summary["excerpt"].endswith("…")

    full = client.get(f"/api/entries/{summary['id']}").json()
    assert full["body"] == body.strip()


def test_short_entries_are_not_given_an_ellipsis(client):
    sign_in(client)
    new_entry(client, body="Just the one line.")
    summary = client.get("/api/entries").json()["entries"][0]
    assert summary["excerpt"] == "Just the one line."


def test_progress_is_reported_while_reading(client):
    sign_in(client)
    client.worker.progress_interval_s = 0  # write every segment, not once a second
    entry = new_entry(client, body="One sentence here. " * 30)
    reading = wait_for(client, entry["id"])
    assert reading["progress"] == 1.0
    assert reading["segments_done"] == reading["segments_total"]


def test_a_hundred_thousand_characters_is_accepted(client, settings):
    sign_in(client)
    assert settings.max_text_chars == 100_000
    body = "A sentence that runs on for a while. " * 2700
    assert 90_000 < len(body) <= 100_000
    assert client.post("/api/entries", json={**BASE, "body": body}).status_code == 201


def test_past_the_limit_is_still_refused(client, settings):
    sign_in(client)
    over = "x" * (settings.max_text_chars + 1)
    response = client.post("/api/entries", json={**BASE, "body": over})
    assert response.status_code == 422
    assert "limit for one entry is 100000" in response.json()["message"]


def test_a_job_interrupted_by_shutdown_keeps_its_audio(client, engine):
    sign_in(client)
    engine.hold = threading.Event()
    engine.hold_at = 2  # some audio exists by the time the shutdown lands
    entry = new_entry(client, body=LONG)
    assert engine.started.wait(5)

    worker = client.worker
    stopper = threading.Thread(target=worker.stop, kwargs={"timeout": 5})
    stopper.start()
    engine.hold.set()
    stopper.join(10)

    reading = entry_of(client, entry["id"])["renditions"][0]
    assert reading["status"] == "stopped"
    assert reading["duration_s"] > 0
    assert client.get(f"/api/renditions/{reading['id']}/audio").status_code == 200


def test_editing_while_a_sample_runs_calls_it_off(client, engine):
    sign_in(client)
    released = threading.Event()
    engine.hold = released
    engine.hold_at = 2
    entry = new_entry(client, body=LONG)
    assert engine.started.wait(5)

    # A sample doesn't freeze the entry the way a full reading does.
    changed = client.put(f"/api/entries/{entry['id']}", json={**BASE, "body": "New text."})
    assert changed.status_code == 200

    for rendition in changed.json()["renditions"]:
        if rendition["scope"] == "sample" and rendition["status"] == "processing":
            assert rendition["stop_requested"] is True
    assert len(changed.json()["renditions"]) == 2

    released.set()
    wait_for(client, entry["id"])
    assert engine.calls[-1]["text"] == "New text."


def test_the_card_is_given_the_most_complete_reading_to_play(client):
    sign_in(client)
    entry = new_entry(client, body="Two sentences. That is all of it.")
    sample = wait_for(client, entry["id"])

    summary = client.get("/api/entries").json()["entries"][0]
    assert summary["playable"]["id"] == sample["id"]
    assert summary["active"] is None

    client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    full = wait_for(client, entry["id"])

    summary = client.get("/api/entries").json()["entries"][0]
    assert summary["rendition_count"] == 2
    assert summary["playable"]["id"] == full["id"]  # newest of the complete ones


def test_a_partial_reading_never_beats_a_complete_one(client, engine):
    import threading

    sign_in(client)
    entry = new_entry(client, body="Two sentences. That is all of it.")
    whole = wait_for(client, entry["id"])
    assert whole["complete"] is True

    engine.started.clear()
    engine.hold = threading.Event()
    engine.hold_at = 1
    started = client.post(
        f"/api/entries/{entry['id']}/renditions", json={"scope": "full"}
    ).json()
    assert engine.started.wait(5)

    live = client.get("/api/entries").json()["entries"][0]
    assert live["active"]["id"] == started["id"]
    assert live["playable"]["id"] == whole["id"]  # keep playing the good one

    client.post(f"/api/renditions/{started['id']}/stop")
    engine.hold.set()
    wait_for(client, entry["id"], status="stopped")

    after = client.get("/api/entries").json()["entries"][0]
    assert after["playable"]["id"] == whole["id"]
    assert after["active"] is None


def test_the_recording_an_entry_plays_cannot_be_removed(client):
    sign_in(client)
    entry = new_entry(client, body="Two sentences. That is all of it.")
    only = wait_for(client, entry["id"])
    assert only["is_default"] is True

    refused = client.delete(f"/api/renditions/{only['id']}")
    assert refused.status_code == 409
    assert "the recording the entry plays" in refused.json()["message"]

    # Make another, and the old one is free to go.
    client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    newer = wait_for(client, entry["id"])
    assert newer["is_default"] is True

    assert client.delete(f"/api/renditions/{only['id']}").status_code == 204
    assert client.delete(f"/api/renditions/{newer['id']}").status_code == 409


def test_a_failed_recording_is_not_protected(client, engine):
    sign_in(client)
    engine.fail_with = "Nope."
    entry = new_entry(client, body="Two sentences. That is all of it.")
    failed = wait_for(client, entry["id"], status="failed")
    assert failed["is_default"] is False
    assert client.delete(f"/api/renditions/{failed['id']}").status_code == 204


def test_the_detail_route_marks_which_one_is_default(client):
    sign_in(client)
    entry = new_entry(client, body="Two sentences. That is all of it.")
    sample = wait_for(client, entry["id"])
    client.post(f"/api/entries/{entry['id']}/renditions", json={"scope": "full"})
    full = wait_for(client, entry["id"])

    flags = {r["id"]: r["is_default"] for r in entry_of(client, entry["id"])["renditions"]}
    assert flags == {sample["id"]: False, full["id"]: True}
    assert client.get(f"/api/renditions/{full['id']}").json()["is_default"] is True
