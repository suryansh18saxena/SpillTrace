"""Application configuration.

Every setting is read from the environment.  Secrets have **no defaults**: a missing
secret raises at startup rather than silently running with a well-known value
(NFR-007, CON-004).
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]

SatelliteProvider = Literal["fixture", "cdse"]
EnvironmentProvider = Literal["synthetic", "cmems"]
AISProviderName = Literal["synthetic", "aisstream"]
DriftEngineOption = Literal["analytical", "openoil"]
SegmentationOption = Literal["analytical", "unet"]
StorageProvider = Literal["s3", "local"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    environment: Environment = Field(default="development", alias="SPILLTRACE_ENV")
    log_level: str = Field(default="INFO", alias="SPILLTRACE_LOG_LEVEL")
    version: str = Field(default="0.1.0", alias="SPILLTRACE_VERSION")
    role: str = Field(default="api", alias="SPILLTRACE_ROLE")
    git_sha: str = Field(default="unknown", alias="SPILLTRACE_GIT_SHA")

    # ---------------------------------------------------------------- security
    secret_key: str = Field(alias="SPILLTRACE_SECRET_KEY", min_length=16)
    access_token_ttl_seconds: int = Field(
        default=900, alias="SPILLTRACE_ACCESS_TOKEN_TTL_SECONDS", ge=60, le=86_400
    )
    refresh_token_ttl_seconds: int = Field(
        default=604_800, alias="SPILLTRACE_REFRESH_TOKEN_TTL_SECONDS", ge=3600
    )
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="SPILLTRACE_CORS_ORIGINS")

    # ---------------------------------------------------------------- database
    postgres_user: str = Field(default="spilltrace", alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="spilltrace", alias="POSTGRES_DB")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    db_pool_size: int = Field(default=10, alias="SPILLTRACE_DB_POOL_SIZE")
    db_echo: bool = Field(default=False, alias="SPILLTRACE_DB_ECHO")

    # ---------------------------------------------------------------- redis
    redis_host: str = Field(default="redis", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    # ---------------------------------------------------------------- storage
    s3_endpoint_url: str = Field(default="http://minio:9000", alias="S3_ENDPOINT_URL")
    s3_public_endpoint_url: str = Field(
        default="http://localhost:9000", alias="S3_PUBLIC_ENDPOINT_URL"
    )
    s3_access_key: str = Field(default="spilltrace", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="spilltrace", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    local_storage_root: str = Field(default="/app/data/artifacts", alias="SPILLTRACE_LOCAL_STORAGE")

    # ---------------------------------------------------------------- adapters
    satellite_provider: SatelliteProvider = Field(
        default="fixture", alias="SPILLTRACE_SATELLITE_PROVIDER"
    )
    environment_provider: EnvironmentProvider = Field(
        default="synthetic", alias="SPILLTRACE_ENVIRONMENT_PROVIDER"
    )
    ais_provider: AISProviderName = Field(default="synthetic", alias="SPILLTRACE_AIS_PROVIDER")
    drift_engine: DriftEngineOption = Field(default="analytical", alias="SPILLTRACE_DRIFT_ENGINE")
    segmentation_model: SegmentationOption = Field(
        default="analytical", alias="SPILLTRACE_SEGMENTATION_MODEL"
    )
    storage_provider: StorageProvider = Field(default="s3", alias="SPILLTRACE_STORAGE_PROVIDER")

    # ---------------------------------------------------------------- credentials
    # Server-side only.  These names must never appear in frontend code (CON-004).
    cdse_username: str = Field(default="", alias="CDSE_USERNAME")
    cdse_password: str = Field(default="", alias="CDSE_PASSWORD")
    cdse_client_id: str = Field(default="cdse-public", alias="CDSE_CLIENT_ID")
    cmems_username: str = Field(default="", alias="COPERNICUSMARINE_SERVICE_USERNAME")
    cmems_password: str = Field(default="", alias="COPERNICUSMARINE_SERVICE_PASSWORD")
    aisstream_api_key: str = Field(default="", alias="AISSTREAM_API_KEY")

    # ---------------------------------------------------------------- limits
    max_aoi_km2: float = Field(default=250_000.0, alias="SPILLTRACE_MAX_AOI_KM2", gt=0)
    max_time_window_days: int = Field(
        default=30, alias="SPILLTRACE_MAX_TIME_WINDOW_DAYS", ge=1, le=365
    )
    job_max_attempts: int = Field(default=3, alias="SPILLTRACE_JOB_MAX_ATTEMPTS", ge=1, le=10)
    worker_concurrency: int = Field(default=2, alias="SPILLTRACE_WORKER_CONCURRENCY", ge=1, le=32)
    job_claim_ttl_seconds: int = Field(default=300, alias="SPILLTRACE_JOB_CLAIM_TTL", ge=30)
    api_page_size_max: int = Field(default=200, alias="SPILLTRACE_PAGE_SIZE_MAX")

    # ---------------------------------------------------------------- validators
    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        if value.strip().lower().startswith("change-me"):
            raise ValueError(
                "SPILLTRACE_SECRET_KEY is still the placeholder. "
                "Generate one with: openssl rand -hex 32"
            )
        return value

    @model_validator(mode="after")
    def _production_hardening(self) -> Settings:
        if self.environment == "production":
            if len(self.secret_key) < 32:
                raise ValueError("SPILLTRACE_SECRET_KEY must be >= 32 chars in production")
            if self.postgres_password.strip().lower().startswith("change-me"):
                raise ValueError("POSTGRES_PASSWORD is still the placeholder")
            if self.db_echo:
                raise ValueError("SPILLTRACE_DB_ECHO must be off in production")
        return self

    # ---------------------------------------------------------------- derived
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Alembic and other synchronous tooling."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def provider_modes(self) -> dict[str, dict[str, str]]:
        """Which implementation backs each port, and whether it produces real data.

        Rendered by the Admin page (UI-010) so an analyst can always tell at a glance
        whether what they are looking at came from a real observation.
        """
        real = {"cdse", "cmems", "aisstream", "openoil", "unet"}
        selected = {
            "satellite": self.satellite_provider,
            "environment": self.environment_provider,
            "ais": self.ais_provider,
            "drift": self.drift_engine,
            "segmentation": self.segmentation_model,
        }
        return {
            port: {
                "implementation": impl,
                "mode": "REAL" if impl in real else "SYNTHETIC",
            }
            for port, impl in selected.items()
        }

    def missing_credentials(self) -> list[str]:
        """Credentials required by the currently selected real adapters but not set."""
        missing: list[str] = []
        if self.satellite_provider == "cdse" and not (self.cdse_username and self.cdse_password):
            missing.append("CDSE_USERNAME/CDSE_PASSWORD")
        if self.environment_provider == "cmems" and not (
            self.cmems_username and self.cmems_password
        ):
            missing.append("COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD")
        if self.ais_provider == "aisstream" and not self.aisstream_api_key:
            missing.append("AISSTREAM_API_KEY")
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def generate_secret_key() -> str:
    """Convenience for tooling/tests — never used to supply a runtime default."""
    return secrets.token_hex(32)


__all__ = ["PostgresDsn", "Settings", "generate_secret_key", "get_settings"]
