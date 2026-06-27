"""FastAPI entrypoint. Mounts the API and serves the dashboard SPA."""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import auth, txns, analytics, bots, telegram, settings as settings_router

app = FastAPI(title=settings.app_name)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(txns.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
app.include_router(bots.router, prefix=API_PREFIX)
app.include_router(settings_router.router, prefix=API_PREFIX)
app.include_router(telegram.router)  # webhook lives at /tg/{routing_id}


@app.get("/health")
def health():
    return {"ok": True}


@app.on_event("startup")
def _startup():
    init_db()


# --- serve the frontend -----------------------------------------------------
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))
