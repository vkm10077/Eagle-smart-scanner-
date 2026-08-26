from __future__ import annotations

"""
Eagle Smart Scanner - Live Market Store

Thread-safe in-memory store for live FYERS WebSocket ticks.

Responsibilities
----------------
- Store live index/sector/stock ticks
- Normalize FYERS WebSocket payloads
- Reject invalid/fake/zero-price ticks
- Detect stale live data
- Maintain subscription symbol set
- Provide scanner/dashboard snapshots
- Keep REST fallback data separate from true WebSocket data

This module does NOT create the WebSocket connection itself.
The WebSocket service/orchestrator feeds messages into this store.
"""

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from config import Config
from data.sector_map import (
    get_candidate_sector_symbols,
    normalize_stock_symbol,
)
from services.fyers_service import FyersService


# ============================================================
# MODELS
# ============================================================

@dataclass(frozen=True)
class LiveTick:
    symbol: str
    fyers_symbol: str
    ltp: float
    change: float
    change_percent: float
    open: float
    high: float
    low: float
    previous_close: float
    volume: float
    bid: float
    ask: float
    exchange_timestamp: int | None
    received_timestamp: float
    source: str = "websocket"

    @property
    def age_seconds(self) -> float:
        return max(
            0.0,
            time.time() - self.received_timestamp,
        )

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > Config.LIVE_TICK_MAX_AGE_SECONDS


# ============================================================
# LIVE MARKET STORE
# ============================================================

