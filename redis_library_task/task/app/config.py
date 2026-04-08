from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://library_user:library_pass@localhost:5433/library_db"
    redis_url: str = "redis://redis:6379/0"          # redis имя сервиса

    app_host: str = "0.0.0.0"
    app_port: int = 8000

settings = Settings()