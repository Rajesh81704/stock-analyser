"""
Unit tests for Zerodha Intraday Cost & Slippage Calculator.
Validates exact formulas and hand-computed benchmarks against Zerodha intraday rules.
"""

import pytest
from src.costs.calculator import CostCalculator, ZerodhaIntradayCostsConfig


def test_hand_computed_brokerage_cap():
    """Tests high-turnover trade where brokerage hits the Rs 20 cap on both legs."""
    config = ZerodhaIntradayCostsConfig()
    calc = CostCalculator(config)

    # 100 shares @ Rs 1000 entry, Rs 1010 exit, turnover > 100 Cr (5 bps slippage)
    res = calc.calculate_roundtrip(
        side="LONG",
        qty=100,
        raw_entry_price=1000.0,
        raw_exit_price=1010.0,
        trailing_turnover_cr=150.0,
    )

    # 5 bps slippage:
    # eff entry = 1000 * 1.0005 = 1000.50
    # eff exit = 1010 * (1 - 0.0005) = 1009.495
    assert pytest.approx(res.effective_entry_price, rel=1e-5) == 1000.50
    assert pytest.approx(res.effective_exit_price, rel=1e-5) == 1009.495

    # Turnover
    assert pytest.approx(res.turnover_buy, rel=1e-5) == 100050.0
    assert pytest.approx(res.turnover_sell, rel=1e-5) == 100949.50
    assert pytest.approx(res.turnover_total, rel=1e-5) == 200999.50

    # Brokerage: min(20, 100050 * 0.0003 = 30.015) -> 20 on each leg = 40.0
    assert res.brokerage == 40.0

    # STT: 0.025% on sell turnover (100949.50 * 0.00025 = 25.237375)
    assert pytest.approx(res.stt, rel=1e-5) == 25.237375

    # Exchange charges: 0.00297% on total turnover (200999.50 * 0.0000297 = 5.96968515)
    assert pytest.approx(res.exchange_charges, rel=1e-5) == 5.96968515

    # SEBI fee: Rs 10 / Crore = 0.0001% on total turnover (200999.50 * 0.000001 = 0.2009995)
    assert pytest.approx(res.sebi_charges, rel=1e-5) == 0.2009995

    # Stamp duty: 0.003% on buy turnover (100050.0 * 0.00003 = 3.0015)
    assert pytest.approx(res.stamp_duty, rel=1e-5) == 3.0015

    # GST: 18% on (Brokerage + Exchange + SEBI)
    # 0.18 * (40.0 + 5.96968515 + 0.2009995) = 0.18 * 46.17068465 = 8.310723237
    assert pytest.approx(res.gst, rel=1e-5) == 8.310723237

    # Slippage: 100 * (1000.5 - 1000.0) + 100 * (1010.0 - 1009.495) = 50.0 + 50.5 = 100.50
    assert pytest.approx(res.slippage_cost, rel=1e-5) == 100.50

    # Total costs = statutory + slippage
    assert pytest.approx(res.total_costs, rel=1e-4) == res.statutory_costs + res.slippage_cost


def test_uncapped_brokerage_small_order():
    """Tests small turnover trade where 0.03% is below Rs 20 cap."""
    calc = CostCalculator()

    # 10 shares @ Rs 100 entry, Rs 105 exit
    res = calc.calculate_roundtrip(
        side="LONG",
        qty=10,
        raw_entry_price=100.0,
        raw_exit_price=105.0,
        trailing_turnover_cr=120.0,
    )

    # Buy turnover ~ 1000.50 => 0.03% = 0.30015 (< Rs 20 cap)
    # Sell turnover ~ 1049.475 => 0.03% = 0.3148425 (< Rs 20 cap)
    assert res.brokerage < 1.0
    assert res.brokerage > 0.5


def test_low_turnover_doubles_slippage():
    """Tests that stocks with trailing turnover < 100 Cr receive 10 bps slippage instead of 5 bps."""
    calc = CostCalculator()

    res_liquid = calc.calculate_roundtrip("LONG", 100, 1000.0, 1000.0, trailing_turnover_cr=150.0)
    res_illiquid = calc.calculate_roundtrip("LONG", 100, 1000.0, 1000.0, trailing_turnover_cr=50.0)

    # 5 bps vs 10 bps: slippage should be exactly 2x
    assert pytest.approx(res_illiquid.slippage_cost, rel=1e-5) == 2.0 * res_liquid.slippage_cost
