from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./finode.db"
    database_echo: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINODE_")


settings = Settings()
