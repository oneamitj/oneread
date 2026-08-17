"""Reading files: what comes out, what gets refused, and what's kept."""

from __future__ import annotations

from pathlib import Path

import documents
import pytest
from conftest import sign_in, wait_for

from oneread.extract import UnreadableFile, extract

# --- extraction, without the web layer ---------------------------------------


def test_plain_text_comes_back_as_it_went_in():
    got = extract(b"Hello there.\n\nSecond paragraph.", "notes.txt")
    assert got.format == "plain"
    assert got.text == "Hello there.\n\nSecond paragraph."
    assert got.title == "notes"
    assert not got.truncated


def test_markdown_stays_markdown_and_takes_its_heading_as_a_title():
    got = extract(b"# Quarterly Report\n\n- one\n- two\n", "readme.md")
    assert got.format == "markdown"
    assert got.title == "Quarterly Report"
    assert "- one" in got.text  # untouched, so the markdown reader can do its job


def test_csv_reads_as_sentences_not_commas():
    got = extract(b"Region,Units\nNorth,412\nSouth,388\n", "sales.csv")
    assert "Columns: Region, Units." in got.text
    assert "Row 1. Region: North. Units: 412." in got.text
    assert "Row 2. Region: South. Units: 388." in got.text


def test_a_single_column_csv_still_reads():
    got = extract(b"one\ntwo\nthree\n", "list.csv")
    assert "Row 1. one." in got.text
    assert "Row 3. three." in got.text


def test_word_keeps_tables_where_they_were_written():
    got = extract(documents.docx(), "report.docx")
    assert got.title == "Quarterly Report"
    assert got.kind == "document"
    # The heading, then the prose, then the table, then the closing line.
    assert got.text.index("Revenue grew") < got.text.index("Row 1. Region: North.")
    assert got.text.index("Row 2. Region: South.") < got.text.index("That is the whole picture.")


def test_slides_are_numbered_and_notes_come_along():
    got = extract(documents.pptx(), "deck.pptx")
    assert got.kind == "slides"
    assert got.text.startswith("Slide 1. How it went.")
    assert "Up and to the right." in got.text
    assert "Notes. Mention the caveat about March." in got.text
    # The title is read once, as part of the slide line, not again after it.
    assert got.text.count("How it went") == 1


def test_a_spreadsheet_names_each_sheet():
    got = extract(documents.xlsx(), "sales.xlsx")
    assert "Sheet: Q3." in got.text
    assert "Sheet: Q4." in got.text
    assert "Row 1. Region: North. Units: 412. Revenue: 88300." in got.text


def test_pdf_rejoins_lines_and_mends_split_words():
    got = extract(
        documents.pdf(
            [
                "The quick brown fox jumps over the lazy dog.",
                "A second line that continues the same para-",
                "graph without a full stop yet.",
            ]
        ),
        "paper.pdf",
    )
    assert "paragraph" in got.text  # the hyphen and the line break both gone
    assert "\n" not in got.text.strip()


def test_a_pdf_of_pictures_says_so():
    with pytest.raises(UnreadableFile) as problem:
        extract(documents.pdf([]), "scan.pdf")
    assert "pictures of pages" in str(problem.value)


def test_rich_text_loses_its_markup():
    got = extract(rb"{\rtf1\ansi Dear friend, \b hello \b0 and goodbye.\par}", "letter.rtf")
    assert got.text.strip() == "Dear friend, hello and goodbye."


def test_html_drops_scripts_and_keeps_the_title():
    got = extract(
        b"<html><head><title>A Page</title><style>p{color:red}</style></head>"
        b"<body><h1>Heading</h1><p>First para.</p>"
        b"<script>alert(1)</script><p>Second para.</p></body></html>",
        "page.html",
    )
    assert got.title == "A Page"
    assert "alert" not in got.text
    assert "color:red" not in got.text
    assert "First para." in got.text and "Second para." in got.text


