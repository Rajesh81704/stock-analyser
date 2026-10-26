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
