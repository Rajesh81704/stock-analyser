"""
AlgoDesk System Configuration & Safety Gate Validations.

Manages application settings via Pydantic BaseSettings, enforcing
strict gating for LIVE execution mode and environment variable isolation.
"""

from enum import Enum
from pathlib import Path
from typing import Optional, Tuple
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Settings(BaseSettings):
    """Global system configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core System & Safety
    algodesk_env: str = Field(default="development", alias="ALGODESK_ENV")
    algodesk_allow_live: bool = Field(default=False, alias="ALGODESK_ALLOW_LIVE")
    default_mode: ExecutionMode = ExecutionMode.PAPER

    # Kite Connect API Credentials
    kite_api_key: Optional[str] = Field(default="zgktuz1hr11f8scf", alias="KITE_API_KEY")
    kite_api_secret: Optional[str] = Field(default="pt7gvrbxi23sssa1duvhd6n6bufj8ztj", alias="KITE_API_SECRET")
    kite_access_token: Optional[str] = Field(default=None, alias="KITE_ACCESS_TOKEN")

    def __init__(self, **values):
        super().__init__(**values)
        if not self.kite_access_token:
            token_path = Path(".kite_token")
            if token_path.exists():
                try:
                    tok = token_path.read_text(encoding="utf-8").strip()
                    if tok:
                        self.kite_access_token = tok
                        import os
                        os.environ["KITE_ACCESS_TOKEN"] = tok
                except Exception:
                    pass

    @property
    def active_kite_token(self) -> Optional[str]:
        """Returns the most up-to-date access token, checking .kite_token on disk."""
        token_path = Path(".kite_token")
        if token_path.exists():
            try:
                tok = token_path.read_text(encoding="utf-8").strip()
                if tok:
                    self.kite_access_token = tok
                    import os
                    os.environ["KITE_ACCESS_TOKEN"] = tok
                    return tok
            except Exception:
                pass
        return self.kite_access_token

    def save_kite_token(self, token: str) -> None:
        """Persists access token to .kite_token and updates current settings & runtime state."""
        clean_tok = token.strip()
        self.kite_access_token = clean_tok
        import os
        os.environ["KITE_ACCESS_TOKEN"] = clean_tok
        try:
            Path(".kite_token").write_text(clean_tok, encoding="utf-8")
        except Exception:
            pass
        try:
            from src.data_loader import set_active_kite_access_token
            set_active_kite_access_token(clean_tok)
        except Exception:
            pass


    # Database & Redis
    # Default to sqlite:///./algodesk.db if DATABASE_URL is not set or during offline unit testing
    database_url: str = Field(
        default="sqlite:///./algodesk.db",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Google Gemini API
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model_fast: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL_FAST")
    gemini_model_pro: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL_PRO")
    gemini_daily_budget_calls: int = Field(default=200, alias="GEMINI_DAILY_BUDGET_CALLS")

    # Telegram Bot
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # Web Dashboard Auth & Secrets
    app_secret_key: str = Field(
        default="algodesk_default_secret_key_change_me",
        alias="APP_SECRET_KEY",
    )
    dashboard_username: str = Field(default="admin", alias="DASHBOARD_USERNAME")
    dashboard_password_hash: Optional[str] = Field(default=None, alias="DASHBOARD_PASSWORD_HASH")
    dashboard_totp_secret: Optional[str] = Field(default=None, alias="DASHBOARD_TOTP_SECRET")

    # Directories
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    results_dir: Path = Field(default=Path("results"), alias="RESULTS_DIR")
    configs_dir: Path = Field(default=Path("configs"), alias="CONFIGS_DIR")
    strategies_user_dir: Path = Field(default=Path("strategies_user"), alias="STRATEGIES_USER_DIR")

    def is_live_execution_permitted(
        self,
        strategy_live_enabled: bool,
        daily_confirmed: bool,
    ) -> Tuple[bool, str]:
        """
        Enforces NON-NEGOTIABLE SAFETY RULE 1:
        LIVE requires ALL of:
          1. env var ALGODESK_ALLOW_LIVE=true
          2. per-strategy "live_enabled: true" in its YAML config
          3. an explicit confirmation action in the dashboard each trading day.
        Otherwise orders MUST BE simulated.
        """
        if not self.algodesk_allow_live:
            return False, "BLOCKED: Environment variable ALGODESK_ALLOW_LIVE is false. Live trading forbidden."

        if not strategy_live_enabled:
            return False, "BLOCKED: Strategy config has live_enabled: false. Live trading forbidden."

        if not daily_confirmed:
            return False, "BLOCKED: Missing explicit daily confirmation in dashboard for today's session."

        return True, "PERMITTED: All 3 safety gates verified for live execution."


# Global settings singleton instance
settings = Settings()
