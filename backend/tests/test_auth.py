from __future__ import annotations

from conftest import sign_in


def test_first_sign_in_creates_the_account(client):
    body = sign_in(client)
    assert body["created"] is True
    assert body["user"]["username"] == "ada.lovelace"
    assert client.get("/api/auth/me").json()["username"] == "ada.lovelace"


def test_same_credentials_sign_back_in(client):
    sign_in(client)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    body = sign_in(client)
    assert body["created"] is False


def test_wrong_password_is_rejected(client):
    sign_in(client)
    response = client.post(
        "/api/auth/login", json={"username": "ada.lovelace", "password": "not-the-one"}
    )
    assert response.status_code == 401
    assert "don't match" in response.json()["message"]


def test_short_password_is_refused(client):
    response = client.post("/api/auth/login", json={"username": "ada", "password": "short"})
    assert response.status_code == 422
    assert "8 characters" in response.json()["message"]


def test_bad_username_is_refused(client):
    response = client.post(
        "/api/auth/login", json={"username": "no spaces", "password": "hunter2hunter"}
    )
    assert response.status_code == 422


def test_writes_need_the_origin_header(client):
    sign_in(client)
    response = client.post(
        "/api/entries",
        json={"title": "x", "body": "Hello."},
        headers={"X-Requested-With": ""},
    )
    assert response.status_code == 403


def test_login_is_rate_limited(client, settings):
    from oneread.routers import auth as auth_routes

    auth_routes._login_limiter = None
    settings.login_per_minute = 3
    seen = [
        client.post(
            "/api/auth/login", json={"username": f"user{i:02d}", "password": "hunter2hunter"}
        ).status_code
        for i in range(5)
    ]
    assert 429 in seen
    auth_routes._login_limiter = None


def test_a_restart_does_not_sign_everyone_out(tmp_path):
    """The signing key has to outlive the process, or every cookie dies with it."""
    from oneread.config import Settings, prepare

    first = prepare(Settings(data_dir=tmp_path / "data"))
    second = prepare(Settings(data_dir=tmp_path / "data"))
    assert first.secret_key
    assert first.secret_key == second.secret_key
    assert (tmp_path / "data" / "secret.key").stat().st_mode & 0o077 == 0


def test_a_configured_key_wins_and_no_file_is_written(tmp_path):
    from oneread.config import Settings, prepare

    settings = prepare(Settings(secret_key="from-the-environment", data_dir=tmp_path / "d"))
    assert settings.secret_key == "from-the-environment"
    assert not (tmp_path / "d" / "secret.key").exists()


def test_an_old_session_is_renewed_on_use(client, settings):
    sign_in(client)
    settings.session_refresh_after_s = 0  # pretend the cookie is getting on

    response = client.get("/api/auth/me")
    assert response.status_code == 200
    # A whole fresh cookie, with the clock started again.
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("oneread_session=")
    assert "Max-Age=2592000" in cookie
    assert "HttpOnly" in cookie

    # And the renewed cookie still works.
    assert client.get("/api/auth/me").status_code == 200


def test_a_fresh_session_is_left_alone(client):
    sign_in(client)
    response = client.get("/api/auth/me")
    assert "set-cookie" not in response.headers


def test_signing_out_is_not_undone_by_the_renewal(client, settings):
    sign_in(client)
    settings.session_refresh_after_s = 0
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_timestamps_leave_the_api_as_utc(client):
    """A naive timestamp is read as local time by a browser, so every one carries
    its offset."""
    from datetime import UTC, datetime

    sign_in(client)
    created = client.post(
        "/api/entries", json={"title": "Clocks", "body": "One sentence here."}
    ).json()

    for stamp in (created["created_at"], created["updated_at"]):
        assert stamp.endswith("Z") or stamp.endswith("+00:00"), stamp
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        # And it says the right moment, not the local wall clock in UTC clothing.
        assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60

    # Same after a round trip through SQLite, which has no timezone type.
    fetched = client.get(f"/api/entries/{created['id']}").json()
    assert fetched["created_at"] == created["created_at"]
    reading = fetched["renditions"][0]
    assert reading["created_at"].endswith(("Z", "+00:00"))
