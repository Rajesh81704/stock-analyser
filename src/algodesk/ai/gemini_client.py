"""
Google Gemini AI Integration for AlgoDesk (google-genai SDK).

Jobs:
1. News / Announcement Tagger: Extract symbol, event_type, sentiment, confidence.
2. End-of-Day Trade Reviewer: Summarize daily trading, winners, losers, and patterns.
3. Strategy Assistant: Draft Python strategy and YAML into drafts/ with static safety checks.

CRITICAL SAFETY MANDATES:
- Gemini is NEVER in the live order execution path.
- All AI responses are structured JSON validated with Pydantic schemas.
- Strategy drafts are saved to drafts/ only; never auto-activated.
- Static checker blocks forbidden modules: os, subprocess, socket, kiteconnect, eval, exec.
"""

import ast
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from src.algodesk.config.settings import settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Pydantic Output Schemas
# -------------------------------------------------------------------------
class NewsTagResult(BaseModel):
    symbol: str
    headline: str
    event_type: str = Field(description="EARNINGS, ORDER_WIN, MANAGEMENT, REGULATORY, GENERAL")
    sentiment: str = Field(description="POSITIVE, NEGATIVE, NEUTRAL")
    relevance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str


class TradeReviewResult(BaseModel):
    summary: str
    key_observations: List[str]
    recurring_patterns: List[str]
    suggested_improvements: List[str]


class StrategyDraftResult(BaseModel):
    strategy_name: str
    description: str
    python_code: str
    yaml_config: str


class SmartAllocationItem(BaseModel):
    symbol: str
    weight_pct: float
    allocated_capital: float
    exposure: Optional[float] = None
    qty: int
    rationale: str


class SmartCapitalAllocationResult(BaseModel):
    total_capital: float
    leverage: float = 5.0
    total_buying_power: Optional[float] = None
    strategy_overview: str
    allocations: List[SmartAllocationItem]
    model_used: str = "gemini-3.5-flash"


# -------------------------------------------------------------------------
# Static Safety Checker for Strategy Code
# -------------------------------------------------------------------------
FORBIDDEN_MODULES = {"os", "sys", "subprocess", "socket", "http", "requests", "urllib", "kiteconnect", "shutil"}
FORBIDDEN_CALLS = {"eval", "exec", "open", "__import__"}


def static_check_strategy_code(code: str) -> Tuple[bool, List[str]]:
    """
    Performs static AST analysis on strategy code.
    Rejects forbidden imports, file writes, network sockets, or live order calls.
    """
    violations = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError in code: {e}"]

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                base_pkg = alias.name.split(".")[0]
                if base_pkg in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden import: '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base_pkg = node.module.split(".")[0]
                if base_pkg in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden from-import: '{node.module}'")

        # Check dangerous calls
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                violations.append(f"Forbidden function call: '{node.func.id}()'")

    is_safe = len(violations) == 0
    return is_safe, violations


