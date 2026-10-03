from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SIGNUP_CODE_LENGTH = 16


class Settings(BaseSettings):
    database_url: str = "sqlite:///./finode.db"
    database_echo: bool = True
    supabase_url: str | None = None
    supabase_audience: str = "authenticated"
    supabase_anon_key: str | None = None
    cookie_secure: bool = False
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
    def signup_enabled(self) -> bool:
        """Sign-up is closed unless an invite code and the admin key are configured."""
        return bool(self.signup_code and self.supabase_service_role_key and self.supabase_url)

    # .env is shared with docker compose, so keys meant for compose are ignored
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_", extra="ignore")


settings = Settings()
