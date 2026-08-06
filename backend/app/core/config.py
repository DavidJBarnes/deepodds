from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    DATABASE_URL_SYNC: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"

    # ----- Verbatim ---------------------------------------------------------
    # Verbatim is a SEPARATE database on the same RDS instance, not a schema in
    # the trading DB — its 11 tables and its Alembic history stay fully isolated
    # so a Verbatim migration can never touch trading data.
    #
    # Empty by default so local dev and the test suite run without it; every
    # Verbatim route 503s when unconfigured rather than erroring at import time.
    VERBATIM_DATABASE_URL: str = ""
    # Shared secret for the GPU worker (NOT a user JWT). The worker holds no AWS
    # or DB credentials — it authenticates with this and nothing else.
    VERBATIM_WORKER_TOKEN: str = ""
    VERBATIM_CLIPS_BUCKET: str = ""
    VERBATIM_S3_REGION: str = "us-west-2"
    # Presigned-URL lifetime. Long enough for a slow home upload, short enough
    # that a leaked URL is not a standing grant.
    VERBATIM_CLIP_URL_TTL_S: int = 900

    @property
    def verbatim_enabled(self) -> bool:
        return bool(self.VERBATIM_DATABASE_URL)

    @property
    def VERBATIM_DATABASE_URL_SYNC(self) -> str:
        """Sync (psycopg2) form of the Verbatim URL, for Alembic.

        Derived rather than configured: two URLs that must agree but are set
        independently is exactly how a migration ends up pointed at the wrong
        database.
        """
        return self.VERBATIM_DATABASE_URL.replace("+asyncpg", "")


settings = Settings()
