"""Runtime configuration. Everything is overridable via environment variables
(prefix SINCE_), so the same image runs in dev, tests and production."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SINCE_", env_file=".env", extra="ignore")

    # --- storage ---------------------------------------------------------
    database_url: str = "sqlite:///./since.db"

    # --- market data -----------------------------------------------------
    # "yahoo" hits Yahoo Finance (free, ~15 min delayed for NSE).
    # "simulated" is a deterministic in-process feed: no network, same data
    # every run. Tests use it; the demo falls back to it if Yahoo is down.
    provider: str = "yahoo"
    # A provider chain: primary first. Failure of the primary trips a circuit
    # breaker and traffic moves to the next one until the breaker half-opens.
    fallback_provider: str | None = "simulated"
    quote_refresh_open_seconds: int = 60       # while NSE is trading
    quote_refresh_closed_seconds: int = 900    # after close: catch late prints
    bars_refresh_hours: int = 12
    provider_timeout_seconds: float = 8.0
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: int = 90
    scheduler_enabled: bool = True
    # Keep daily bars for the whole static universe (~60 names) so the Market
    # page can rank sectors and movers. One request per symbol per day.
    universe_scan: bool = True

    # --- news ------------------------------------------------------------
    news_provider: str = "google"          # "google" | "simulated" | "" (off)
    news_fallback_provider: str | None = "simulated"
    news_refresh_minutes: int = 30

    # --- email -----------------------------------------------------------
    # Leave smtp_host empty and the login code is shown in the app instead of
    # emailed — that is the zero-config path, and the fallback if SMTP fails.
    # Set these (SINCE_SMTP_HOST, SINCE_SMTP_USER, ...) to send real mail.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                       # e.g. "since@yourdomain.com"
    smtp_from_name: str = "Since"
    smtp_starttls: bool = True                # port 587
    smtp_ssl: bool = False                    # port 465 instead
    smtp_timeout_seconds: float = 10.0

    # --- auth ------------------------------------------------------------
    # Show the login code in the app. Forced on whenever SMTP is unconfigured
    # (otherwise nobody could ever sign in); set false once mail is working.
    auth_dev_return_code: bool = True
    login_code_ttl_seconds: int = 600
    session_ttl_days: int = 90
    # A "visit" ends after this much inactivity; the next request starts a
    # new one, which is when the per-user baseline advances.
    visit_idle_minutes: int = 30

    static_dir: str | None = None  # built frontend to serve; default: ../frontend/dist if present
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"


settings = Settings()
