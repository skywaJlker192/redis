"""
Конфигурация проекта из переменных окружения.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Postgres ───────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://library_user:library_pass@localhost:5432/library_db"

    # ── App ────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000


settings = Settings()
