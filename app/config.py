from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SIGNUP_CODE_LENGTH = 16


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
    # How often (in minutes) due recurring transactions are recorded in the background; 0 turns it off.
    recurring_interval_minutes: int = Field(default=15, ge=0)
    # Most people (profiles, you included) who may have an account; sign-up closes when it is reached. 0 = no limit.
    max_users: int = Field(default=10, ge=0)
    supabase_service_role_key: str | None = None
    signup_code: str | None = None

    @field_validator("signup_code")
    @classmethod
    def signup_code_must_be_strong(cls, v: str | None) -> str | None:
        if not v:
            return None
        if len(v) < MIN_SIGNUP_CODE_LENGTH:
            raise ValueError(
                f"FINODE_SIGNUP_CODE must be at least {MIN_SIGNUP_CODE_LENGTH} characters "
                "(generate one with: openssl rand -base64 24)"
            )
        return v

    @property
    def can_delete_logins(self) -> bool:
        """Removing a person's sign-in needs Supabase's admin API (the service key)."""
        return bool(self.supabase_service_role_key and self.supabase_url)

    @property
    def signup_enabled(self) -> bool:
        """Sign-up is closed unless an invite code and the admin key are configured."""
        return bool(self.signup_code and self.supabase_service_role_key and self.supabase_url)

    # .env is shared with docker compose, so keys meant for compose are ignored
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_", extra="ignore")


settings = Settings()
