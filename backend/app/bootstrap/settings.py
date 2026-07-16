from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DA_", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://da:da@127.0.0.1:55432/da"
    artifact_root: Path = Path("data/artifacts")
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173",)
    timezone: str = "Asia/Shanghai"
    authentication_enabled: bool = False
    worker_stale_after_seconds: int = Field(default=120, ge=30)
