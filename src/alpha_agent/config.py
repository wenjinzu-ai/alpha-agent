
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__version__ = "0.3.0"

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_DOTENV_PATH if _DOTENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Alpha Agent"
    debug: bool = False
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "alpha_agent"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_enabled: bool = False

    tushare_token: str | None = None

    tavily_api_key: str | None = None
    bing_api_key: str | None = None
    bocha_api_key: str | None = None
    search_proxy: str | None = None
    searxng_url: str | None = None

    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_enabled: bool = False

    default_analysis_timeout: int = 60

    agent_max_steps: int = 60
    terminal_default_timeout: int = 180
    execute_code_default_timeout: int = 300
    pipeline_background_timeout: int = 600

    fundamental_growth_weight: float = 0.4
    fundamental_profit_weight: float = 0.35
    fundamental_valuation_weight: float = 0.25

    technical_trend_weight: float = 0.3
    technical_momentum_weight: float = 0.4
    technical_oscillator_weight: float = 0.3

    risk_volatility_weight: float = 0.25
    risk_drawdown_weight: float = 0.3
    risk_sharpe_weight: float = 0.3
    risk_liquidity_weight: float = 0.15

    synthesize_fundamental_weight: float = 0.35
    synthesize_technical_weight: float = 0.3
    synthesize_risk_weight: float = 0.35

    backtest_buy_threshold: float = 65.0
    backtest_sell_threshold: float = 35.0
    backtest_initial_capital: float = 100000.0
    backtest_commission_pct: float = 0.0003
    backtest_slippage_pct: float = 0.001
    backtest_position_pct: float = 0.95


    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()