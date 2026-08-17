"""App factory: wiring, lifespan, and serving the built frontend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessionRefreshMiddleware
from .config import Settings, get_settings
from .db import get_engine, init_db
from .routers import auth as auth_router
from .routers import entries as entries_router
from .routers import meta as meta_router
from .routers import preview as preview_router
from .routers import renditions as rendition_router
from .routers import uploads as upload_router
from .security import SecurityHeadersMiddleware
from .worker import get_worker

logging.basicConfig(
    level=logging.INFO,
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

    # The segment list for a long document is a few hundred kilobytes of text.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.add_middleware(SessionRefreshMiddleware, settings=settings)
    if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _install_error_handlers(app)

    app.include_router(auth_router.router)
    app.include_router(entries_router.router)
    app.include_router(meta_router.router)
    app.include_router(rendition_router.router)
    app.include_router(preview_router.router)
    app.include_router(upload_router.router)

    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the Vite build, with every unknown path falling back to index.html."""
    index = static_dir / "index.html"
    if not index.is_file():
        log.warning("no frontend build at %s; serving the API only", static_dir)
        return

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (static_dir / path).resolve()
        if path and static_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


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
