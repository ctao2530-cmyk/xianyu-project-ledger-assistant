from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8877
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'xianyu_operator.db'}"
    log_level: str = "INFO"
    log_file: str = str(PROJECT_ROOT / "logs" / "backend.log")
    log_max_bytes: int = Field(default=5_000_000, ge=100_000, le=100_000_000)
    log_backup_count: int = Field(default=7, ge=1, le=30)
    listener_log_retention_days: int = Field(default=30, ge=1, le=365)
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    xianyu_cookie: SecretStr = SecretStr("")
    xianyu_ws_url: str = "wss://wss-goofish.dingtalk.com/"
    # Xianyu is normally reached directly on the local machine. Keeping this
    # disabled prevents stale desktop proxy variables from breaking both the
    # MTop HTTP client and the message WebSocket. Users who need a proxy can
    # opt back in explicitly.
    xianyu_use_system_proxy: bool = False
    xianyu_reconnect_min_seconds: float = 2
    xianyu_reconnect_max_seconds: float = 60
    xianyu_subscription_timeout_seconds: float = Field(default=15, ge=5, le=60)
    xianyu_history_limit: int = 30
    xianyu_context_hydration_timeout_seconds: float = Field(default=1.5, ge=0.1, le=10)
    xianyu_item_cache_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    xianyu_reconcile_interval_seconds: float = Field(default=30, ge=15, le=300)
    xianyu_reconcile_conversation_limit: int = Field(default=50, ge=1, le=200)
    xianyu_reconcile_max_age_minutes: int = Field(default=60, ge=5, le=1440)

    # Product intelligence is deliberately low frequency and read-only. One
    # run row per local calendar day is the hard safety boundary.
    product_collection_enabled: bool = True
    product_collection_hour: int = Field(default=8, ge=0, le=23)
    product_collection_minute: int = Field(default=30, ge=0, le=59)
    product_collection_timezone: str = "Asia/Shanghai"
    product_collection_check_interval_seconds: float = Field(
        default=1800, ge=60, le=86_400
    )
    product_collection_request_delay_seconds: float = Field(
        default=0.8, ge=0, le=30
    )
    product_collection_max_items: int = Field(default=100, ge=1, le=500)
    product_delivery_capacity: int = Field(default=4, ge=1, le=100)

    # Real WeChat messages are received through the official WeCom Customer
    # Service callback.  ``mock`` keeps the local webhook available for tests;
    # ``wecom`` enables the signed/encrypted public callback and official sender.
    wechat_provider: str = "mock"
    wecom_corp_id: str = ""
    wecom_corp_secret: SecretStr = SecretStr("")
    wecom_callback_token: SecretStr = SecretStr("")
    wecom_encoding_aes_key: SecretStr = SecretStr("")
    wecom_api_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_request_timeout_seconds: float = Field(default=15, ge=3, le=60)
    wecom_sync_max_pages: int = Field(default=10, ge=1, le=100)

    ai_provider: str = "codex_cli"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: SecretStr = SecretStr("")
    ai_model: str = ""
    ai_temperature: float = 0.4
    ai_timeout_seconds: float = 45

    # DeepSeek is an independent, low-latency provider for reply drafts and
    # lead-signal analysis.  Its secret is read from the local environment only
    # and is never copied into the database or returned by an API.
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_reply_model: str = "deepseek-v4-flash"
    deepseek_lead_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = Field(default=12, ge=3, le=60)

    codex_command: str = "codex"
    codex_timeout_seconds: float = Field(default=120, ge=10, le=600)
    codex_max_concurrency: int = Field(default=2, ge=1, le=8)
    codex_max_context_messages: int = Field(default=20, ge=1, le=100)
    codex_max_context_chars: int = Field(default=12_000, ge=1_000, le=100_000)
    codex_model: str = ""
    codex_reasoning_effort: str = ""
    codex_ignore_user_config: bool = True
    codex_ignore_rules: bool = True

    reply_speed_mode: str = "balanced"
    reply_fast_model: str = "gpt-5.4-mini"
    reply_fast_reasoning_effort: str = "low"
    reply_balanced_model: str = "gpt-5.6-sol"
    reply_balanced_reasoning_effort: str = "low"
    reply_quality_model: str = "gpt-5.6-sol"
    reply_quality_reasoning_effort: str = "high"
    reply_high_risk_routing_enabled: bool = True
    reply_fast_context_messages: int = Field(default=8, ge=1, le=30)
    reply_fast_context_chars: int = Field(default=4000, ge=1000, le=20000)
    reply_balanced_context_messages: int = Field(default=12, ge=1, le=50)
    reply_balanced_context_chars: int = Field(default=6000, ge=1000, le=30000)
    reply_burst_coalesce_seconds: float = Field(default=1.0, ge=0, le=10)

    # A requirement document is a deliberate, user-triggered analysis task.  It
    # uses a dedicated high-reasoning model without changing the faster model
    # selected for day-to-day reply drafts.
    requirement_analysis_model: str = "gpt-5.6-sol"
    requirement_analysis_reasoning_effort: str = "max"
    requirement_analysis_timeout_seconds: float = Field(default=300, ge=30, le=900)
    requirement_analysis_max_messages: int = Field(default=80, ge=5, le=300)
    requirement_analysis_max_context_chars: int = Field(
        default=40_000, ge=5_000, le=200_000
    )

    style_learning_enabled: bool = True
    style_learning_max_samples: int = Field(default=500, ge=20, le=5000)
    style_context_examples: int = Field(default=8, ge=1, le=20)
    style_context_max_chars: int = Field(default=1200, ge=200, le=5000)

    macos_notifications: bool = True
    api_rate_limit_per_minute: int = 120
    send_rate_limit_per_minute: int = 10
    auto_reply_feature_enabled: bool = True
    auto_reply_default_minutes: int = Field(default=480, ge=15, le=1440)
    auto_reply_max_minutes: int = Field(default=720, ge=15, le=1440)
    auto_reply_debounce_seconds: float = Field(default=3, ge=0, le=30)
    auto_reply_conversation_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    auto_reply_daily_limit: int = Field(default=30, ge=1, le=500)
    auto_reply_max_failures: int = Field(default=3, ge=1, le=20)

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def automatic_sending_enabled(self) -> bool:
        """The persisted runtime switch is always off until a user arms it."""
        return False

    @property
    def xianyu_configured(self) -> bool:
        cookie = self.xianyu_cookie.get_secret_value()
        return bool(cookie and "unb=" in cookie and "_m_h5_tk=" in cookie)

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "codex_cli":
            return bool(self.codex_command.strip())
        return bool(self.ai_api_key.get_secret_value() and self.ai_model)

    @property
    def deepseek_configured(self) -> bool:
        return bool(
            self.deepseek_api_key.get_secret_value().strip()
            and self.deepseek_base_url.strip()
            and self.deepseek_reply_model.strip()
        )

    @property
    def wecom_configured(self) -> bool:
        return bool(
            self.wechat_provider == "wecom"
            and self.wecom_corp_id.strip()
            and self.wecom_corp_secret.get_secret_value().strip()
            and self.wecom_callback_token.get_secret_value().strip()
            and self.wecom_encoding_aes_key.get_secret_value().strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
