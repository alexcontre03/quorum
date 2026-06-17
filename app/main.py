from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config.runtime_settings import load_environment

load_environment()

from app.api.routes import router as api_router

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
ASSETS_DIR = STATIC_DIR / "assets"
INDEX_FILE = STATIC_DIR / "index.html"

app = FastAPI(
    title="Meeting Agent Lab",
    summary="JSON-defined meeting agents with a local Ollama-backed task proposal agent.",
    version="0.1.0",
)

app.include_router(api_router)
if ASSETS_DIR.exists():
    app.mount("/static/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


def _serve_spa() -> HTMLResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(
            status_code=503,
            detail="Frontend no compilado. Ejecuta 'npm run build' en frontend/.",
        )
    return HTMLResponse(
        content=INDEX_FILE.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return _serve_spa()


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> HTMLResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    root_file = STATIC_DIR / full_path
    if full_path and root_file.is_file():
        return FileResponse(root_file)  # type: ignore[return-value]
    return _serve_spa()


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
