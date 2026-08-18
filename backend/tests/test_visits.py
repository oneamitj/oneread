"""The headcount: that it counts the right things, and keeps nothing else.

The test that matters most here is the blunt one — after a flush, the address
and the browser name must not appear anywhere in the database file. Everything
else is arithmetic; that one is the promise.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from oneread import db as db_module
from oneread import stats, visits
from oneread.config import Settings, get_settings, set_settings
from oneread.main import create_app
from oneread.models import DailyCount
from oneread.visits import VisitCounter, looks_automated, set_counter

CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DAY_ONE = date(2026, 8, 18)
DAY_TWO = date(2026, 8, 19)


class Clock:
    def __init__(self, today: date = DAY_ONE) -> None:
        self.today = today

    def __call__(self) -> date:
        return self.today


@pytest.fixture
def store(tmp_path: Path):
    """A throwaway database, wired up the way the app wires up its own."""
    values = Settings(
        secret_key="test-secret-key",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "nowhere",
        preload_model=False,
    )
    set_settings(values)
    engine = db_module.create_engine_for(values.sqlalchemy_url)
    db_module.init_db(engine)
    db_module.set_session_factory(sessionmaker(bind=engine, expire_on_commit=False))
    yield values.data_dir / "oneread.db"
    engine.dispose()
    set_settings(None)


def written(day: date) -> dict[str, int]:
    with db_module.session_scope() as session:
        row = session.get(DailyCount, day)
        if row is None:
            return {}
        return {
            "views": row.views,
            "visitors": row.visitors,
            "signups": row.signups,
            "signins": row.signins,
        }


# --- counting -----------------------------------------------------------------


def test_the_same_person_twice_is_one_visitor(store):
    counter = VisitCounter(clock=Clock())
    counter.record_view("203.0.113.7", CHROME)
    counter.record_view("203.0.113.7", CHROME)
    counter.flush()

    assert written(DAY_ONE) == {"views": 2, "visitors": 1, "signups": 0, "signins": 0}


def test_a_different_browser_is_a_different_visitor(store):
    counter = VisitCounter(clock=Clock())
    counter.record_view("203.0.113.7", CHROME)
    counter.record_view("203.0.113.7", "Mozilla/5.0 Firefox/128.0")
    counter.flush()

    assert written(DAY_ONE)["visitors"] == 2


def test_signups_and_signins_are_counted_apart(store):
    counter = VisitCounter(clock=Clock())
    counter.record_signup()
    counter.record_signin()
    counter.record_signin()
    counter.flush()

    assert written(DAY_ONE)["signups"] == 1
    assert written(DAY_ONE)["signins"] == 2


# --- the day boundary ---------------------------------------------------------


def test_yesterday_is_written_under_yesterdays_date(store):
    clock = Clock()
    counter = VisitCounter(clock=clock)
    counter.record_view("203.0.113.7", CHROME)
    counter.record_view("198.51.100.4", CHROME)

    clock.today = DAY_TWO
    counter.record_view("203.0.113.7", CHROME)
    counter.flush()

    assert written(DAY_ONE) == {"views": 2, "visitors": 2, "signups": 0, "signins": 0}
    assert written(DAY_TWO) == {"views": 1, "visitors": 1, "signups": 0, "signins": 0}


def test_the_salt_is_replaced_at_midnight_so_two_days_dont_join(store):
    clock = Clock()
    counter = VisitCounter(clock=clock)
    counter.record_view("203.0.113.7", CHROME)
    yesterday_salt = counter._today.salt
    yesterday_digests = set(counter._today.seen)

    clock.today = DAY_TWO
    counter.record_view("203.0.113.7", CHROME)

    assert counter._today.salt != yesterday_salt
    # The same person, and nothing about the two records can say so.
    assert counter._today.seen.isdisjoint(yesterday_digests)
    counter.flush()
    assert written(DAY_TWO)["visitors"] == 1


# --- what reaches the disk ----------------------------------------------------


def test_nothing_that_identifies_anyone_reaches_the_disk(store: Path):
    counter = VisitCounter(clock=Clock())
    counter.record_view("203.0.113.7", CHROME)
    counter.flush()

    # The write-ahead log counts as disk too, and is where a fresh row actually
    # lands before a checkpoint.
    for path in (store, store.with_name(store.name + "-wal")):
        if not path.exists():
            continue
        raw = path.read_bytes()
        assert b"203.0.113.7" not in raw
        assert CHROME.encode() not in raw
        assert b"Chrome" not in raw


# --- durability ---------------------------------------------------------------


def test_a_restart_never_lowers_the_visitor_count(store):
    clock = Clock()
    before = VisitCounter(clock=clock)
    for last in range(5):
        before.record_view(f"203.0.113.{last}", CHROME)
    before.flush()

    # A new process on the same day: fresh salt, empty set, nothing carried over.
    after = VisitCounter(clock=clock)
    after.record_view("203.0.113.0", CHROME)
    after.record_view("203.0.113.1", CHROME)
    after.flush()

    assert written(DAY_ONE)["visitors"] == 5  # plateaus, never drops
    assert written(DAY_ONE)["views"] == 7  # views are deltas, so they add up


def test_a_failed_flush_keeps_its_counts(store, monkeypatch):
    counter = VisitCounter(clock=Clock())
    counter.record_view("203.0.113.7", CHROME)
    counter.record_signup()

    def explode():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(visits, "session_scope", explode)
    counter.flush()
    assert written(DAY_ONE) == {}

    monkeypatch.undo()
    counter.record_view("198.51.100.4", CHROME)
    counter.flush()

    assert written(DAY_ONE) == {"views": 2, "visitors": 2, "signups": 1, "signins": 0}


def test_the_tracked_set_stops_growing_rather_than_drifting(store, caplog):
    counter = VisitCounter(clock=Clock(), max_tracked=3)
    for last in range(10):
        counter.record_view(f"203.0.113.{last}", CHROME)
    counter.flush()

    assert written(DAY_ONE)["views"] == 10
    assert written(DAY_ONE)["visitors"] == 3
    assert sum("visitors today" in record.message for record in caplog.records) <= 1


# --- who is asking ------------------------------------------------------------


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "curl/8.4.0",
        "python-requests/2.32.3",
        "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/125.0",
        "facebookexternalhit/1.1",
        "Better Uptime Bot",
    ],
)
def test_a_machine_is_not_a_visitor(user_agent: str):
    assert looks_automated(user_agent)


def test_a_real_browser_is_a_visitor():
    assert not looks_automated(CHROME)
    assert not looks_automated("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5) Safari/605.1.15")


# --- the route ----------------------------------------------------------------


@pytest.fixture
def site(tmp_path: Path):
    """The app with a real frontend build behind it, so `/` serves the shell."""
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html><head></head><body></body></html>")
    (static / "favicon.ico").write_bytes(b"\x00\x00")
    (static / "assets" / "app.js").write_text("// built")

    values = Settings(
        secret_key="test-secret-key",
        data_dir=tmp_path / "data",
        static_dir=static,
        preload_model=False,
        login_per_minute=1000,
    )
    set_settings(values)
    engine = db_module.create_engine_for(values.sqlalchemy_url)
    db_module.init_db(engine)
    db_module.set_session_factory(sessionmaker(bind=engine, expire_on_commit=False))

    counter = VisitCounter(flush_interval_s=3600.0, clock=Clock())
    set_counter(counter)

    from oneread.routers import auth as auth_routes

    auth_routes.reset_limiters()

    app = create_app(values)
    app.dependency_overrides[get_settings] = lambda: values
    with TestClient(app) as client:
        client.headers.update({"X-Requested-With": "oneread", "User-Agent": CHROME})
        yield client, counter

    set_counter(None)
    engine.dispose()
    set_settings(None)


def test_a_page_load_is_counted(site):
    client, counter = site
    assert client.get("/").status_code == 200
    assert client.get("/e/abc123").status_code == 200
    counter.flush()

    assert written(DAY_ONE) == {"views": 2, "visitors": 1, "signups": 0, "signins": 0}


@pytest.mark.parametrize(
    "path", ["/favicon.ico", "/assets/app.js", "/api/meta", "/healthz", "/about"]
)
def test_only_a_document_load_is_a_page_view(site, path: str):
    client, counter = site
    client.get(path)
    counter.flush()

    assert written(DAY_ONE) == {}


def test_a_head_request_is_not_a_page_view(site):
    """Starlette answers HEAD from every GET route, and monitors send it."""
    client, counter = site
    client.head("/")
    counter.flush()

    assert written(DAY_ONE) == {}


def test_a_scanner_probing_for_wordpress_is_served_but_not_counted(site):
    client, counter = site
    assert client.get("/wp-login.php").status_code == 200
    counter.flush()

    assert written(DAY_ONE) == {}


@pytest.mark.parametrize("user_agent", ["Googlebot/2.1", ""])
def test_a_crawler_loading_the_page_is_not_a_visitor(site, user_agent: str):
    client, counter = site
    client.get("/", headers={"User-Agent": user_agent})
    counter.flush()

    assert written(DAY_ONE) == {}


def test_a_prefetch_is_not_somebody_arriving(site):
    client, counter = site
    client.get("/", headers={"Sec-Purpose": "prefetch;anonymous-client-ip"})
    counter.flush()

    assert written(DAY_ONE) == {}


def test_signing_up_then_signing_in_is_counted_as_one_of_each(site):
    client, counter = site
    credentials = {"username": "ada.lovelace", "password": "hunter2hunter"}

    assert client.post("/api/auth/login", json=credentials).status_code == 200
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    wrong = {**credentials, "password": "not-the-password"}
    assert client.post("/api/auth/login", json=wrong).status_code == 401
    counter.flush()

    assert written(DAY_ONE)["signups"] == 1
    assert written(DAY_ONE)["signins"] == 1


# --- the table ----------------------------------------------------------------


def test_stats_shows_the_newest_days_first_and_never_totals_visitors(store):
    clock = Clock()
    counter = VisitCounter(clock=clock)
    counter.record_view("203.0.113.7", CHROME)
    counter.record_signup()
    clock.today = DAY_TWO
    counter.record_view("203.0.113.7", CHROME)
    counter.record_view("198.51.100.4", CHROME)
    counter.flush()

    table = stats.render(stats.rows(30))
    lines = table.splitlines()

    assert lines[0].split() == list(stats.COLUMNS)
    assert lines[1].startswith(str(DAY_TWO))  # newest first
    assert lines[2].startswith(str(DAY_ONE))
    total = next(line for line in lines if line.startswith("total"))
    assert total.split()[1:] == ["3", "-", "1", "0"]
    assert "doesn't add up" in table


def test_stats_on_an_untouched_instance_says_so(store):
    assert stats.render(stats.rows(30)) == "No counts yet."
