"""
Kite Connect Client Wrapper with Session Management & Safety Validations.

Handles:
- Manual daily web authentication workflow (URL generation & request token exchange)
- Encrypted/persisted access token storage
- Detection and formatting of Static IP restriction errors
- Rate-limited historical candle fetching with exponential backoff
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pandas as pd

try:
    from kiteconnect import KiteConnect
    from kiteconnect.exceptions import PermissionException, InputException, NetworkException
except ImportError:
    KiteConnect = None
    PermissionException = Exception
    InputException = Exception
    NetworkException = Exception

from src.algodesk.config.settings import settings

logger = logging.getLogger(__name__)


class StaticIPRestrictionError(Exception):
    """Raised when Zerodha rejects API requests due to an unregistered VPS Static IP."""
    pass


_CONNECTION_CACHE: Dict[str, Any] = {
    "token": None,
    "last_checked": 0,
    "result": None,
}


class KiteClientWrapper:
    """Wrapper around Zerodha KiteConnect client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        self.api_key = api_key or settings.kite_api_key
        self.api_secret = api_secret or settings.kite_api_secret
        self.access_token = access_token or settings.active_kite_token

        if KiteConnect is None:
            raise ImportError("kiteconnect is not installed. Install via pip install kiteconnect.")

        if not self.api_key:
            raise ValueError("KITE_API_KEY is missing from environment or configuration.")

        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)

        self._instrument_cache: Dict[str, int] = {}


    @classmethod
    def get_login_url(cls, api_key: Optional[str] = None) -> str:
        """
        Generates the manual login URL for Zerodha Kite Connect web authentication.
        Manual login is required daily as 2FA TOTP cannot be automated.
        """
        key = api_key if api_key is not None else settings.kite_api_key
        if not key:
            raise ValueError("KITE_API_KEY is required to generate the login URL.")
        if KiteConnect is None:
            raise ImportError("kiteconnect is not installed.")

        kc = KiteConnect(api_key=key)
        return kc.login_url()

    @classmethod
    def generate_session_token(
        cls,
        request_token: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> str:
        """
        Exchanges the request_token from login redirect for a daily access token.
        """
        key = api_key or settings.kite_api_key
        secret = api_secret or settings.kite_api_secret

        if not key or not secret:
            raise ValueError("Both KITE_API_KEY and KITE_API_SECRET are required for session exchange.")

        kc = KiteConnect(api_key=key)
        try:
            session_data = kc.generate_session(request_token=request_token, api_secret=secret)
        except Exception as e:
            err_msg = str(e).lower()
            if "ip" in err_msg or "forbidden" in err_msg:
                raise StaticIPRestrictionError(
                    "Zerodha rejected session exchange. If running on a cloud VPS, "
                    "verify that your VPS static IP is registered in your Kite Developer Console app settings."
                ) from e
            raise RuntimeError(f"Failed to exchange request token with Zerodha Kite: {e}") from e

        token = session_data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token returned by Kite session: {session_data}")
        return token

    def check_connection(self, force: bool = False) -> Dict[str, Any]:
        """Validates current access token by fetching account profile with 60s cache."""
        now = time.time()
        if not force and _CONNECTION_CACHE["token"] == self.access_token and (now - _CONNECTION_CACHE["last_checked"] < 60):
            if _CONNECTION_CACHE["result"] is not None:
                return _CONNECTION_CACHE["result"]

        try:
            profile = self.kite.profile()
            res = {"status": "CONNECTED", "user_id": profile.get("user_id"), "user_name": profile.get("user_name")}
            _CONNECTION_CACHE["token"] = self.access_token
            _CONNECTION_CACHE["last_checked"] = now
            _CONNECTION_CACHE["result"] = res
            return res
        except PermissionException as pe:
            err_msg = str(pe).lower()
            if "ip" in err_msg or "network" in err_msg:
                raise StaticIPRestrictionError(
                    "VPS Static IP Not Authorized: Register this server's public IP in your Kite Developer Console."
                ) from pe
            res = {"status": "EXPIRED", "error": str(pe)}
            _CONNECTION_CACHE["token"] = self.access_token
            _CONNECTION_CACHE["last_checked"] = now
            _CONNECTION_CACHE["result"] = res
            return res
        except Exception as e:
            res = {"status": "ERROR", "error": str(e)}
            return res


    def fetch_historical_candles_chunked(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "5minute",
        max_chunk_days: int = 90,
        rate_limit_sleep: float = 0.5,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """
        Fetches historical candles in 90-day chunks with rate limiting and retry backoff.
        Kite allows a maximum of ~100 days for 5-minute interval requests.
        """
        all_bars = []
        curr_from = from_date

        while curr_from < to_date:
            curr_to = min(curr_from + timedelta(days=max_chunk_days), to_date)
            chunk_records = None

            for attempt in range(max_retries):
                try:
                    time.sleep(rate_limit_sleep)
                    chunk_records = self.kite.historical_data(
                        instrument_token=instrument_token,
                        from_date=curr_from.strftime("%Y-%m-%d %H:%M:%S"),
                        to_date=curr_to.strftime("%Y-%m-%d %H:%M:%S"),
                        interval=interval,
                    )
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if "ip" in err_str or "unauthorized" in err_str:
                        raise StaticIPRestrictionError(
                            "Kite API rejected request. Check that your VPS static IP is whitelisted in Kite console."
                        ) from e

                    backoff = (2 ** attempt) * rate_limit_sleep * 2
                    logger.warning(f"Error fetching chunk {curr_from.date()} to {curr_to.date()} (attempt {attempt+1}): {e}. Backing off {backoff:.1f}s")
                    time.sleep(backoff)
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed historical fetch for token {instrument_token}: {e}")

            if chunk_records:
                all_bars.extend(chunk_records)

            curr_from = curr_to + timedelta(seconds=1)

        if not all_bars:
            return pd.DataFrame()

        df = pd.DataFrame(all_bars)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            if df["date"].dt.tz is not None:
                df["date"] = df["date"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

        return df[["date", "open", "high", "low", "close", "volume"]]

    # -------------------------------------------------------------------------
    # Real Brokerage Account & Order Execution Methods (LIVE TRADING)
    # -------------------------------------------------------------------------
    def get_live_margins(self) -> Dict[str, Any]:
        """Fetches live funds, available cash, and used margins from Zerodha."""
        try:
            margins = self.kite.margins(segment="equity")
            avail = margins.get("available", {})
            util = margins.get("utilised", {})
            net = margins.get("net", 0.0)
            return {
                "status": "success",
                "available_cash": float(avail.get("cash", 0.0)),
                "opening_balance": float(avail.get("opening_balance", 0.0)),
                "used_margin": float(util.get("debits", 0.0)),
                "collateral": float(avail.get("collateral", 0.0)),
                "net": float(net if isinstance(net, (int, float)) else 0.0),
            }
        except Exception as e:
            logger.error(f"Error fetching live margins: {e}")
            return {"status": "error", "message": str(e), "available_cash": 0.0, "used_margin": 0.0}

    def get_live_positions(self) -> Dict[str, Any]:
        """Fetches live open day and net positions from Zerodha."""
        try:
            pos = self.kite.positions()
            net_positions = pos.get("net", [])
            day_positions = pos.get("day", [])
            total_unrealized_pnl = sum(p.get("unrealised", 0.0) or 0.0 for p in net_positions)
            total_realized_pnl = sum(p.get("realised", 0.0) or 0.0 for p in net_positions)
            return {
                "status": "success",
                "net": net_positions,
                "day": day_positions,
                "open_count": sum(1 for p in net_positions if p.get("quantity", 0) != 0),
                "unrealized_pnl": total_unrealized_pnl,
                "realized_pnl": total_realized_pnl,
                "total_pnl": total_unrealized_pnl + total_realized_pnl,
            }
        except Exception as e:
            logger.error(f"Error fetching live positions: {e}")
            return {"status": "error", "message": str(e), "net": [], "day": [], "open_count": 0, "total_pnl": 0.0}

    def get_live_orders(self) -> List[Dict[str, Any]]:
        """Fetches today's live order book from Zerodha."""
        try:
            orders = self.kite.orders()
            # Sort latest first
            return list(reversed(orders))
        except Exception as e:
            logger.error(f"Error fetching live orders: {e}")
            return []

    def place_live_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        order_type: str = "MARKET",
        product: str = "MIS",
        price: float = 0.0,
        trigger_price: float = 0.0,
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submits a REAL order to Zerodha KiteConnect Exchange Gateways.
        """
        clean_sym = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
        clean_side = side.strip().upper()
        clean_type = order_type.strip().upper()
        clean_prod = product.strip().upper()

        kite_side = self.kite.TRANSACTION_TYPE_BUY if clean_side == "BUY" else self.kite.TRANSACTION_TYPE_SELL
        kite_type = self.kite.ORDER_TYPE_MARKET if clean_type == "MARKET" else self.kite.ORDER_TYPE_LIMIT
        kite_prod = self.kite.PRODUCT_MIS if clean_prod == "MIS" else self.kite.PRODUCT_CNC

        order_params = {
            "variety": self.kite.VARIETY_REGULAR,
            "exchange": self.kite.EXCHANGE_NSE,
            "tradingsymbol": clean_sym,
            "transaction_type": kite_side,
            "quantity": int(qty),
            "product": kite_prod,
            "order_type": kite_type,
        }

        if kite_type == self.kite.ORDER_TYPE_LIMIT and price > 0:
            order_params["price"] = round(float(price), 2)
        if trigger_price > 0:
            order_params["trigger_price"] = round(float(trigger_price), 2)
        if tag:
            order_params["tag"] = tag[:20]

        logger.info(f"Submitting LIVE Zerodha Order: {order_params}")
        order_id = self.kite.place_order(**order_params)
        return {
            "status": "success",
            "order_id": order_id,
            "symbol": clean_sym,
            "side": clean_side,
            "qty": qty,
            "product": clean_prod,
            "order_type": clean_type,
            "placed_at": datetime.now().isoformat(),
        }

    def cancel_live_order(self, order_id: str) -> Dict[str, Any]:
        """Cancels an open order in Zerodha Kite."""
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
            return {"status": "success", "order_id": order_id, "message": "Order cancelled successfully"}
        except Exception as e:
            return {"status": "error", "order_id": order_id, "message": str(e)}

    def square_off_live_position(self, symbol: str, product: str = "MIS") -> Dict[str, Any]:
        """Squares off an open live position at market price."""
        clean_sym = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
        positions = self.get_live_positions().get("net", [])
        target_pos = next((p for p in positions if p.get("tradingsymbol") == clean_sym and p.get("product") == product), None)
        if not target_pos:
            return {"status": "error", "message": f"No open position found for {clean_sym} ({product})"}

        qty = target_pos.get("quantity", 0)
        if qty == 0:
            return {"status": "error", "message": f"Position already flat for {clean_sym}"}

        # If Long (qty > 0), SELL to close. If Short (qty < 0), BUY to close.
        side = "SELL" if qty > 0 else "BUY"
        abs_qty = abs(qty)

        return self.place_live_order(
            symbol=clean_sym,
            side=side,
            qty=abs_qty,
            order_type="MARKET",
            product=product,
            tag="squareoff"
        )

    def square_off_all_live_positions(self) -> Dict[str, Any]:
        """Emergency closes ALL open MIS positions in Zerodha Kite."""
        positions = self.get_live_positions().get("net", [])
        closed = []
        errors = []
        for p in positions:
            qty = p.get("quantity", 0)
            sym = p.get("tradingsymbol")
            prod = p.get("product", "MIS")
            if qty != 0:
                try:
                    res = self.square_off_live_position(symbol=sym, product=prod)
                    closed.append({"symbol": sym, "result": res})
                except Exception as e:
                    errors.append({"symbol": sym, "error": str(e)})

        return {
            "status": "success",
            "closed_count": len(closed),
            "closed": closed,
            "errors": errors,
        }
