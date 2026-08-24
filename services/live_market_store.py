from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class LiveMarketStore:
    """
    Thread-safe in-memory store for FYERS WebSocket ticks.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._message_count = 0
        self._last_message_at: Optional[str] = None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def update(self, message: Any) -> bool:
        if not isinstance(message, dict):
            return False

        symbol = str(message.get("symbol") or "").strip().upper()

        if not symbol:
            return False

        tick = copy.deepcopy(message)
        tick["received_at"] = self._now_iso()

        with self._lock:
            self._data[symbol] = tick
            self._message_count += 1
            self._last_message_at = tick["received_at"]

        return True

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_symbol = str(symbol or "").strip().upper()

        with self._lock:
            value = self._data.get(clean_symbol)

            if value is None:
                return None

            return copy.deepcopy(value)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._data)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "symbols_received": len(self._data),
                "message_count": self._message_count,
                "last_message_at": self._last_message_at,
                "symbols": sorted(self._data.keys()),
            }

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._message_count = 0
            self._last_message_at = None


LIVE_MARKET_STORE = LiveMarketStore()