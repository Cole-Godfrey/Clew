"""Configuration loaded once when the API starts."""

from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/shorturl.sqlite3")
    base_url: str = "http://localhost:8000"
    api_key: str | None = None

    def __post_init__(self) -> None:
        base_url = self.base_url.rstrip("/")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            validated = TypeAdapter(HttpUrl).validate_python(base_url)
        except (ValueError, ValidationError) as exc:
            raise ValueError("SHORTURL_BASE_URL is invalid") from exc

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or port == 0
        ):
            raise ValueError("SHORTURL_BASE_URL must be an HTTP(S) origin")

        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not local and parsed.scheme != "https":
            raise ValueError("Public SHORTURL_BASE_URL must use HTTPS")
        if not local and (self.api_key is None or len(self.api_key) < 32):
            raise ValueError("Public deployments need a 32-character SHORTURL_API_KEY")

        object.__setattr__(self, "base_url", str(validated).rstrip("/"))

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("SHORTURL_DATABASE_PATH", "data/shorturl.sqlite3")),
            base_url=os.getenv("SHORTURL_BASE_URL", "http://localhost:8000"),
            api_key=os.getenv("SHORTURL_API_KEY") or None,
        )
