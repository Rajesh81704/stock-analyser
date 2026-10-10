"""
Real-time Webhook & WebSocket Manager for Zerodha KiteConnect & Live Market Feeds
Allows pushing real-time tick updates, price quotes, and screener alerts directly to connected web clients with 0 HTTP polling.
"""

from typing import Dict, List, Set, Any, Optional
import json
import logging
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("WebhooksManager")

class ConnectionManager:
    """Manages active WebSocket connections and topic subscriptions."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        logger.info(f"WebSocket client connected. Total active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        logger.info(f"WebSocket client disconnected. Remaining connections: {len(self.active_connections)}")

    def subscribe(self, websocket: WebSocket, symbol: str):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].add(symbol.upper())

    def unsubscribe(self, websocket: WebSocket, symbol: str):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].discard(symbol.upper())

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcasts message to all connected clients."""
        payload = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_symbol_tick(self, symbol: str, tick_data: Dict[str, Any]):
        """Broadcasts live price tick to clients subscribed to specific symbol or all clients."""
        symbol_clean = symbol.upper()
        payload = json.dumps({
            "type": "TICK_UPDATE",
            "symbol": symbol_clean,
            "data": tick_data,
            "timestamp": datetime.now().isoformat()
        })
        disconnected = []
        for connection in self.active_connections:
            subs = self.subscriptions.get(connection, set())
            if not subs or symbol_clean in subs or "*" in subs:
                try:
                    await connection.send_text(payload)
                except Exception as e:
                    disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

ws_manager = ConnectionManager()


def process_incoming_webhook_tick(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses and standardizes incoming webhook tick data from Zerodha postback or live feed.
    """
    symbol = payload.get("symbol") or payload.get("trading_symbol") or payload.get("ticker") or "UNKNOWN"
    last_price = payload.get("last_price") or payload.get("close") or payload.get("price") or 0.0
    change_pct = payload.get("change_pct") or payload.get("change") or 0.0
    volume = payload.get("volume") or payload.get("volume_traded") or 0
    high = payload.get("high") or last_price
    low = payload.get("low") or last_price
    open_price = payload.get("open") or last_price

    return {
        "symbol": str(symbol).upper(),
        "last_price": round(float(last_price), 2),
        "change_pct": round(float(change_pct), 2),
        "volume": int(volume),
        "open": round(float(open_price), 2),
        "high": round(float(high), 2),
        "low": round(float(low), 2),
        "timestamp": payload.get("timestamp") or datetime.now().isoformat()
    }
