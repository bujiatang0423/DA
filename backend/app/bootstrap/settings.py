from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.bootstrap.security import validate_security


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DA_", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    provider_mode: Literal["production", "fake"] = "production"
    research_provider_factory: str | None = None
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
        repr=False,
    )
    cninfo_web_fetch_enabled: bool | None = None
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://da:da@127.0.0.1:55432/da"
    artifact_root: Path = Path("data/artifacts")
    pit_approval_secret: str | None = None
    legacy_import_root: Path = Path("data/imports")
    legacy_import_source_roots: tuple[Path, ...] = (Path("data/legacy-sources"),)
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173",)
    timezone: str = "Asia/Shanghai"
    authentication_enabled: bool = False
    worker_stale_after_seconds: int = Field(default=120, ge=30)

    @model_validator(mode="after")
    def validate_startup_security(self) -> "Settings":
        validate_security(
            bind_host=self.bind_host,
            authentication_enabled=self.authentication_enabled,
            allowed_origins=self.allowed_origins,
        )
        return self