class LiveMarketStore:
    """
    Central thread-safe live price store.

    One singleton instance should be shared by:
    - WebSocket callbacks
    - scanner_orchestrator
    - market_data_service
    - dashboard APIs
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

        self._ticks: dict[str, LiveTick] = {}
        self._subscriptions: set[str] = set()

        self._connected: bool = False
        self._last_connect_at: float | None = None
        self._last_disconnect_at: float | None = None
        self._last_message_at: float | None = None
        self._last_error: str = ""

        self._message_count: int = 0
        self._accepted_tick_count: int = 0
        self._rejected_tick_count: int = 0

    # ========================================================
    # CONNECTION STATE
    # ========================================================

    def mark_connected(self) -> None:
        with self._lock:
            self._connected = True
            self._last_connect_at = time.time()
            self._last_error = ""

    def mark_disconnected(
        self,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            self._connected = False
            self._last_disconnect_at = time.time()

            if reason:
                self._last_error = str(reason)

    def mark_error(
        self,
        error: str | Exception,
    ) -> None:
        with self._lock:
            self._last_error = str(error)

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # ========================================================
    # SUBSCRIPTIONS
    # ========================================================

    def set_subscriptions(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        normalized = self._normalize_symbols(symbols)

        with self._lock:
            self._subscriptions = set(normalized)

        return normalized

    def add_subscriptions(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        normalized = self._normalize_symbols(symbols)

        with self._lock:
            self._subscriptions.update(normalized)

        return normalized

    def remove_subscriptions(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        normalized = self._normalize_symbols(symbols)

        with self._lock:
            for symbol in normalized:
                self._subscriptions.discard(symbol)

        return normalized

    def get_subscriptions(self) -> list[str]:
        with self._lock:
            return sorted(self._subscriptions)

    def build_default_subscriptions(
        self,
        stock_symbols: Iterable[str] | None = None,
    ) -> list[str]:
        """
        Build WebSocket universe:
        benchmark indices + all candidate sector indices + selected stocks.
        """
        symbols: list[str] = []

        symbols.extend(Config.FYERS_WEBSOCKET_SYMBOLS)
        symbols.extend(get_candidate_sector_symbols())

        if stock_symbols:
            symbols.extend(stock_symbols)

        return self.set_subscriptions(symbols)

    # ========================================================
    # WEBSOCKET MESSAGE INGESTION
    # ========================================================

    def ingest(
        self,
        message: Any,
    ) -> int:
        """
        Accept one FYERS WebSocket message or a list of messages.

        Returns number of valid ticks accepted.
        """
        with self._lock:
            self._message_count += 1
            self._last_message_at = time.time()

        if isinstance(message, (list, tuple)):
            accepted = 0

            for item in message:
                if self._ingest_one(item):
                    accepted += 1

            return accepted

        return 1 if self._ingest_one(message) else 0

    def _ingest_one(
        self,
        message: Any,
    ) -> bool:
        if not isinstance(message, dict):
            self._reject()
            return False

        # FYERS may wrap values under "v".
        values = message.get("v")

        if isinstance(values, dict):
            payload = dict(values)

            for key in (
                "symbol",
                "n",
                "type",
                "code",
                "s",
            ):
                if key in message and key not in payload:
                    payload[key] = message[key]
        else:
            payload = message

        fyers_symbol = self._extract_symbol(payload)

        if not fyers_symbol:
            # Ignore control/status messages that do not contain a symbol.
            return False

        ltp = self._number(
            payload,
            "ltp",
            "lp",
            "last_price",
            "last_traded_price",
            default=0.0,
        )

        if ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
            self._reject()
            return False

        received_at = time.time()

        exchange_timestamp = self._timestamp(
            payload.get("exch_feed_time")
            or payload.get("exchange_timestamp")
            or payload.get("tt")
            or payload.get("timestamp")
            or payload.get("last_traded_time")
        )

        tick = LiveTick(
            symbol=normalize_stock_symbol(fyers_symbol),
            fyers_symbol=fyers_symbol,
            ltp=ltp,
            change=self._number(
                payload,
                "ch",
                "change",
                default=0.0,
            ),
            change_percent=self._number(
                payload,
                "chp",
                "change_percent",
                "p_change",
                default=0.0,
            ),
            open=self._number(
                payload,
                "open_price",
                "open",
                default=0.0,
            ),
            high=self._number(
                payload,
                "high_price",
                "high",
                default=0.0,
            ),
            low=self._number(
                payload,
                "low_price",
                "low",
                default=0.0,
            ),
            previous_close=self._number(
                payload,
                "prev_close_price",
                "prev_close",
                "previous_close",
                default=0.0,
            ),
            volume=self._number(
                payload,
                "vol_traded_today",
                "volume",
                "vol",
                default=0.0,
            ),
            bid=self._number(
                payload,
                "bid_price",
                "bid",
                default=0.0,
            ),
            ask=self._number(
                payload,
                "ask_price",
                "ask",
                default=0.0,
            ),
            exchange_timestamp=exchange_timestamp,
            received_timestamp=received_at,
            source="websocket",
        )

        if not self._valid_tick(tick):
            self._reject()
            return False

        with self._lock:
            self._ticks[fyers_symbol] = tick
            self._accepted_tick_count += 1

        return True

    # ========================================================
    # REST QUOTE INGESTION
    # ========================================================

    def ingest_rest_quote(
        self,
        quote: Any,
    ) -> bool:
        """
        Optional safe cache of a real FYERS REST quote.

        This is never labelled as WebSocket data.
        """
        fyers_symbol = str(
            getattr(quote, "fyers_symbol", "")
            or ""
        ).strip().upper()

        ltp = self._safe_float(
            getattr(quote, "ltp", 0.0)
        )

        if not fyers_symbol:
            return False

        if ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
            return False

        tick = LiveTick(
            symbol=normalize_stock_symbol(fyers_symbol),
            fyers_symbol=fyers_symbol,
            ltp=ltp,
            change=self._safe_float(
                getattr(quote, "change", 0.0)
            ),
            change_percent=self._safe_float(
                getattr(quote, "change_percent", 0.0)
            ),
            open=self._safe_float(
                getattr(quote, "open", 0.0)
            ),
            high=self._safe_float(
                getattr(quote, "high", 0.0)
            ),
            low=self._safe_float(
                getattr(quote, "low", 0.0)
            ),
            previous_close=self._safe_float(
                getattr(quote, "previous_close", 0.0)
            ),
            volume=self._safe_float(
                getattr(quote, "volume", 0.0)
            ),
            bid=self._safe_float(
                getattr(quote, "bid", 0.0)
            ),
            ask=self._safe_float(
                getattr(quote, "ask", 0.0)
            ),
            exchange_timestamp=self._timestamp(
                getattr(quote, "timestamp", None)
            ),
            received_timestamp=time.time(),
            source="rest",
        )

        if not self._valid_tick(tick):
            return False

        with self._lock:
            # Do not overwrite a fresh WebSocket tick with REST data.
            existing = self._ticks.get(fyers_symbol)

            if (
                existing is not None
                and existing.source == "websocket"
                and not existing.is_stale
            ):
                return False

            self._ticks[fyers_symbol] = tick

        return True

    # ========================================================
    # READ API
    # ========================================================

    def get_tick(
        self,
        symbol: str,
        *,
        allow_stale: bool = False,
    ) -> LiveTick | None:
        fyers_symbol = FyersService.normalize_fyers_symbol(
            symbol
        )

        if not fyers_symbol:
            return None

        with self._lock:
            tick = self._ticks.get(fyers_symbol)

        if tick is None:
            return None

        if tick.is_stale and not allow_stale:
            return None

        return tick

    def get_ltp(
        self,
        symbol: str,
        *,
        allow_stale: bool = False,
    ) -> float | None:
        tick = self.get_tick(
            symbol,
            allow_stale=allow_stale,
        )

        if tick is None:
            return None

        return tick.ltp

    def has_fresh_tick(
        self,
        symbol: str,
    ) -> bool:
        return self.get_tick(
            symbol,
            allow_stale=False,
        ) is not None

    def get_many(
        self,
        symbols: Iterable[str],
        *,
        allow_stale: bool = False,
    ) -> dict[str, LiveTick]:
        result: dict[str, LiveTick] = {}

        for symbol in symbols:
            tick = self.get_tick(
                symbol,
                allow_stale=allow_stale,
            )

            if tick is not None:
                result[tick.fyers_symbol] = tick

        return result

    def snapshot(
        self,
        *,
        allow_stale: bool = False,
    ) -> dict[str, dict[str, Any]]:
        with self._lock:
            ticks = list(self._ticks.values())

        result: dict[str, dict[str, Any]] = {}

        for tick in ticks:
            if tick.is_stale and not allow_stale:
                continue

            row = asdict(tick)
            row["age_seconds"] = round(
                tick.age_seconds,
                3,
            )
            row["is_stale"] = tick.is_stale

            result[tick.fyers_symbol] = row

        return result

    # ========================================================
    # STALE DATA MANAGEMENT
    # ========================================================

    def stale_symbols(self) -> list[str]:
        with self._lock:
            return sorted(
                symbol
                for symbol, tick in self._ticks.items()
                if tick.is_stale
            )

    def fresh_symbols(self) -> list[str]:
        with self._lock:
            return sorted(
                symbol
                for symbol, tick in self._ticks.items()
                if not tick.is_stale
            )

    def purge_stale(
        self,
        max_age_seconds: int | float | None = None,
    ) -> int:
        max_age = float(
            max_age_seconds
            if max_age_seconds is not None
            else Config.LIVE_TICK_MAX_AGE_SECONDS
        )

        now = time.time()

        with self._lock:
            stale = [
                symbol
                for symbol, tick in self._ticks.items()
                if (now - tick.received_timestamp) > max_age
            ]

            for symbol in stale:
                self._ticks.pop(symbol, None)

        return len(stale)

    # ========================================================
    # HEALTH / STATUS
    # ========================================================

    def status(self) -> dict[str, Any]:
        now = time.time()

        with self._lock:
            fresh_count = sum(
                1
                for tick in self._ticks.values()
                if not tick.is_stale
            )

            stale_count = len(self._ticks) - fresh_count

            last_message_age = (
                None
                if self._last_message_at is None
                else max(
                    0.0,
                    now - self._last_message_at,
                )
            )

            return {
                "enabled": bool(
                    Config.FYERS_WEBSOCKET_ENABLED
                ),
                "connected": self._connected,
                "subscriptions": len(
                    self._subscriptions
                ),
                "stored_ticks": len(self._ticks),
                "fresh_ticks": fresh_count,
                "stale_ticks": stale_count,
                "message_count": self._message_count,
                "accepted_ticks": self._accepted_tick_count,
                "rejected_ticks": self._rejected_tick_count,
                "last_connect_at": self._last_connect_at,
                "last_disconnect_at": self._last_disconnect_at,
                "last_message_at": self._last_message_at,
                "last_message_age_seconds": (
                    None
                    if last_message_age is None
                    else round(last_message_age, 3)
                ),
                "last_error": self._last_error,
            }

    # ========================================================
    # RESET
    # ========================================================

    def clear_ticks(self) -> None:
        with self._lock:
            self._ticks.clear()

    def reset(self) -> None:
        with self._lock:
            self._ticks.clear()
            self._subscriptions.clear()

            self._connected = False
            self._last_connect_at = None
            self._last_disconnect_at = None
            self._last_message_at = None
            self._last_error = ""

            self._message_count = 0
            self._accepted_tick_count = 0
            self._rejected_tick_count = 0

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _reject(self) -> None:
        with self._lock:
            self._rejected_tick_count += 1

    @staticmethod
    def _valid_tick(
        tick: LiveTick,
    ) -> bool:
        if not tick.fyers_symbol:
            return False

        if (
            tick.ltp <= 0
            and not Config.ALLOW_ZERO_PRICE
        ):
            return False

        if tick.high > 0 and tick.low > 0:
            if tick.high < tick.low:
                return False

        if tick.volume < 0:
            return False

        return True

    @staticmethod
    def _extract_symbol(
        payload: dict[str, Any],
    ) -> str:
        value = (
            payload.get("symbol")
            or payload.get("n")
            or payload.get("fyToken")
            or ""
        )

        text = str(value or "").strip().upper()

        if not text:
            return ""

        # Only convert human/equity symbols. Already-qualified FYERS
        # symbols are preserved.
        if ":" in text:
            return text

        # Control messages sometimes have arbitrary strings in "symbol".
        # A plain NSE equity ticker can be normalized safely.
        return FyersService.normalize_fyers_symbol(text)

    @classmethod
    def _normalize_symbols(
        cls,
        symbols: Iterable[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for raw in symbols:
            symbol = FyersService.normalize_fyers_symbol(
                str(raw or "").strip()
            )

            if not symbol:
                continue

            if symbol in seen:
                continue

            seen.add(symbol)
            result.append(symbol)

        return result

    @staticmethod
    def _number(
        payload: dict[str, Any],
        *keys: str,
        default: float = 0.0,
    ) -> float:
        for key in keys:
            value = payload.get(key)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                continue

        return float(default)

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _timestamp(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        try:
            timestamp = int(float(value))
        except (TypeError, ValueError):
            return None

        # Normalize milliseconds to seconds when needed.
        if timestamp > 10_000_000_000:
            timestamp //= 1000

        return timestamp


# ============================================================
# SINGLETON
# ============================================================

_live_market_store = LiveMarketStore()


def get_live_market_store() -> LiveMarketStore:
    return _live_market_store


# ============================================================
# BACKWARD-COMPATIBLE HELPERS
# ============================================================

def update_live_tick(
    message: Any,
) -> int:
    return _live_market_store.ingest(message)


def get_live_tick(
    symbol: str,
    *,
    allow_stale: bool = False,
) -> LiveTick | None:
    return _live_market_store.get_tick(
        symbol,
        allow_stale=allow_stale,
    )


def get_live_price(
    symbol: str,
    *,
    allow_stale: bool = False,
) -> float | None:
    return _live_market_store.get_ltp(
        symbol,
        allow_stale=allow_stale,
    )


def get_live_snapshot(
    *,
    allow_stale: bool = False,
) -> dict[str, dict[str, Any]]:
    return _live_market_store.snapshot(
        allow_stale=allow_stale,
    )
