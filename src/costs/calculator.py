"""
Zerodha Intraday Equity Cost & Slippage Calculator.

This module computes accurate transaction costs, statutory charges,
and slippage for Indian equities (NSE intraday / MIS product) according
to Zerodha's equity intraday tariff schedule.

Tariff Reference:
- Brokerage: min(Rs 20, 0.03% of turnover) per order leg
- STT/CTT: 0.025% on the sell side only for equity intraday
- Exchange Transaction Charges (NSE): 0.00297% on both sides
- SEBI Turnover Charges: Rs 10 per crore (0.0001%) on both sides
- Stamp Duty: 0.003% on buy side only
- GST: 18% on (Brokerage + Exchange Charges + SEBI Fees)
- Slippage: Configurable bps (default 5 bps, 10 bps for turnover < Rs 100 Cr)

Note: Always verify current rates against Zerodha's official brokerage calculator:
https://zerodha.com/brokerage-calculator/#tab-equities
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class ZerodhaIntradayCostsConfig:
    """Configuration parameters for Zerodha Intraday Equity costs and slippage."""
    brokerage_pct: float = 0.0003          # 0.03%
    max_brokerage_per_order: float = 20.0  # Rs 20 cap per order leg
    stt_sell_pct: float = 0.00025          # 0.025% on sell side
    exchange_txn_pct: float = 0.0000297    # 0.00297% on both sides (NSE)
    sebi_turnover_pct: float = 0.000001    # Rs 10 / Crore = 0.0001%
    stamp_duty_buy_pct: float = 0.00003    # 0.003% on buy side
    gst_pct: float = 0.18                  # 18% on (Brokerage + Exchange txn + SEBI)
    default_slippage_bps: float = 5.0      # 5 bps = 0.05%
    low_turnover_slippage_bps: float = 10.0 # 10 bps for illiquid stocks
    low_turnover_threshold_cr: float = 100.0 # Turnover threshold in Rs Crore


@dataclass
class CostBreakdown:
    """Detailed breakdown of costs incurred on an intraday roundtrip trade."""
    turnover_buy: float
    turnover_sell: float
    turnover_total: float
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    statutory_costs: float
    slippage_cost: float
    total_costs: float
    effective_entry_price: float
    effective_exit_price: float


class CostCalculator:
    """
    Computes statutory charges, brokerages, and slippage for intraday equity trades.
    """

    def __init__(self, config: ZerodhaIntradayCostsConfig = None):
        self.config = config or ZerodhaIntradayCostsConfig()

    def get_slippage_pct(self, trailing_turnover_cr: float, cost_multiplier: float = 1.0, slippage_multiplier: float = 1.0) -> float:
        """
        Determines the slippage percentage based on stock liquidity and multiplier.
        """
        base_bps = (
            self.config.low_turnover_slippage_bps
            if trailing_turnover_cr < self.config.low_turnover_threshold_cr
            else self.config.default_slippage_bps
        )
        return (base_bps * slippage_multiplier) / 10000.0

    def calculate_roundtrip(
        self,
        side: str,
        qty: int,
        raw_entry_price: float,
        raw_exit_price: float,
        trailing_turnover_cr: float = 150.0,
        cost_multiplier: float = 1.0,
        slippage_multiplier: float = 1.0,
    ) -> CostBreakdown:
        """
        Calculate full roundtrip costs including slippage and statutory taxes.

        Parameters:
        -----------
        side: 'LONG' or 'SHORT'
        qty: integer share quantity
        raw_entry_price: unadjusted trigger/fill price
        raw_exit_price: unadjusted stop/target/time-exit price
        trailing_turnover_cr: 20-day average turnover in Rs Crore (for liquidity slippage tier)
        cost_multiplier: stress-test multiplier for statutory taxes & brokerage (default 1.0)
        slippage_multiplier: stress-test multiplier for slippage bps (default 1.0)
        """
        if qty <= 0:
            raise ValueError(f"Quantity must be positive integer, got {qty}")

        slippage_pct = self.get_slippage_pct(
            trailing_turnover_cr,
            cost_multiplier=cost_multiplier,
            slippage_multiplier=slippage_multiplier
        )

        # Slippage adversely impacts execution prices:
        # Long entry: buys higher; Long exit: sells lower
        # Short entry: sells lower; Short exit: buys higher
        if side.upper() == "LONG":
            eff_entry_price = raw_entry_price * (1.0 + slippage_pct)
            eff_exit_price = raw_exit_price * (1.0 - slippage_pct)
            buy_price = eff_entry_price
            sell_price = eff_exit_price
            slippage_entry = qty * (eff_entry_price - raw_entry_price)
            slippage_exit = qty * (raw_exit_price - eff_exit_price)
        elif side.upper() == "SHORT":
            eff_entry_price = raw_entry_price * (1.0 - slippage_pct)
            eff_exit_price = raw_exit_price * (1.0 + slippage_pct)
            buy_price = eff_exit_price
            sell_price = eff_entry_price
            slippage_entry = qty * (raw_entry_price - eff_entry_price)
            slippage_exit = qty * (eff_exit_price - raw_exit_price)
        else:
            raise ValueError(f"Unknown side: {side}")

        slippage_cost = slippage_entry + slippage_exit

        turnover_buy = qty * buy_price
        turnover_sell = qty * sell_price
        turnover_total = turnover_buy + turnover_sell

        # 1. Brokerage: min(Rs 20, 0.03%) per leg
        brokerage_entry = min(self.config.max_brokerage_per_order, turnover_buy * self.config.brokerage_pct) if side.upper() == "LONG" \
            else min(self.config.max_brokerage_per_order, turnover_sell * self.config.brokerage_pct)
        brokerage_exit = min(self.config.max_brokerage_per_order, turnover_sell * self.config.brokerage_pct) if side.upper() == "LONG" \
            else min(self.config.max_brokerage_per_order, turnover_buy * self.config.brokerage_pct)
        brokerage = (brokerage_entry + brokerage_exit) * cost_multiplier

        # 2. STT: 0.025% on sell side only for equity intraday
        stt = (turnover_sell * self.config.stt_sell_pct) * cost_multiplier

        # 3. Exchange transaction charges (NSE: 0.00297% on both sides)
        exchange_charges = (turnover_total * self.config.exchange_txn_pct) * cost_multiplier

        # 4. SEBI turnover fee: Rs 10 / Crore (0.0001% on both sides)
        sebi_charges = (turnover_total * self.config.sebi_turnover_pct) * cost_multiplier

        # 5. Stamp duty: 0.003% on buy side only
        stamp_duty = (turnover_buy * self.config.stamp_duty_buy_pct) * cost_multiplier

        # 6. GST: 18% on (Brokerage + Exchange Charges + SEBI Fees)
        gst = ((brokerage + exchange_charges + sebi_charges) * self.config.gst_pct)

        statutory_costs = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst
        total_costs = statutory_costs + slippage_cost

        return CostBreakdown(
            turnover_buy=turnover_buy,
            turnover_sell=turnover_sell,
            turnover_total=turnover_total,
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            gst=gst,
            statutory_costs=statutory_costs,
            slippage_cost=slippage_cost,
            total_costs=total_costs,
            effective_entry_price=eff_entry_price,
            effective_exit_price=eff_exit_price,
        )
