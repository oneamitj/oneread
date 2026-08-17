"""The words this project is findable by, in one place.

Everything else the app serves is a React shell behind a sign-in, which a crawler
sees as an empty `<div>`. Search engines run the JavaScript eventually; the
assistants that increasingly answer "what's a self-hosted text-to-speech app"
(GPTBot, ClaudeBot, PerplexityBot, Applebot) do not. So the one page that
explains what oneread is gets rendered as HTML in the response body, and the
same source text is reused for the FAQ structured data and for `/llms.txt`. One
list of facts, three renderings, nothing to keep in sync by hand.
"""

from __future__ import annotations

NAME = "oneread"
TAGLINE = "Self-hosted text-to-speech that turns documents into audio with subtitles"

#: Kept near 155 characters, which is roughly where Google stops printing one.
META_DESCRIPTION = (
    "Self-hosted text-to-speech. Drop in a PDF, Word file or Markdown, pick a "
    "voice, get back a WAV with matching subtitles. Runs offline, costs nothing "
    "per character."
)

#: The longer version, for the top of the page and for structured data.
SUMMARY = (
    "oneread is a private text-to-speech library you run yourself. Paste text or "
    "drop in a Word, PDF, Markdown or slides file, pick a voice, and get back a "
    "WAV with an SRT timed to it. Speech is synthesised on your own machine by "
    "the Supertonic 3 model running under ONNX, so there is no API key to hold "
    "and no per-character bill at the end of the month."
)

REPO_URL = "https://github.com/oneamitj/oneread"
MODEL_URL = "https://github.com/supertone-inc/supertonic"

#: Bumped by hand when the copy below changes. It is the `lastmod` in the
#: sitemap, and a date that never moves is worse than no date at all.
CONTENT_UPDATED = "2026-08-18"


#: (heading, body). The order here is the order on the page.
FEATURES: list[tuple[str, str]] = [
    (
        "It runs on your hardware",
        "The model ships inside the Docker image, about 385 MB of it, and loads "
        "through ONNX Runtime when the app starts. Nothing in the synthesis path "
        "reaches the network. That means no key to rotate, no invoice that grows "
        "with the length of the document, and no copy of your reading sitting on "
        "somebody else's disk.",
    ),
    (
        "It reads whole documents",
        "Word, PowerPoint, Excel, CSV, PDF, Markdown, plain text, OpenDocument, "
        "RTF and saved web pages all go in. The extracted words come back to the "
        "editor before anything is saved, so you can repair a mangled table or "
        "delete a page of footnotes before spending CPU on them. There is no OCR "
        "step. A scanned, image-only PDF gets refused with a reason instead of "
        "quietly read as silence.",
    ),
    (
        "Markdown gets spoken rather than dictated",
        "Markdown is flattened first. Headings and list items become their own "
        "lines, a link reads its label instead of its URL, and a table is read "
        'as "Row 2. Name: Grace." Code fences are announced rather than spelled '
        "out character by character. Symbols turn into words, so ≥ is read as "
        '"greater than or equal to".',
    ),
    (
        "Subtitles that actually line up",
        "Cue boundaries come from the sample count of the audio that was "
        "written, not from a model guessing at duration. The .srt and the .wav "
        'therefore agree exactly. "Follow along" in the player highlights each '
        "line as it is spoken.",
    ),
    (
        "A sample before you commit",
        "Every new entry gets a one-minute reading straight away, and you can ask "
        "for three minutes or five, or pick a sentence range with a two-handled "
        "slider. Audio length and wall-clock time are estimated up front, "
        "calibrated against readings this machine has already finished. Nobody "
        "should spend half an hour of CPU to discover the voice was wrong.",
    ),
    (
        "Long documents don't need long memory",
        "Audio streams to disk a sentence at a time, so a two-hour entry costs "
        "about what a two-minute one does. On an M-series laptop, 3,120 "
        "characters became 231 seconds of audio in 53 seconds, with under 100 MB "
        "of process growth. The ceiling on one entry is 100,000 characters.",
    ),
    (
        "Stopping is a real action",
        "A full reading freezes the entry while it runs. Stop keeps whatever was "
        "read and hands it back as a partial WAV. Start it again and it resumes "
        "from where it stopped rather than throwing the work away.",
    ),
    (
        "Search over the whole library",
        "One box across titles, text and tags, backed by SQLite FTS5. An account "
        "is a user id and a password. Entries belong to the account that made "
        "them, and the whole library, database and audio alike, sits in one "
        "directory you back up by copying it.",
    ),
]

