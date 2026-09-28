"""Configuration loaded once when the API starts."""

from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/clew.sqlite3")
    base_url: str = "http://localhost:8000"
    api_key: str | None = None
    allow_unauthenticated_local: bool = False

    def __post_init__(self) -> None:
        base_url = self.base_url.rstrip("/")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            validated = TypeAdapter(HttpUrl).validate_python(base_url)
        except (ValueError, ValidationError) as exc:
            raise ValueError("CLEW_BASE_URL is invalid") from exc

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
            raise ValueError("CLEW_BASE_URL must be an HTTP(S) origin")

        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not local and parsed.scheme != "https":
            raise ValueError("Public CLEW_BASE_URL must use HTTPS")
        if self.allow_unauthenticated_local and not local:
            raise ValueError("CLEW_ALLOW_UNAUTHENTICATED_LOCAL requires a local CLEW_BASE_URL")
        if self.api_key is not None and len(self.api_key) < 32:
            raise ValueError("CLEW_API_KEY must be at least 32 characters")
        if not local and self.api_key is None:
            raise ValueError("Public deployments need a 32-character CLEW_API_KEY")

        object.__setattr__(self, "base_url", str(validated).rstrip("/"))

    @classmethod
    def from_environment(cls) -> "Settings":
        local_development = os.getenv("CLEW_ALLOW_UNAUTHENTICATED_LOCAL", "false").lower()
        if local_development not in {"true", "false"}:
            raise ValueError("CLEW_ALLOW_UNAUTHENTICATED_LOCAL must be true or false")
        return cls(
            database_path=Path(
                os.getenv("CLEW_DATABASE_PATH")
                or os.getenv("SHORTURL_DATABASE_PATH")
                or "data/clew.sqlite3"
            ),
            base_url=(
                os.getenv("CLEW_BASE_URL")
                or os.getenv("SHORTURL_BASE_URL")
                or "http://localhost:8000"
            ),
            api_key=os.getenv("CLEW_API_KEY") or os.getenv("SHORTURL_API_KEY") or None,
            allow_unauthenticated_local=local_development == "true",
        )
