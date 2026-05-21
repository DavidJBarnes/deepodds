from pydantic import BaseModel, Field, model_validator


class BotConfigResponse(BaseModel):
    mode: str
    strategy: str = "model"
    enabled: bool
    max_exposure_cents: int
    daily_budget_cents: int
    min_edge_cents: float
    min_liquidity: float
    max_position_cents: int
    max_contracts_per_signal: int
    max_position_cents_moderate: int
    max_contracts_moderate: int
    max_position_cents_high: int
    max_contracts_high: int
    max_position_cents_elite: int
    max_contracts_elite: int
    take_profit_cents: int
    stop_loss_cents: int
    daily_loss_limit_cents: int
    max_signals_per_hour: int
    tier_budget_pct_elite: int
    tier_budget_pct_high: int
    max_positions_per_asset: int = 3
    min_yes_prob: int = 20
    expiry_exit_minutes: int = 15
    spot_enabled: bool = False
    spot_mode: str = "paper"
    spot_dip_pct: float = 3.0
    spot_take_profit_pct: float = 3.0
    spot_stop_loss_pct: float = 2.0
    spot_buy_amount_usd: int = 50
    spot_max_position_usd: int = 500
    spot_cooldown_minutes: int = 60
    settlement_arb_enabled: bool = False
    settlement_arb_max_minutes: int = 60
    settlement_arb_min_sigma: float = 1.5
    settlement_arb_min_discount_cents: int = 5
    settlement_arb_max_position_cents: int = 5000


class BotConfigUpdate(BaseModel):
    mode: str | None = None
    strategy: str | None = None
    enabled: bool | None = None
    max_exposure_cents: int | None = Field(None, ge=100, le=100000)
    daily_budget_cents: int | None = Field(None, ge=0, le=100000)
    min_edge_cents: float | None = Field(None, ge=1, le=50)
    min_liquidity: float | None = Field(None, ge=0)
    max_position_cents: int | None = Field(None, ge=100, le=10000)
    max_contracts_per_signal: int | None = Field(None, ge=1, le=100)
    max_position_cents_moderate: int | None = Field(None, ge=100, le=10000)
    max_contracts_moderate: int | None = Field(None, ge=1, le=100)
    max_position_cents_high: int | None = Field(None, ge=100, le=10000)
    max_contracts_high: int | None = Field(None, ge=1, le=100)
    max_position_cents_elite: int | None = Field(None, ge=100, le=50000)
    max_contracts_elite: int | None = Field(None, ge=1, le=200)
    take_profit_cents: int | None = Field(None, ge=0, le=50)
    stop_loss_cents: int | None = Field(None, ge=0, le=50)
    daily_loss_limit_cents: int | None = Field(None, ge=0, le=100000)
    max_signals_per_hour: int | None = Field(None, ge=0, le=50)
    tier_budget_pct_elite: int | None = Field(None, ge=0, le=50)
    tier_budget_pct_high: int | None = Field(None, ge=0, le=50)
    max_positions_per_asset: int | None = Field(None, ge=0, le=20)
    min_yes_prob: int | None = Field(None, ge=0, le=100)
    expiry_exit_minutes: int | None = Field(None, ge=0, le=120)
    spot_enabled: bool | None = None
    spot_mode: str | None = None
    spot_dip_pct: float | None = Field(None, ge=0.5, le=20.0)
    spot_take_profit_pct: float | None = Field(None, ge=1.5, le=50.0)
    spot_stop_loss_pct: float | None = Field(None, ge=1.5, le=50.0)
    spot_buy_amount_usd: int | None = Field(None, ge=10, le=10000)
    spot_max_position_usd: int | None = Field(None, ge=10, le=100000)
    spot_cooldown_minutes: int | None = Field(None, ge=5, le=1440)
    settlement_arb_enabled: bool | None = None
    settlement_arb_max_minutes: int | None = Field(None, ge=1, le=240)
    settlement_arb_min_sigma: float | None = Field(None, ge=0.5, le=5.0)
    settlement_arb_min_discount_cents: int | None = Field(None, ge=1, le=50)
    settlement_arb_max_position_cents: int | None = Field(None, ge=100, le=100000)

    @model_validator(mode="after")
    def check_fee_sanity(self):
        ROUND_TRIP_FEE_PCT = 1.0  # Coinbase 0.5% taker fee each side
        if self.spot_take_profit_pct is not None and self.spot_take_profit_pct <= ROUND_TRIP_FEE_PCT:
            raise ValueError(
                f"Take profit ({self.spot_take_profit_pct}%) must exceed "
                f"round-trip Coinbase fees ({ROUND_TRIP_FEE_PCT}%)"
            )
        return self
