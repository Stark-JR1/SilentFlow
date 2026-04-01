import os
from functools import lru_cache

from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    supabase_url: HttpUrl = Field(validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_ANON_KEY", "SUPABASE_KEY")
    )
    supabase_service_role_key: str = Field(
        validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    app_secret_key: str = "change-me-in-production"
    app_env: str = "development"
    app_port: int = 8000
    app_host: str = "0.0.0.0"

    jwt_secret_key: str = "change-me-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days

    # Intelligence features
    intelligence_enabled: bool = True
    learning_enabled: bool = True
    profile_enabled: bool = True
    alerts_enabled: bool = True

@lru_cache
def get_settings() -> Settings:
    has_required_env = (
        bool(os.getenv("SUPABASE_URL"))
        and bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        and bool(os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY"))
    )
    if not os.path.exists(".env") and not has_required_env:
        raise RuntimeError(
            "Arquivo .env nao encontrado. Crie-o a partir de .env.example "
            "e preencha SUPABASE_URL, SUPABASE_ANON_KEY e SUPABASE_SERVICE_ROLE_KEY."
        )
    return Settings()


