from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./finode.db"
    database_echo: bool = True
    supabase_url: str | None = None
    supabase_audience: str = "authenticated"
    supabase_anon_key: str | None = None
    cookie_secure: bool = False
    # Hard ceiling on account depth; users can set lower limits but never exceed this.
    max_account_depth: int = Field(default=20, ge=1)
    # MCP calls allowed per token per minute (per app process).
    mcp_rate_limit: int = Field(default=120, ge=1)

    # .env is shared with docker compose, so keys meant for compose are ignored
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_", extra="ignore")


settings = Settings()
