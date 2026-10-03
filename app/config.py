from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./finode.db"
    database_echo: bool = True
    supabase_url: str | None = None
    supabase_audience: str = "authenticated"
    supabase_anon_key: str | None = None
    cookie_secure: bool = False

    # .env is shared with docker compose, so keys meant for compose are ignored
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_", extra="ignore")


settings = Settings()
