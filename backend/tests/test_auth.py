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


def test_a_rotating_forwarded_header_does_not_shake_off_the_limit(client, settings):
    """`X-Forwarded-For` is written by the caller, so it can't be the only key."""
    from oneread.routers import auth as auth_routes

    auth_routes._login_limiter = None
    auth_routes._login_peer_limiter = None
    settings.login_per_minute = 3
    settings.login_peer_factor = 2  # so the peer bucket holds 6

    seen = [
        client.post(
            "/api/auth/login",
            json={"username": f"user{i:02d}", "password": "hunter2hunter"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},  # a fresh identity each time
        ).status_code
        for i in range(12)
    ]
    assert 429 in seen
    auth_routes._login_limiter = None
    auth_routes._login_peer_limiter = None


def test_guessing_at_one_account_is_capped_however_the_address_moves(client, settings):
    """The limit that holds when both address keys have been shaken off.

    uvicorn rewrites the connecting address from `X-Forwarded-For` by default, so
    a caller on the same host can reset an address-keyed bucket at will. The user
    id under attack is the one key that can't move.
    """
    from oneread.routers import auth as auth_routes

    for name in ("_login_limiter", "_login_peer_limiter", "_login_failure_limiter"):
        setattr(auth_routes, name, None)
    settings.login_per_minute = 1_000  # the address limits are not what's on trial
    settings.login_failures_per_minute = 4

    sign_in(client, username="victim.here", password="the-real-password")

    seen = [
        client.post(
            "/api/auth/login",
            json={"username": "victim.here", "password": f"wrong-guess-{i:03d}"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},  # a new address each time
        ).status_code
        for i in range(10)
    ]
    # Four wrong answers allowed, then the account stops answering guesses at all.
    assert seen == [401] * 4 + [429] * 6

    for name in ("_login_limiter", "_login_peer_limiter", "_login_failure_limiter"):
        setattr(auth_routes, name, None)


def test_the_limit_on_guesses_cannot_lock_someone_out_of_their_own_account(client, settings):
    """The limit is only consulted when an answer is wrong, so a right one sails past.

    Otherwise this becomes a way to keep the owner out: guess at their user id
    until the bucket empties and their own password stops working too.
    """
    from oneread.routers import auth as auth_routes

    for name in ("_login_limiter", "_login_peer_limiter", "_login_failure_limiter"):
        setattr(auth_routes, name, None)
    settings.login_per_minute = 1_000
    settings.login_failures_per_minute = 3

    sign_in(client, username="target.user", password="correct-horse-battery")
    spent = [
        client.post(
            "/api/auth/login",
            # Long enough to be a real attempt: a short one is refused as
            # malformed and never reaches the limit at all.
            json={"username": "target.user", "password": f"wrong-answer-{i:03d}"},
        ).status_code
        for i in range(5)
    ]
    assert spent[:3] == [401, 401, 401]  # three wrong answers, three tokens
    assert spent[3:] == [429, 429]  # then the guessing stops

    # And the owner walks straight in regardless.
    assert sign_in(client, username="target.user", password="correct-horse-battery")[
        "created"
    ] is False

    for name in ("_login_limiter", "_login_peer_limiter", "_login_failure_limiter"):
        setattr(auth_routes, name, None)


def test_one_visitors_attempts_do_not_lock_out_another(settings, engine):
    """The peer bucket is per-connection, so a busy neighbour isn't your problem."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from oneread import db as db_module
    from oneread.config import get_settings
    from oneread.main import create_app
    from oneread.routers import auth as auth_routes

    sql_engine = db_module.create_engine_for(settings.sqlalchemy_url)
    db_module.init_db(sql_engine)
    db_module.set_session_factory(sessionmaker(bind=sql_engine, expire_on_commit=False))

    auth_routes._login_limiter = None
    auth_routes._login_peer_limiter = None
    settings.login_per_minute = 2
    settings.login_peer_factor = 1

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    def attempt(client: TestClient, who: str) -> int:
        return client.post(
            "/api/auth/login",
            json={"username": who, "password": "hunter2hunter"},
            headers={"X-Requested-With": "oneread"},
        ).status_code

    with TestClient(app, client=("10.1.1.1", 40000)) as noisy:
        assert 429 in [attempt(noisy, f"noisy{i:02d}") for i in range(6)]

    with TestClient(app, client=("10.2.2.2", 40000)) as quiet:
        assert attempt(quiet, "quiet.one") == 200

    auth_routes._login_limiter = None
    auth_routes._login_peer_limiter = None
    sql_engine.dispose()


def test_revoking_sessions_keeps_this_device_and_drops_the_others(client, settings):
    from oneread.main import create_app

    signed_in = sign_in(client)
    stolen = client.cookies.get(settings.cookie_name)
    assert stolen

    assert client.post("/api/auth/revoke-sessions").status_code == 204
    # The device that asked carries on with the cookie it was just handed.
    assert client.get("/api/auth/me").json()["username"] == signed_in["user"]["username"]

    # Another browser holding the cookie from before is turned away.
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as elsewhere:
        elsewhere.cookies.set(settings.cookie_name, stolen)
        response = elsewhere.get("/api/auth/me")
        assert response.status_code == 401
        assert "signed out" in response.json()["message"]


def test_a_cookie_from_before_versions_existed_still_works(client, settings):
    """The column arrives with existing databases already full of live sessions."""
    from itsdangerous import URLSafeTimedSerializer

    signed_in = sign_in(client)
    old_shape = URLSafeTimedSerializer(settings.secret_key, salt="oneread.session").dumps(
        {"uid": signed_in["user"]["id"]}  # no "v" at all
    )
    client.cookies.set(settings.cookie_name, old_shape)
    assert client.get("/api/auth/me").status_code == 200


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
        assert stamp.endswith(("Z", "+00:00")), stamp
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        # And it says the right moment, not the local wall clock in UTC clothing.
        assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60

    # Same after a round trip through SQLite, which has no timezone type.
    fetched = client.get(f"/api/entries/{created['id']}").json()
    assert fetched["created_at"] == created["created_at"]
    reading = fetched["renditions"][0]
    assert reading["created_at"].endswith(("Z", "+00:00"))