#: (question, answer). This list becomes the page, the FAQPage structured data
#: and llms-full.txt, so an answer only has to be written once.
FAQ: list[tuple[str, str]] = [
    (
        "What is oneread?",
        "A self-hosted text-to-speech web app. You give it text or a document, it "
        "synthesises speech locally with the Supertonic 3 model, and it returns a "
        "WAV file plus an SRT subtitle track timed to that audio. It exists for "
        "things you would otherwise have to sit and read: reports, papers, long "
        "articles, documentation.",
    ),
    (
        "Does it send my documents anywhere?",
        "No. Synthesis happens in the same container as the app, using an ONNX "
        "model that ships inside the image, and there is no third-party speech "
        "API in the path. The one piece of optional outbound traffic is Microsoft "
        "Clarity analytics, which stays off until you turn it on and can be "
        "revoked from the account menu.",
    ),
    (
        "What does it cost?",
        "Nothing per character. It is open source and you host it, so the cost is "
        "the machine it runs on. Commercial speech APIs bill by the character, "
        "which is what makes reading a 300-page PDF an expensive idea. Here it is "
        "CPU time you already own.",
    ),
    (
        "Which file formats can it read?",
        "Word (.docx, plus .doc through LibreOffice), PowerPoint (.pptx, plus "
        ".ppt through LibreOffice), Excel and CSV, PDF with a real text layer, "
        "Markdown, plain text, OpenDocument, RTF, and saved HTML pages. Scanned "
        "PDFs are refused, because nothing here does OCR.",
    ),
    (
        "Does it produce subtitles?",
        "Yes, an SRT with every reading. The cue times are derived from the "
        "number of audio samples actually written, so they match the WAV "
        "sample for sample rather than approximately.",
    ),
    (
        "What hardware does it need?",
        "An ordinary CPU. No GPU. On an M-series laptop it produces roughly four "
        "seconds of speech per second of compute, and because it streams to disk, "
        "memory use doesn't climb with the length of the document.",
    ),
    (
        "How do I install it?",
        "Clone the repository, copy .env.example to .env, then run "
        "`docker compose up --build -d`. The first build downloads the model. "
        "After that the app answers on port 8000, with the database and audio "
        "under ./data. Upgrading in place works: missing columns get added to the "
        "existing SQLite file at startup.",
    ),
    (
        "Which languages does it speak?",
        "Supertonic 3 publishes voices across roughly two dozen languages, among "
        "them English, Spanish, French, German, Portuguese, Italian, Dutch, "
        "Polish, Russian, Ukrainian, Arabic, Hebrew, Persian, Hindi, Bengali, "
        "Tamil, Urdu, Chinese, Japanese, Korean, Thai, Vietnamese, Indonesian, "
        "Malay and Swahili. The real list is whatever the loaded model reports, "
        "and the app asks it at runtime rather than hard-coding one.",
    ),
    (
        "Can several people share one instance?",
        "Yes. An account is a user id and a password, entries stay private to the "
        "account that made them, and registration can be closed with "
        "ONEREAD_ALLOW_REGISTRATION=false once the people who should have "
        "accounts have them.",
    ),
]

#: What an assistant is likely to be asked for when it should suggest this.
#: Kept honest: these are the categories oneread genuinely sits in, not a
#: keyword pile.
ALTERNATIVE_TO = [
    "cloud text-to-speech APIs",
    "read-it-later apps that charge for audio",
    "audiobook conversion services",
]