@pytest.mark.parametrize(
    ("build", "name", "expected"),
    [
        (documents.odt, "open.odt", "Some prose here."),
        (documents.ods, "open.ods", "Row 1. Region: North. Units: 412."),
        (documents.odp, "open.odp", "Hello slide."),
    ],
)
def test_opendocument_files_read(build, name, expected):
    assert expected in extract(build(), name).text


def test_utf16_and_windows_text_both_decode():
    assert "café" in extract("café au lait".encode("utf-16"), "a.txt").text
    assert "café" in extract("café au lait".encode("cp1252"), "b.txt").text


def test_a_long_file_is_cut_at_a_sentence_and_says_so():
    got = extract(("Sentence number one. " * 500).encode(), "long.txt", limit=300)
    assert got.truncated
    assert len(got.text) <= 300
    assert got.text.endswith(".")


# --- refusals ----------------------------------------------------------------


def test_an_unknown_extension_lists_what_does_work():
    with pytest.raises(UnreadableFile) as problem:
        extract(b"MZ\x90\x00", "thing.exe")
    assert ".exe" in str(problem.value)
    assert "markdown" in str(problem.value)


def test_an_empty_file_is_refused():
    with pytest.raises(UnreadableFile, match="empty"):
        extract(b"   \n  ", "nothing.txt")


def test_a_file_lying_about_its_type_is_refused():
    with pytest.raises(UnreadableFile, match="whatever the name says"):
        extract(b"just text, not a zip", "liar.docx")


def test_a_zip_bomb_is_refused_before_anything_parses_it():
    with pytest.raises(UnreadableFile, match="unpacks to far more"):
        extract(documents.zip_bomb(), "bomb.docx")


def test_declared_xml_entities_are_refused():
    with pytest.raises(UnreadableFile, match="won't run"):
        extract(documents.entity_bomb(), "evil.docx")


def test_legacy_formats_explain_themselves_when_libreoffice_is_absent():
    with pytest.raises(UnreadableFile) as problem:
        extract(b"\xd0\xcf\x11\xe0anything", "old.doc", soffice="")
    assert ".docx" in str(problem.value)


# --- through the API ---------------------------------------------------------


def upload(client, name: str, data: bytes):
    return client.post("/api/uploads", files={"file": (name, data, "application/octet-stream")})


def test_uploading_reads_the_file_and_suggests_a_title(client):
    sign_in(client)
    response = upload(client, "report.docx", documents.docx())
    assert response.status_code == 201

    body = response.json()
    assert body["title"] == "Quarterly Report"
    assert body["format"] == "plain"
    assert body["kind"] == "document"
    assert body["truncated"] is False
    assert "Row 1. Region: North." in body["text"]
    assert body["bytes"] > 0


