"""The public, server-rendered pages: /about, robots.txt, sitemap.xml, llms.txt.

Rendered here rather than in React because the readers that matter for being
found — Googlebot's first pass, and every assistant crawler, none of which runs
JavaScript — would otherwise get an empty div. `/` stays the app; this is the
one page that explains it, linked from the sign-in card.

Nothing here reads the database or the session, so none of it is metered and
none of it can leak an entry.
"""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from .. import seo
from ..config import Settings, get_settings

router = APIRouter(tags=["site"], include_in_schema=False)

#: The crawlers that feed assistant answers and AI search. Named one by one
#: rather than left to the `*` rule, because several of them read a bare `*`
#: conservatively and skip a site that never mentions them. Removing a name here
#: is how you opt this instance out of that model's index.
AI_AGENTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "Applebot",
    "Applebot-Extended",
    "meta-externalagent",
    "Amazonbot",
    "cohere-ai",
    "DuckAssistBot",
]

#: Private by definition — one is a reader's own entry, the other is the API the
#: app talks to itself with. Neither belongs in an index.
PRIVATE_PATHS = ["/api/", "/e/"]

_CACHE: dict[tuple, str] = {}


def _cached(key: tuple, build) -> str:
    if key not in _CACHE:
        _CACHE[key] = build()
    return _CACHE[key]


def _absolute(settings: Settings, path: str) -> str:
    return f"{settings.public_url}{path}" if settings.public_url else path


# --- /about ------------------------------------------------------------------


@router.get("/about")
def about(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    key = ("about", settings.public_url, settings.public_site)
    body = _cached(key, lambda: _about_page(settings))
    return Response(
        body,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": _csp(_structured_data(settings)),
            # Long enough that a crawler's repeat visits are cheap, short enough
            # that a copy change is live the same day.
            "Cache-Control": "public, max-age=3600",
        },
    )


def _csp(json_ld: str) -> str:
    """The page's own policy: one inline script, allowed by its hash.

    The app-wide policy has no 'unsafe-inline' for scripts and that is worth
    keeping, but structured data has to sit inline in the document for a crawler
    to associate it with the page. A hash lets both be true. `setdefault` in
    SecurityHeadersMiddleware leaves this alone.
    """
    digest = base64.b64encode(hashlib.sha256(json_ld.encode()).digest()).decode()
    return (
        "default-src 'self'; "
        f"script-src 'sha256-{digest}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )


def _structured_data(settings: Settings) -> str:
    """JSON-LD for the page: what the software is, and the answers on it.

    Two separate audiences read this. Search engines use FAQPage and
    SoftwareApplication to decide what the page is about; assistants use it as a
    compact, unambiguous statement of the same facts the prose gives, which is
    what makes a citation come out right rather than paraphrased into something
    the project doesn't do.
    """
    home = _absolute(settings, "/")
    page = _absolute(settings, "/about")
    graph = [
        {
            "@type": "SoftwareApplication",
            "@id": f"{page}#software",
            "name": seo.NAME,
            "alternateName": "oneread text-to-speech",
            "applicationCategory": "MultimediaApplication",
            "applicationSubCategory": "Text-to-speech",
            "operatingSystem": "Docker, Linux, macOS, Windows",
            "description": seo.SUMMARY,
            "url": home,
            "softwareHelp": page,
            "codeRepository": seo.REPO_URL,
            "license": seo.REPO_URL,
            "isAccessibleForFree": True,
            "offers": {
                "@type": "Offer",
                "price": "0",
                "priceCurrency": "USD",
            },
            "featureList": [heading for heading, _ in seo.FEATURES],
        },
        {
            "@type": "WebSite",
            "@id": f"{home}#website",
            "name": seo.NAME,
            "url": home,
            "description": seo.SUMMARY,
        },
        {
            "@type": "FAQPage",
            "@id": f"{page}#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {"@type": "Answer", "text": answer},
                }
                for question, answer in seo.FAQ
            ],
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=2)


