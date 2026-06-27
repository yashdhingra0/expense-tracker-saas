"""Application settings, loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./expense_saas.db"
    secret_key: str = "dev-only-change-me"
    token_enc_key: str = ""          # Fernet key; auto-generated in dev if blank
    dev_allow_unverified_tokens: bool = True
    public_base_url: str = "http://localhost:8000"
    app_name: str = "Expense Tracker"


settings = Settings()
