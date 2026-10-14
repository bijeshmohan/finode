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
    # What one person may hold (0 = no limit): so nobody can fill the shared database.
    max_accounts: int = Field(default=500, ge=0)
    max_transactions: int = Field(default=100_000, ge=0)
    max_transactions_per_day: int = Field(default=1_000, ge=0)
    max_postings_per_transaction: int = Field(default=100, ge=0)
    max_own_assets: int = Field(default=50, ge=0)
    max_restore_mb: int = Field(default=25, ge=1)
    # Failed sign-ins, and sign-up attempts, allowed per address in the window (0 = no limit).
    login_attempts: int = Field(default=10, ge=0)
    signup_attempts: int = Field(default=5, ge=0)
    attempt_window_minutes: int = Field(default=15, ge=1)
    # The time zone "today" is read in (an IANA name such as Asia/Kolkata); the server's own clock when empty.
    timezone: str | None = None
    # Interactive API docs (/docs, /redoc, /openapi.json) are public when on; off unless you are developing.
    api_docs: bool = False
    # "Forgot password": needs email sending set up in Supabase (custom SMTP) and its recovery email
    # template pointing at /reset (see README). Off until then, so nobody is offered a link that sends nothing.
    password_reset: bool = False
    reset_attempts: int = Field(default=5, ge=0)
    # A test with invited people: shows the notice at sign-up (to be accepted) and under Profile.
    test_notice: bool = False
    # Where "Send feedback" (Profile) writes to; the link is hidden when empty.
    feedback_email: str | None = None
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

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, v: str | None) -> str | None:
        if not v:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"FINODE_TIMEZONE must be a time zone name such as Asia/Kolkata, not {v!r}")
        return v

    @property
    def can_delete_logins(self) -> bool:
        """Removing a person's sign-in needs Supabase's admin API (the service key)."""
        return bool(self.supabase_service_role_key and self.supabase_url)

    @property
    def reset_enabled(self) -> bool:
        return bool(self.password_reset and self.supabase_url and self.supabase_anon_key)

    @property
    def signup_enabled(self) -> bool:
        """Sign-up is closed unless an invite code and the admin key are configured."""
        return bool(self.signup_code and self.supabase_service_role_key and self.supabase_url)

    # .env is shared with docker compose, so keys meant for compose are ignored
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_", extra="ignore")


settings = Settings()
