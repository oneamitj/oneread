"""App factory: wiring, lifespan, and serving the built frontend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessionRefreshMiddleware
from .config import Settings, get_settings
from .db import get_engine, init_db
from .routers import auth as auth_router
from .routers import entries as entries_router
from .routers import meta as meta_router
from .routers import preview as preview_router
from .routers import renditions as rendition_router
from .routers import site as site_router
from .routers import uploads as upload_router
from .security import BodyLimitMiddleware, SecurityHeadersMiddleware
from .visits import get_counter, record_page_view
from .worker import get_worker

# ONEREAD_LOG_LEVEL, INFO here and ERROR in production, where the request log
# is off on both nginx and uvicorn and this is the only thing still writing.
logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("oneread")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    init_db(get_engine())

    worker = get_worker()
    worker.start()
    worker.requeue_unfinished()

    counter = get_counter()
    if settings.count_visits:
        counter.start()

    # A file read but never turned into an entry is nobody's, and a crash
    # mid-edit leaves one behind. Clear the old ones on the way up.
    from .db import session_scope

    with session_scope() as session:
        dropped = upload_router.sweep(session)
    if dropped:
        log.info("swept %s unclaimed upload(s)", dropped)

    if settings.preload_model:
        import anyio

        from .tts_engine import get_engine as get_tts

        await anyio.to_thread.run_sync(get_tts().load)

    try:
        yield
    finally:
        log.info("draining synthesis queue")
        worker.stop(timeout=60.0)
        # After the worker, so the drain is inside the window this writes out.
        counter.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="oneread",
        version="0.1.0",
        summary="A private library of things you'd rather listen to.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    # `add_middleware` prepends, so these run in reverse: CORS, TrustedHost,
    # SessionRefresh, SecurityHeaders, BodyLimit, GZip, then the routes.

    # The segment list for a long document is a few hundred kilobytes of text.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # Ahead of every route and of GZip, which is what matters: an oversized body
    # is turned away before anything downstream has read it. The layers above
    # this one all read headers only.
    app.add_middleware(
        BodyLimitMiddleware,
        limit=settings.max_request_bytes,
        # Uploads have their own, larger ceiling; the slack is for the multipart
        # wrapper around the file rather than the file itself.
        upload_limit=settings.max_upload_bytes + 1024 * 1024,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.add_middleware(SessionRefreshMiddleware, settings=settings)
    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.cors_origins:
        # Named origins only — the config refuses "*", because with credentials
        # on, Starlette answers a wildcard by reflecting whichever origin asked.
        # The header list is spelled out for the same reason: "*" on a preflight
        # approves `X-Requested-With`, which is the whole CSRF guard.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-Requested-With"],
        )

    _install_error_handlers(app)

    app.include_router(auth_router.router)
    app.include_router(entries_router.router)
    app.include_router(meta_router.router)
    app.include_router(rendition_router.router)
    app.include_router(preview_router.router)
    app.include_router(upload_router.router)
    # Before the frontend, whose catch-all would otherwise swallow /about,
    # /robots.txt and the rest and answer them with the React shell.
    app.include_router(site_router.router)

    # After every router and before the frontend, so it catches what no route
    # claimed and nothing else ever sees an /api/ path.
    _seal_api(app)
    _mount_frontend(app, settings)
    return app


def _seal_api(app: FastAPI) -> None:
    """Answer any unclaimed /api/ path in JSON, whatever the method.

    Two things would otherwise handle these, and both lie. The frontend's
    catch-all below returns the React shell with a 200, so a caller expecting
    `{"message": "..."}` parses HTML and reports whatever its most generic
    sentence is — which is how a proxy sending `POST /api/uploads` to
    `/api/uploads/` looked for a while like a file that couldn't be read. And
    starlette's `redirect_slashes` answers the other direction with a 307,
    quietly making the slash optional on routes where it isn't.

    Registered for every method rather than GET alone, so neither of those can
    reach an /api/ path by any route. It costs the 405s, which said more about
    the routing table than a stranger needed anyway.
    """

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def unknown_endpoint(rest: str) -> Response:
        raise HTTPException(404, "No such endpoint.")


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the Vite build, with every unknown path falling back to index.html."""
    static_dir = settings.static_dir
    index = static_dir / "index.html"
    if not index.is_file():
        log.warning("no frontend build at %s; serving the API only", static_dir)
        return

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    shell = _shell(index, settings)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        candidate = (static_dir / path).resolve()
        if path and static_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        # Everything with a route of its own — the API, /about, robots.txt,
        # /healthz, /assets — was matched before this, and the branch above
        # takes the remaining files. So reaching here is already "somebody
        # loaded a page", and the counter needs no allowlist of its own to keep
        # in step with the routers.
        if settings.count_visits:
            record_page_view(request, path)
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})


def _shell(index: Path, settings: Settings) -> str:
    """index.html with this instance's own address written into it.

    The Vite build is a static file and cannot know what name it will be served
    under, so the canonical link and the absolute URLs that link previews need
    are filled in here, once, at startup. An instance with no
    ONEREAD_PUBLIC_URL keeps the relative tags the build shipped with, and one
    that isn't meant to be found says so in a robots meta as well as in
    robots.txt, since the two are read by different things at different times.
    """
    html = index.read_text(encoding="utf-8")
    head: list[str] = []

    if settings.public_url:
        origin = settings.public_url
        html = html.replace('content="/og-image.png"', f'content="{origin}/og-image.png"')
        head.append(f'<link rel="canonical" href="{origin}/" />')
        head.append(f'<meta property="og:url" content="{origin}/" />')

    head.append(
        '<meta name="robots" content="index, follow, max-image-preview:large" />'
        if settings.public_site
        else '<meta name="robots" content="noindex, nofollow" />'
    )

    return html.replace("</head>", "    " + "\n    ".join(head) + "\n  </head>", 1)


def _install_error_handlers(app: FastAPI) -> None:
    """One error shape for the frontend: `{"message": "..."}`."""

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
        return JSONResponse(
            {"message": detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic prefixes its messages with "Value error, ". Readers don't need that.
        messages = [
            str(error.get("msg", "")).removeprefix("Value error, ")
            for error in exc.errors()
        ]
        message = next((m for m in messages if m), "Check the form and try again.")
        return JSONResponse({"message": message}, status_code=422)


app = create_app()
