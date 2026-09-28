"""HTTP API for creating, following, and inspecting short links."""

import hmac
import logging
import sqlite3

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator

from shorturl.settings import Settings
from shorturl.storage import CodeExhaustedError, SQLiteStore


logger = logging.getLogger(__name__)


class LinkRequest(BaseModel):
    url: HttpUrl = Field(max_length=2048)

    @field_validator("url", mode="before")
    @classmethod
    def reject_unsafe_input(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("URL must be a string")
        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("URL cannot contain whitespace or control characters")
        return value

    @field_validator("url")
    @classmethod
    def reject_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("URL cannot contain credentials")
        if len(str(value)) > 2048:
            raise ValueError("URL cannot exceed 2048 characters")
        return value


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = SQLiteStore(settings.database_path)
    store.initialize()
    app = FastAPI(title="ShortURL", version="0.1.0")

    def authorize(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key is not None and (
            x_api_key is None
            or not hmac.compare_digest(x_api_key.encode("utf-8"), settings.api_key.encode("utf-8"))
        ):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request, exception: sqlite3.Error) -> JSONResponse:
        logger.error("Storage error", exc_info=exception)
        return JSONResponse(status_code=503, content={"detail": "Storage temporarily unavailable"})

    @app.exception_handler(CodeExhaustedError)
    async def code_exhausted(_request, exception: CodeExhaustedError) -> JSONResponse:
        logger.error("Could not allocate short code", exc_info=exception)
        return JSONResponse(status_code=503, content={"detail": "Could not create link"})

    @app.get("/healthz")
    def health() -> dict[str, str]:
        if not store.healthy():
            raise HTTPException(status_code=503, detail="Storage temporarily unavailable")
        return {"status": "ok"}

    @app.post("/api/links", status_code=201, dependencies=[Depends(authorize)])
    def create_link(payload: LinkRequest, response: Response) -> dict:
        link = store.create_link(str(payload.url))
        link["short_url"] = f"{settings.base_url}/{link['code']}"
        response.headers["Location"] = link["short_url"]
        response.headers["Cache-Control"] = "no-store"
        return link

    @app.get("/api/links/{code}/stats", dependencies=[Depends(authorize)])
    def link_stats(code: str, response: Response) -> dict:
        stats = store.stats_for(code)
        if stats is None:
            raise HTTPException(status_code=404, detail="Link not found")
        stats["short_url"] = f"{settings.base_url}/{code}"
        response.headers["Cache-Control"] = "no-store"
        return stats

    @app.head("/{code}")
    def inspect_redirect(code: str) -> RedirectResponse:
        destination = store.destination_for(code)
        if destination is None:
            raise HTTPException(status_code=404, detail="Link not found")
        return RedirectResponse(destination, status_code=302, headers={"Cache-Control": "no-store"})

    @app.get("/{code}")
    def follow_link(code: str) -> RedirectResponse:
        destination = store.record_click(code)
        if destination is None:
            raise HTTPException(status_code=404, detail="Link not found")
        return RedirectResponse(destination, status_code=302, headers={"Cache-Control": "no-store"})

    return app


app = create_app()
