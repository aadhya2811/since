from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .market.service import MarketService, build_news_chain, build_provider
from .routers import auth, briefing, misc, watchlists

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per request is noise, not signal
logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_app(market: MarketService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        svc = market or MarketService(build_provider(settings), settings, build_news_chain(settings))
        app.state.market = svc
        svc.start()
        logging.getLogger("since").info(
            "Since is up · prices: %s (fallback: %s) · news: %s · db: %s",
            settings.provider, settings.fallback_provider or "none", settings.news_provider or "off", settings.database_url,
        )
        try:
            yield
        finally:
            await svc.stop()

    app = FastAPI(title="Since — a watchlist that opens as a briefing", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_origin_regex=r"https://.*\.(vercel\.app|onrender\.com|netlify\.app)",
        allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
    )
    for r in (auth.router, watchlists.router, briefing.router, misc.router):
        app.include_router(r, prefix="/api")

    # Serve the built frontend if it exists, so one process = the whole app.
    dist = Path(settings.static_dir) if settings.static_dir else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = dist / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