def test_the_file_is_kept_and_can_be_downloaded_again(client, settings):
    sign_in(client)
    original = documents.docx()
    staged = upload(client, "report.docx", original).json()

    created = client.post(
        "/api/entries",
        json={"title": "The report", "body": staged["text"], "upload_id": staged["id"]},
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["source"] == {
        "name": "report.docx",
        # The extension decides the type, not whatever the client claimed.
        "media_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "bytes": len(original),
    }

    got = client.get(f"/api/entries/{entry['id']}/source")
    assert got.status_code == 200
    assert got.content == original
    # Downloaded under the name it was uploaded with, not a slug of the title.
    assert got.headers["content-disposition"] == 'attachment; filename="report.docx"'

    # It left staging and now lives beside the entry.
    assert not any(settings.staging_dir.rglob("*.docx"))
    kept = next(settings.upload_dir.rglob("*.docx"))
    assert kept.is_file()
    assert kept.parent.name == entry["id"]


def test_the_spoken_text_downloads_as_a_plain_file(client):
    sign_in(client)
    created = client.post(
        "/api/entries",
        json={"title": "Notes", "body": "# Heading\n\n- one\n- two", "format": "markdown"},
    )
    entry_id = created.json()["id"]
    wait_for(client, entry_id)

    got = client.get(f"/api/entries/{entry_id}/text.txt")
    assert got.status_code == 200
    assert 'filename="notes.txt"' in got.headers["content-disposition"]
    assert "#" not in got.text  # the flattened version, not the markdown


def test_an_entry_with_no_file_behind_it_says_so(client):
    sign_in(client)
    entry_id = client.post("/api/entries", json={"title": "Typed", "body": "Just typed."}).json()[
        "id"
    ]
    assert client.get(f"/api/entries/{entry_id}/source").status_code == 404


def test_nobody_else_can_reach_the_file(client):
    sign_in(client)
    staged = upload(client, "report.docx", documents.docx()).json()
    entry_id = client.post(
        "/api/entries",
        json={"title": "Mine", "body": staged["text"], "upload_id": staged["id"]},
    ).json()["id"]

    sign_in(client, username="grace.hopper", password="compiler123")
    assert client.get(f"/api/entries/{entry_id}/source").status_code == 404


def test_someone_elses_upload_cannot_be_claimed(client):
    sign_in(client)
    staged = upload(client, "report.docx", documents.docx()).json()

    sign_in(client, username="grace.hopper", password="compiler123")
    stolen = client.post(
        "/api/entries",
        json={"title": "Not mine", "body": "Some words.", "upload_id": staged["id"]},
    )
    assert stolen.status_code == 404


def test_deleting_the_entry_removes_the_file(client, settings):
    sign_in(client)
    staged = upload(client, "report.docx", documents.docx()).json()
    entry_id = client.post(
        "/api/entries",
        json={"title": "Doomed", "body": staged["text"], "upload_id": staged["id"]},
    ).json()["id"]

    kept = Path(next(settings.upload_dir.rglob("*.docx")))
    assert kept.is_file()

    assert client.delete(f"/api/entries/{entry_id}").status_code == 204
    assert not kept.exists()


def test_a_second_upload_replaces_the_first(client, settings):
    sign_in(client)
    first = upload(client, "report.docx", documents.docx()).json()
    entry_id = client.post(
        "/api/entries",
        json={"title": "Report", "body": first["text"], "upload_id": first["id"]},
    ).json()["id"]

    second = upload(client, "deck.pptx", documents.pptx()).json()
    updated = client.put(
        f"/api/entries/{entry_id}",
        json={"title": "Report", "body": second["text"], "upload_id": second["id"]},
    )
    assert updated.status_code == 200
    assert updated.json()["source"]["name"] == "deck.pptx"
    assert not any(settings.upload_dir.rglob("*.docx"))


def test_discarding_an_upload_takes_the_file_with_it(client, settings):
    sign_in(client)
    staged = upload(client, "notes.txt", b"Some words to read.").json()
    assert any(settings.staging_dir.rglob("*.txt"))

    assert client.delete(f"/api/uploads/{staged['id']}").status_code == 204
    assert not any(settings.staging_dir.rglob("*.txt"))
    assert client.delete(f"/api/uploads/{staged['id']}").status_code == 404


def test_an_unreadable_file_comes_back_as_a_sentence(client):
    sign_in(client)
    response = upload(client, "scan.pdf", documents.pdf([]))
    assert response.status_code == 422
    assert "pictures of pages" in response.json()["message"]


def test_a_file_over_the_size_limit_is_refused(client, settings):
    sign_in(client)
    too_big = b"a" * (settings.max_upload_bytes + 1024)
    response = upload(client, "huge.txt", too_big)
    assert response.status_code == 413
    assert "limit" in response.json()["message"]


def test_signed_out_visitors_cannot_upload(client):
    assert upload(client, "notes.txt", b"Hello.").status_code == 401


def test_the_meta_route_lists_what_can_be_uploaded(client):
    body = client.get("/api/meta").json()
    extensions = {item["ext"] for item in body["upload_types"]}
    assert {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx", ".csv"} <= extensions
    assert body["max_upload_bytes"] > 0