def _about_page(settings: Settings) -> str:
    title = f"{seo.NAME}: {seo.TAGLINE}"
    canonical = _absolute(settings, "/about")
    image = _absolute(settings, "/og-image.png")
    robots = (
        "index, follow, max-image-preview:large, max-snippet:-1"
        if settings.public_site
        else "noindex, nofollow"
    )

    features = "\n".join(
        f"""      <section class="feature">
        <h3>{escape(heading)}</h3>
        <p>{escape(body)}</p>
      </section>"""
        for heading, body in seo.FEATURES
    )
    faq = "\n".join(
        f"""      <section class="qa">
        <h3>{escape(question)}</h3>
        <p>{escape(answer)}</p>
      </section>"""
        for question, answer in seo.FAQ
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light dark" />
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(seo.META_DESCRIPTION)}" />
    <meta name="robots" content="{robots}" />
    <link rel="canonical" href="{escape(canonical)}" />
    <link rel="icon" href="/favicon.ico" sizes="48x48" />
    <link rel="icon" type="image/png" href="/favicon-32x32.png" sizes="32x32" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
    <link rel="alternate" type="text/plain" href="/llms.txt" title="llms.txt" />

    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{escape(seo.NAME)}" />
    <meta property="og:title" content="{escape(title)}" />
    <meta property="og:description" content="{escape(seo.SUMMARY)}" />
    <meta property="og:url" content="{escape(canonical)}" />
    <meta property="og:image" content="{escape(image)}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{escape(title)}" />
    <meta name="twitter:description" content="{escape(seo.SUMMARY)}" />
    <meta name="twitter:image" content="{escape(image)}" />

    <style>
      :root {{
        color-scheme: light dark;
        --bg: #eef1f7;
        --card: #ffffff;
        --ink: #171a21;
        --muted: #565d6b;
        --line: #d8deea;
        --accent: #2f5bd7;
      }}
      @media (prefers-color-scheme: dark) {{
        :root {{
          --bg: #0b0c10;
          --card: #14161d;
          --ink: #eef1f7;
          --muted: #9aa3b4;
          --line: #262a35;
          --accent: #8aa9ff;
        }}
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          Helvetica, Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      .wrap {{ max-width: 46rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
      header.top {{
        display: flex; align-items: center; justify-content: space-between;
        gap: 1rem; margin-bottom: 3rem;
      }}
      header.top img {{ height: 2rem; width: auto; }}
      a {{ color: var(--accent); }}
      .cta {{
        display: inline-block; padding: 0.55rem 1.1rem; border-radius: 999px;
        background: var(--accent); color: #fff; text-decoration: none;
        font-weight: 600; font-size: 0.95rem;
      }}
      h1 {{ font-size: clamp(1.9rem, 5vw, 2.6rem); line-height: 1.15; margin: 0 0 1rem; }}
      h2 {{ font-size: 1.35rem; margin: 3rem 0 1rem; }}
      h3 {{ font-size: 1.05rem; margin: 0 0 0.4rem; }}
      .lede {{ font-size: 1.15rem; color: var(--muted); margin: 0 0 2rem; }}
      .feature, .qa {{
        background: var(--card); border: 1px solid var(--line);
        border-radius: 14px; padding: 1.1rem 1.25rem; margin-bottom: 0.75rem;
      }}
      .feature p, .qa p {{ margin: 0; color: var(--muted); }}
      pre {{
        background: var(--card); border: 1px solid var(--line);
        border-radius: 14px; padding: 1rem 1.25rem; overflow-x: auto;
        font-size: 0.9rem;
      }}
      footer {{
        margin-top: 3.5rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
        color: var(--muted); font-size: 0.9rem;
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <header class="top">
        <a href="/" aria-label="{escape(seo.NAME)} home">
          <picture>
            <source
              srcset="/brand/oneread-logo-dark-256.png"
              media="(prefers-color-scheme: dark)"
            />
            <img
              src="/brand/oneread-logo-256.png"
              alt="{escape(seo.NAME)}"
              width="256"
              height="253"
            /></picture>
        </a>
        <a class="cta" href="/">Open the app</a>
      </header>

      <main>
        <h1>{escape(seo.TAGLINE)}</h1>
        <p class="lede">{escape(seo.SUMMARY)}</p>

        <h2>What it does</h2>
{features}

        <h2>Running it</h2>
        <p>
          Four commands. The first build downloads the model, which takes a
          while and happens once. After that the app answers on port 8000, and
          the database and the audio both live in <code>./data</code>. Copy that
          directory and you have backed up everything.
        </p>
        <pre><code>git clone {escape(seo.REPO_URL)}.git
cd oneread
cp .env.example .env
docker compose up --build -d</code></pre>

        <h2>Questions</h2>
{faq}
      </main>

      <footer>
        <p>
          Source and issues on <a href="{escape(seo.REPO_URL)}">GitHub</a>.
          Speech from <a href="{escape(seo.MODEL_URL)}">Supertonic 3</a>, run
          locally as ONNX. Machine-readable summary at
          <a href="/llms.txt">/llms.txt</a>.
        </p>
      </footer>
    </div>

    <script type="application/ld+json">{_structured_data(settings)}</script>
  </body>
</html>
"""


# --- crawler files ------------------------------------------------------------


@router.get("/robots.txt")
def robots(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    key = ("robots", settings.public_url, settings.public_site)
    return Response(
        _cached(key, lambda: _robots(settings)),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _robots(settings: Settings) -> str:
    if not settings.public_site:
        # The default, and the right one for the instance on somebody's laptop.
        return (
            "# This instance is private. Set ONEREAD_PUBLIC_SITE=true on an\n"
            "# instance that is meant to be found.\n"
            "User-agent: *\n"
            "Disallow: /\n"
        )

    disallow = "\n".join(f"Disallow: {path}" for path in PRIVATE_PATHS)
    blocks = [
        f"User-agent: *\nAllow: /\n{disallow}",
        # Spelled out so the assistants that read a bare `*` conservatively still
        # index the one page there is. Same rules as everyone else.
        *(f"User-agent: {agent}\nAllow: /\n{disallow}" for agent in AI_AGENTS),
    ]
    body = "\n\n".join(blocks)
    if settings.public_url:
        body += f"\n\nSitemap: {_absolute(settings, '/sitemap.xml')}"
    return body + "\n"


@router.get("/sitemap.xml")
def sitemap(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    if not settings.public_site or not settings.public_url:
        # A sitemap without an absolute origin is invalid, and one for a private
        # instance is an invitation. Neither is worth serving.
        return Response(status_code=404)
    key = ("sitemap", settings.public_url)
    return Response(
        _cached(key, lambda: _sitemap(settings)),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _sitemap(settings: Settings) -> str:
    pages = [(_absolute(settings, "/"), "0.8"), (_absolute(settings, "/about"), "1.0")]
    entries = "\n".join(
        f"""  <url>
    <loc>{escape(url)}</loc>
    <lastmod>{seo.CONTENT_UPDATED}</lastmod>
    <priority>{priority}</priority>
  </url>"""
        for url, priority in pages
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""


# --- llms.txt -----------------------------------------------------------------


@router.get("/llms.txt")
def llms(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    """The short form: what this is, and where the long form lives.

    The llms.txt convention — an index in Markdown at a fixed path — is what an
    agent fetches when it wants the project's own account of itself instead of
    whatever it can reconstruct from a rendered page.
    """
    key = ("llms", settings.public_url)
    return Response(
        _cached(key, lambda: _llms(settings)),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _llms(settings: Settings) -> str:
    return f"""# {seo.NAME}

> {seo.SUMMARY}

Self-hosted, open source, no per-character billing. Speech is produced on the
host by Supertonic 3 running under ONNX Runtime; the model ships inside the
Docker image. Every reading comes with an SRT whose cue times are derived from
the audio samples actually written, so subtitles and audio match exactly.

## Docs

- [About and FAQ]({_absolute(settings, '/about')}): what it does, how to run it,
  the answers to the usual questions.
- [Full text]({_absolute(settings, '/llms-full.txt')}): every feature and every
  FAQ answer in one file.
- [Source]({seo.REPO_URL}): code, issues, installation.
- [Speech model]({seo.MODEL_URL}): Supertonic 3.

## Notes

- The app itself, at `/`, is behind a sign-in and holds private per-user
  libraries. There is nothing to crawl there.
- Not an API service: it is software you run. There is no hosted endpoint to
  call and no key to obtain.
"""


@router.get("/llms-full.txt")
def llms_full(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    key = ("llms-full", settings.public_url)
    return Response(
        _cached(key, lambda: _llms_full(settings)),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _llms_full(settings: Settings) -> str:
    features = "\n\n".join(f"### {heading}\n\n{body}" for heading, body in seo.FEATURES)
    faq = "\n\n".join(f"### {question}\n\n{answer}" for question, answer in seo.FAQ)
    alternatives = ", ".join(seo.ALTERNATIVE_TO)
    return f"""# {seo.NAME}: {seo.TAGLINE}

> {seo.SUMMARY}

- Home: {_absolute(settings, '/')}
- About: {_absolute(settings, '/about')}
- Source: {seo.REPO_URL}
- Speech model: {seo.MODEL_URL}
- Licence and cost: open source, free, self-hosted. No per-character billing.
- Sits in the same space as: {alternatives}.
- Last updated: {seo.CONTENT_UPDATED}

## Features

{features}

## Frequently asked questions

{faq}

## Installation

```sh
git clone {seo.REPO_URL}.git
cd oneread
cp .env.example .env
docker compose up --build -d
```

The first build downloads the model, which is around 385 MB. The app then
answers on port 8000. The database and the generated audio live in `./data`;
copying that directory backs up everything. Upgrading in place is supported:
missing columns get added to the existing SQLite file at startup.

## What it is not

- Not a hosted API. There is no endpoint to call and no key to obtain; it is
  software you run yourself.
- Not an OCR tool. A scanned, image-only PDF is refused rather than read as
  silence.
- Not a cloud service. Nothing in the synthesis path leaves the host.
"""