# -------------------------------------------------------------------------
# Gemini Client
# -------------------------------------------------------------------------
class GeminiClient:
    """Client for Google GenAI SDK with daily budget limits and structured output validation."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.fast_model = os.getenv("GEMINI_MODEL_FAST") or os.getenv("GEMINI_MODEL") or settings.gemini_model_fast or "gemini-3.5-flash"
        self.pro_model = os.getenv("GEMINI_MODEL_PRO") or os.getenv("GEMINI_MODEL") or settings.gemini_model_pro or "gemini-3.5-flash"
        self.daily_budget = settings.gemini_daily_budget_calls
        self._daily_calls_count = 0

    def is_available(self) -> bool:
        """Checks if API key is provided and daily budget is not exceeded."""
        return bool(self.api_key) and (self._daily_calls_count < self.daily_budget)

    def tag_news_headline(self, symbol: str, headline: str) -> Optional[NewsTagResult]:
        """Tags news headlines into structured sentiment and event categories."""
        if not self.is_available():
            return None

        prompt = (
            f"Analyze this Indian stock market announcement for symbol {symbol}:\n"
            f"Headline: \"{headline}\"\n"
            f"Respond ONLY with a JSON object conforming to:\n"
            f"{{\"symbol\": \"{symbol}\", \"headline\": \"{headline}\", "
            f"\"event_type\": \"EARNINGS|ORDER_WIN|MANAGEMENT|REGULATORY|GENERAL\", "
            f"\"sentiment\": \"POSITIVE|NEGATIVE|NEUTRAL\", \"relevance\": 0.9, \"confidence\": 0.85, \"summary\": \"brief summary\"}}"
        )

        try:
            raw_json = self._call_gemini(self.fast_model, prompt)
            self._daily_calls_count += 1
            data = json.loads(raw_json)
            return NewsTagResult(**data)
        except Exception as e:
            logger.warning(f"Gemini news tagging failed: {e}")
            return None

    def review_daily_trades(self, trades_summary: Dict[str, Any]) -> Optional[TradeReviewResult]:
        """Summarizes post-market trading performance, win/loss patterns, and suggestions."""
        if not self.is_available():
            return None

        prompt = (
            f"You are a senior quant performance reviewer. Review today's algorithmic trading results:\n"
            f"{json.dumps(trades_summary, indent=2)}\n"
            f"Respond ONLY with a valid JSON object with keys: "
            f"\"summary\", \"key_observations\" (list of strings), \"recurring_patterns\" (list of strings), \"suggested_improvements\" (list of strings)."
        )

        try:
            raw_json = self._call_gemini(self.pro_model, prompt)
            self._daily_calls_count += 1
            data = json.loads(raw_json)
            return TradeReviewResult(**data)
        except Exception as e:
            logger.warning(f"Gemini trade review failed: {e}")
            return None

    def optimize_capital_allocation(
        self,
        total_capital: float,
        picks: List[Dict[str, Any]],
        risk_profile: str = "BALANCED",
        leverage: float = 5.0
    ) -> SmartCapitalAllocationResult:
        """
        Smartly distributes cash margin `total_capital` across `picks` using Gemini API,
        accounting for 5x intraday MIS leverage (purchasing power = total_capital * 5.0).
        Analyzes conviction score, relative volume (RVOL), sector diversification,
        and risk-reward ratio. Falls back seamlessly to smart quantitative conviction sizing
        if the Gemini API is offline or quota-limited.
        """
        if not picks:
            return SmartCapitalAllocationResult(
                total_capital=total_capital,
                leverage=leverage,
                total_buying_power=total_capital * leverage,
                strategy_overview="No picks provided for allocation.",
                allocations=[],
                model_used="none"
            )

        if not self.is_available():
            logger.info("Gemini API not available/configured. Utilizing Quant Conviction Risk-Parity Allocation (5x MIS Leverage).")
            return self._quant_conviction_fallback(total_capital, picks, leverage=leverage)

        total_exposure = round(total_capital * leverage, 2)

        prompt = (
            f"You are a Senior Quantitative Portfolio Manager and Risk Officer.\n"
            f"You have an intraday cash margin pool of ₹{total_capital:,.2f}.\n"
            f"INTRADAY LEVERAGE: 5.0x MIS margin leverage applies (20% margin requirement). Total purchasing exposure = ₹{total_exposure:,.2f}.\n"
            f"Distribute this margin capital smartly across the following {len(picks)} selected intraday stocks.\n\n"
            f"PORTFOLIO STOCKS IN PLAY:\n"
        )
        for p in picks:
            sym = p.get("symbol", "")
            sec = p.get("sector", "Equities")
            px = float(p.get("price", 100.0))
            score = float(p.get("conviction_score", p.get("score", 75.0)))
            rvol = float(p.get("rvol", 1.0))
            strat = p.get("strategy_name", "Breakout")
            sl = float(p.get("initial_sl", px * 0.99))
            tgt = float(p.get("target", p.get("target_price", px * 1.02)))
            prompt += (
                f"- Symbol: {sym} | Sector: {sec} | Price: ₹{px:.2f} | "
                f"Conviction Score: {score:.1f} | RVOL: {rvol:.2f}x | Strategy: {strat} | "
                f"Initial SL: ₹{sl:.2f} | Target: ₹{tgt:.2f}\n"
            )

        n_picks = max(1, len(picks))
        max_pct = round(max(30.0, min(60.0, (180.0 / n_picks))), 1) if n_picks <= 4 else 25.0
        min_pct = round(max(2.0, min(8.0, 50.0 / n_picks)), 1)

        prompt += (
            f"\nRULES FOR ALLOCATION:\n"
            f"1. Total allocated margin capital across all stocks MUST sum to exactly ₹{total_capital:,.2f} (weights sum to 100.0%).\n"
            f"2. Conviction-weighted sizing: Stocks with higher conviction scores and higher RVOL MUST receive proportionally larger allocations.\n"
            f"3. Risk parity & bounds: No single stock should exceed {max_pct}% of capital. Every stock must receive at least {min_pct}% of capital.\n"
            f"4. Sector diversification: Do not overload a single sector.\n"
            f"5. Sizing & Leverage: 5.0x intraday MIS leverage applies. Calculate suggested quantity = max(1, floor((allocated_capital * 5.0) / price)).\n"
            f"6. Respond ONLY with a valid JSON object matching this schema:\n"
            f"{{\n"
            f'  "total_capital": {total_capital},\n'
            f'  "strategy_overview": "Summary of portfolio risk distribution and weighting rationale",\n'
            f'  "allocations": [\n'
            f'    {{\n'
            f'      "symbol": "SYMBOL",\n'
            f'      "weight_pct": 14.5,\n'
            f'      "allocated_capital": 14500.0,\n'
            f'      "qty": 50,\n'
            f'      "rationale": "Clear concise 1-sentence rationale for this sizing with 5x leverage"\n'
            f'    }}\n'
            f'  ]\n'
            f"}}\n"
        )

        try:
            raw_json = self._call_gemini(self.fast_model, prompt)
            self._daily_calls_count += 1
            data = json.loads(raw_json)
            alloc_items = []
            picks_by_sym = {p.get("symbol"): p for p in picks}

            for item in data.get("allocations", []):
                sym = item.get("symbol")
                px = float(picks_by_sym.get(sym, {}).get("price", 100.0))
                alloc_cap = float(item.get("allocated_capital", 0.0))
                item["exposure"] = round(alloc_cap * leverage, 2)
                # Ensure 5x leverage quantity is enforced even if LLM omitted leverage math
                expected_qty = max(1, int((alloc_cap * leverage) / max(1.0, px)))
                if item.get("qty", 0) < expected_qty * 0.7:
                    item["qty"] = expected_qty
                alloc_items.append(SmartAllocationItem(**item))

            if alloc_items:
                return SmartCapitalAllocationResult(
                    total_capital=total_capital,
                    leverage=leverage,
                    total_buying_power=total_exposure,
                    strategy_overview=data.get("strategy_overview", f"Gemini AI Portfolio Allocation (5x MIS Leverage: ₹{total_exposure:,.2f})"),
                    allocations=alloc_items,
                    model_used=self.fast_model
                )
        except Exception as e:
            logger.warning(f"Gemini smart capital allocation call notice: {e}. Falling back to quant conviction engine.")

        return self._quant_conviction_fallback(total_capital, picks, leverage=leverage)

    def _quant_conviction_fallback(
        self,
        total_capital: float,
        picks: List[Dict[str, Any]],
        leverage: float = 5.0
    ) -> SmartCapitalAllocationResult:
        """
        Mathematical Quant Conviction Fallback with 5x MIS Leverage:
        Weights positions proportional to (conviction_score^1.3 * rvol^0.5),
        clamped between min and max bounds, normalized to 100%, and sized with 5x leverage.
        """
        if not picks:
            return SmartCapitalAllocationResult(
                total_capital=total_capital,
                leverage=leverage,
                total_buying_power=total_capital * leverage,
                strategy_overview="No picks available",
                allocations=[],
                model_used="quant-engine"
            )

        raw_scores = []
        for p in picks:
            score = max(10.0, float(p.get("conviction_score", p.get("score", 70.0))))
            rvol = max(0.8, min(float(p.get("rvol", 1.0)), 3.0))
            raw_weight = (score ** 1.3) * (rvol ** 0.5)
            raw_scores.append(raw_weight)

        total_raw = sum(raw_scores) or 1.0
        weights = [raw / total_raw for raw in raw_scores]

        # Dynamic risk parity bounds
        n_picks = max(1, len(picks))
        max_bound = max(0.30, min(0.60, 1.8 / n_picks)) if n_picks <= 4 else 0.25
        min_bound = max(0.02, min(0.08, 0.5 / n_picks))
        clamped = [max(min_bound, min(w, max_bound)) for w in weights]
        norm_sum = sum(clamped)
        final_weights = [round(w / norm_sum, 4) for w in clamped]

        # Ensure sum is 1.0 by adjusting top pick
        diff = 1.0 - sum(final_weights)
        top_idx = max(range(len(final_weights)), key=lambda i: final_weights[i])
        final_weights[top_idx] = round(final_weights[top_idx] + diff, 4)

        allocations = []
        for p, w in zip(picks, final_weights):
            sym = p.get("symbol", "")
            px = max(1.0, float(p.get("price", 100.0)))
            allocated = round(total_capital * w, 2)
            exposure = round(allocated * leverage, 2)
            qty = max(1, int(exposure / px))
            score = float(p.get("conviction_score", p.get("score", 75.0)))
            rvol = float(p.get("rvol", 1.0))
            rationale = (
                f"Conviction-weighted risk parity ({w * 100.0:.1f}%, 5x MIS): "
                f"Margin ₹{allocated:,.2f} (Exposure ₹{exposure:,.2f}) | Score {score:.1f}, RVOL {rvol:.2f}x in {p.get('sector', 'Equities')}."
            )
            allocations.append(SmartAllocationItem(
                symbol=sym,
                weight_pct=round(w * 100.0, 2),
                allocated_capital=allocated,
                exposure=exposure,
                qty=qty,
                rationale=rationale
            ))

        total_exposure = round(total_capital * leverage, 2)
        return SmartCapitalAllocationResult(
            total_capital=total_capital,
            leverage=leverage,
            total_buying_power=total_exposure,
            strategy_overview=f"Quant Conviction Multi-Factor Allocation (5x MIS Leverage: ₹{total_exposure:,.2f}) across {len(picks)} positions.",
            allocations=allocations,
            model_used="quant-conviction-fallback"
        )

    def draft_strategy(self, user_idea: str) -> Tuple[bool, str, Optional[Path], Optional[Path]]:
        """
        Drafts a Python strategy file and YAML config into drafts/ based on user prompt.
        Runs static check to ensure no forbidden imports or live order calls.
        """
        if not self.is_available():
            return False, "Gemini API key missing or daily budget exceeded.", None, None

        prompt = (
            f"You are an algorithmic quantitative engineer for AlgoDesk. Draft a complete, production-ready "
            f"subclass of BaseStrategy and YAML config for this trading concept:\n"
            f"\"{user_idea}\"\n\n"
            f"RULES:\n"
            f"1. Inherit from BaseStrategy in src.algodesk.strategies.base.\n"
            f"2. Return OrderIntent objects from on_bar().\n"
            f"3. Do NOT import os, sys, subprocess, or kiteconnect.\n"
            f"Respond ONLY with a JSON object: {{\"strategy_name\": \"...\", \"description\": \"...\", \"python_code\": \"...\", \"yaml_config\": \"...\"}}"
        )

        try:
            raw_json = self._call_gemini(self.pro_model, prompt)
            self._daily_calls_count += 1
            data = json.loads(raw_json)
            draft = StrategyDraftResult(**data)

            # Static check
            is_safe, violations = static_check_strategy_code(draft.python_code)
            if not is_safe:
                return False, f"Static Check Failed: {'; '.join(violations)}", None, None

            # Save to drafts/ only (never auto-activated)
            drafts_dir = Path("drafts")
            drafts_dir.mkdir(parents=True, exist_ok=True)

            py_file = drafts_dir / f"{draft.strategy_name}.py"
            yaml_file = drafts_dir / f"{draft.strategy_name}.yaml"

            with open(py_file, "w", encoding="utf-8") as f:
                f.write(draft.python_code)
            with open(yaml_file, "w", encoding="utf-8") as f:
                f.write(draft.yaml_config)

            return True, f"Strategy draft created safely in {drafts_dir}. Requires manual review.", py_file, yaml_file

        except Exception as e:
            return False, f"Gemini strategy drafting failed: {e}", None, None

    def _call_gemini(self, model: str, prompt: str) -> str:
        """Invokes google-genai SDK with automatic model fallback and retries."""
        import time
        from google import genai
        client = genai.Client(api_key=self.api_key)
        candidate_models = [model, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash"]
        unique_models = list(dict.fromkeys([m for m in candidate_models if m]))

        last_err = None
        for m in unique_models:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=prompt,
                    )
                    text = response.text.strip()
                    import re
                    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
                    if match:
                        return match.group(1).strip()
                    fb = text.find("{")
                    lb = text.rfind("}")
                    if fb != -1 and lb != -1 and lb > fb:
                        return text[fb : lb + 1].strip()
                    return text.strip()
                except Exception as e:
                    last_err = e
                    time.sleep(0.5)

        raise RuntimeError(f"GenAI SDK error across fallback models: {last_err}") from last_err
