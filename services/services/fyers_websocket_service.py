from __future__ import annotations

"""
Eagle Smart Scanner - FYERS WebSocket Service

Purpose
-------
Create and manage the real FYERS Data WebSocket connection and feed
incoming live market ticks into services/live_market_store.py.

Responsibilities
----------------
- Connect to FYERS Data WebSocket
- Subscribe to benchmark indices + sector indices + selected stocks
- Use SymbolUpdate (OHLCV + LTP) feed
- Feed all valid ticks into LiveMarketStore
- Reconnect automatically
- Support dynamic subscription updates
- Expose start / stop / status / snapshot helpers for app.py

No trading/order placement.
No fake/random market data.
"""

import logging
import threading
import time
from typing import Any, Iterable

from config import Config
from data.sector_map import get_candidate_sector_symbols
from services.fyers_service import FyersService
from services.live_market_store import (
    LiveMarketStore,
    get_live_market_store,
)


logger = logging.getLogger(__name__)


class FyersWebSocketError(RuntimeError):
    """FYERS live WebSocket transport error."""


class FyersWebSocketService:
    """
    Threaded FYERS Data WebSocket manager.

    FYERS SDK v3 uses:
        from fyers_apiv3.FyersWebsocket import data_ws
        data_ws.FyersDataSocket(...)
    """

    DATA_TYPE = "SymbolUpdate"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        client_id: str | None = None,
        live_store: LiveMarketStore | None = None,
    ) -> None:
        self.client_id = str(
            client_id
            or Config.FYERS_CLIENT_ID
            or ""
        ).strip()

        self.access_token = str(
            access_token
            or Config.FYERS_ACCESS_TOKEN
            or ""
        ).strip()

        self.live_store = (
            live_store
            or get_live_market_store()
        )

        self._lock = threading.RLock()

        self._socket: Any | None = None
        self._thread: threading.Thread | None = None

        self._running = False
        self._connected = False
        self._stop_requested = False

        self._last_error = ""
        self._last_connect_at: float | None = None
        self._last_disconnect_at: float | None = None

        self._symbols: list[str] = []

    # ========================================================
    # SDK IMPORT
    # ========================================================

    @staticmethod
    def _import_data_ws() -> Any:
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
            return data_ws
        except Exception as exc:
            raise FyersWebSocketError(
                "Unable to import FYERS WebSocket SDK. "
                "Make sure fyers-apiv3 is installed. "
                f"Reason: {exc}"
            ) from exc

    # ========================================================
    # AUTH
    # ========================================================

    def set_credentials(
        self,
        *,
        access_token: str | None = None,
        client_id: str | None = None,
    ) -> None:
        with self._lock:
            if access_token is not None:
                self.access_token = str(
                    access_token
                ).strip()

            if client_id is not None:
                self.client_id = str(
                    client_id
                ).strip()

    def _formatted_access_token(self) -> str:
        """
        FYERS DataSocket examples use:
            app_id:access_token

        If caller already passes that form, preserve it.
        """
        token = str(
            self.access_token or ""
        ).strip()

        client_id = str(
            self.client_id or ""
        ).strip()

        if not token:
            raise FyersWebSocketError(
                "FYERS access token is missing."
            )

        if ":" in token:
            return token

        if not client_id:
            raise FyersWebSocketError(
                "FYERS client_id is missing."
            )

        return f"{client_id}:{token}"

    # ========================================================
    # SYMBOL UNIVERSE
    # ========================================================

    def build_symbols(
        self,
        stock_symbols: Iterable[str] | None = None,
    ) -> list[str]:
        symbols: list[str] = []

        symbols.extend(
            Config.FYERS_WEBSOCKET_SYMBOLS
        )

        symbols.extend(
            get_candidate_sector_symbols()
        )

        if stock_symbols:
            symbols.extend(
                stock_symbols
            )

        return self._normalize_symbols(
            symbols
        )

    def set_symbols(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        normalized = self._normalize_symbols(
            symbols
        )

        with self._lock:
            self._symbols = normalized

        self.live_store.set_subscriptions(
            normalized
        )

        return normalized

    def add_symbols(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        additions = self._normalize_symbols(
            symbols
        )

        with self._lock:
            current = set(
                self._symbols
            )

            current.update(
                additions
            )

            self._symbols = sorted(
                current
            )

            socket = self._socket
            connected = self._connected

        self.live_store.add_subscriptions(
            additions
        )

        if (
            socket is not None
            and connected
            and additions
        ):
            try:
                socket.subscribe(
                    symbols=additions,
                    data_type=self.DATA_TYPE,
                )
            except Exception as exc:
                self._set_error(
                    f"Dynamic subscribe failed: {exc}"
                )

        return additions

    def remove_symbols(
        self,
        symbols: Iterable[str],
    ) -> list[str]:
        removals = self._normalize_symbols(
            symbols
        )

        with self._lock:
            current = set(
                self._symbols
            )

            for symbol in removals:
                current.discard(
                    symbol
                )

            self._symbols = sorted(
                current
            )

            socket = self._socket
            connected = self._connected

        self.live_store.remove_subscriptions(
            removals
        )

        if (
            socket is not None
            and connected
            and removals
        ):
            unsubscribe = getattr(
                socket,
                "unsubscribe",
                None,
            )

            if callable(unsubscribe):
                try:
                    unsubscribe(
                        symbols=removals,
                        data_type=self.DATA_TYPE,
                    )
                except Exception as exc:
                    self._set_error(
                        f"Dynamic unsubscribe failed: {exc}"
                    )

        return removals

    # ========================================================
    # START / STOP
    # ========================================================

    def start(
        self,
        *,
        access_token: str | None = None,
        client_id: str | None = None,
        symbols: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if not Config.FYERS_WEBSOCKET_ENABLED:
            return {
                "enabled": False,
                "running": False,
                "connected": False,
                "message": (
                    "FYERS WebSocket disabled by configuration."
                ),
            }

        self.set_credentials(
            access_token=access_token,
            client_id=client_id,
        )

        # Validate token shape before starting a background thread.
        self._formatted_access_token()

        if symbols is None:
            symbols = self.build_symbols()
        else:
            symbols = self.build_symbols(
                stock_symbols=symbols
            )

        self.set_symbols(
            symbols
        )

        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                self._running = True

                return self.status()

            self._stop_requested = False
            self._running = True
            self._last_error = ""

            self._thread = threading.Thread(
                target=self._run_socket,
                name="eagle-fyers-data-websocket",
                daemon=True,
            )

            self._thread.start()

        return self.status()

    def stop(
        self,
        *,
        clear_market_data: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._stop_requested = True
            self._running = False

            socket = self._socket

        if socket is not None:
            self._close_socket(
                socket
            )

        with self._lock:
            self._connected = False
            self._last_disconnect_at = (
                time.time()
            )

        self.live_store.mark_disconnected(
            "WebSocket stopped"
        )

        if clear_market_data:
            self.live_store.clear_ticks()

        return self.status()

    # ========================================================
    # SOCKET THREAD
    # ========================================================

    def _run_socket(self) -> None:
        try:
            data_ws = self._import_data_ws()

            token = (
                self._formatted_access_token()
            )

            socket = data_ws.FyersDataSocket(
                access_token=token,
                log_path="",
                litemode=False,
                write_to_file=False,
                reconnect=True,
                on_connect=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                on_message=self._on_message,
            )

            with self._lock:
                self._socket = socket

            logger.info(
                "Connecting FYERS Data WebSocket"
            )

            socket.connect()

        except Exception as exc:
            logger.exception(
                "FYERS WebSocket thread failed"
            )

            self._set_error(
                str(exc)
            )

            with self._lock:
                self._running = False
                self._connected = False
                self._last_disconnect_at = (
                    time.time()
                )

            self.live_store.mark_disconnected(
                str(exc)
            )

    # ========================================================
    # CALLBACKS
    # ========================================================

    def _on_connect(self) -> None:
        with self._lock:
            if self._stop_requested:
                return

            self._connected = True
            self._running = True
            self._last_connect_at = (
                time.time()
            )
            self._last_error = ""

            socket = self._socket
            symbols = list(
                self._symbols
            )

        self.live_store.mark_connected()

        logger.info(
            "FYERS WebSocket connected | symbols=%s",
            len(symbols),
        )

        if (
            socket is None
            or not symbols
        ):
            return

        try:
            socket.subscribe(
                symbols=symbols,
                data_type=self.DATA_TYPE,
            )

            # FYERS SDK examples call keep_running after subscription.
            keep_running = getattr(
                socket,
                "keep_running",
                None,
            )

            if callable(
                keep_running
            ):
                keep_running()

        except Exception as exc:
            logger.exception(
                "FYERS WebSocket subscription failed"
            )

            self._set_error(
                f"Subscription failed: {exc}"
            )

    def _on_message(
        self,
        message: Any,
    ) -> None:
        try:
            accepted = self.live_store.ingest(
                message
            )

            if accepted:
                return

            # Control/status messages are expected and need no warning.
            if isinstance(
                message,
                dict,
            ):
                msg_type = str(
                    message.get("type")
                    or message.get("s")
                    or ""
                ).lower()

                if msg_type in {
                    "cn",
                    "ful",
                    "sub",
                    "pong",
                    "success",
                    "ok",
                }:
                    return

        except Exception as exc:
            logger.exception(
                "FYERS tick ingestion failed"
            )

            self._set_error(
                f"Tick ingestion failed: {exc}"
            )

    def _on_error(
        self,
        message: Any,
    ) -> None:
        error = str(
            message or "Unknown FYERS WebSocket error"
        )

        logger.error(
            "FYERS WebSocket error: %s",
            error,
        )

        self._set_error(
            error
        )

        self.live_store.mark_error(
            error
        )

    def _on_close(
        self,
        message: Any,
    ) -> None:
        reason = str(
            message or "FYERS WebSocket closed"
        )

        logger.warning(
            "FYERS WebSocket closed: %s",
            reason,
        )

        with self._lock:
            self._connected = False
            self._last_disconnect_at = (
                time.time()
            )

            if self._stop_requested:
                self._running = False

        self.live_store.mark_disconnected(
            reason
        )

    # ========================================================
    # STATUS
    # ========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            thread_alive = bool(
                self._thread
                and self._thread.is_alive()
            )

            return {
                "enabled": bool(
                    Config.FYERS_WEBSOCKET_ENABLED
                ),
                "running": bool(
                    self._running
                    and thread_alive
                ),
                "connected": (
                    self._connected
                ),
                "thread_alive": (
                    thread_alive
                ),
                "symbols": len(
                    self._symbols
                ),
                "data_type": (
                    self.DATA_TYPE
                ),
                "last_connect_at": (
                    self._last_connect_at
                ),
                "last_disconnect_at": (
                    self._last_disconnect_at
                ),
                "last_error": (
                    self._last_error
                ),
                "live_store": (
                    self.live_store.status()
                ),
            }

    def snapshot(
        self,
    ) -> dict[str, dict[str, Any]]:
        return self.live_store.snapshot(
            allow_stale=False
        )

    # ========================================================
    # INTERNAL
    # ========================================================

    def _set_error(
        self,
        message: str,
    ) -> None:
        with self._lock:
            self._last_error = str(
                message or ""
            )

    @staticmethod
    def _close_socket(
        socket: Any,
    ) -> None:
        """
        FYERS SDK method names can vary by minor version.
        Try known safe close methods.
        """
        for method_name in (
            "close_connection",
            "close",
            "disconnect",
        ):
            method = getattr(
                socket,
                method_name,
                None,
            )

            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    continue

    @staticmethod
    def _normalize_symbols(
        symbols: Iterable[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for raw in symbols:
            symbol = (
                FyersService
                .normalize_fyers_symbol(
                    str(raw or "")
                )
            )

            if not symbol:
                continue

            symbol = (
                symbol.strip().upper()
            )

            if symbol in seen:
                continue

            seen.add(symbol)
            result.append(symbol)

        return result


# ============================================================
# SINGLETON
# ============================================================

_default_websocket_service = (
    FyersWebSocketService()
)


def get_fyers_websocket_service(
) -> FyersWebSocketService:
    return _default_websocket_service


# ============================================================
# APP.PY COMPATIBILITY HELPERS
# ============================================================

def start_market_websocket(
    *,
    access_token: str,
    client_id: str | None = None,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    return (
        _default_websocket_service
        .start(
            access_token=access_token,
            client_id=client_id,
            symbols=symbols,
        )
    )


def stop_market_websocket(
    *,
    clear_market_data: bool = False,
) -> dict[str, Any]:
    return (
        _default_websocket_service
        .stop(
            clear_market_data=(
                clear_market_data
            ),
        )
    )


def get_market_websocket_status(
) -> dict[str, Any]:
    return (
        _default_websocket_service
        .status()
    )


def get_live_market_snapshot(
) -> dict[str, dict[str, Any]]:
    return (
        _default_websocket_service
        .snapshot()
    )


def update_market_websocket_symbols(
    symbols: Iterable[str],
) -> dict[str, Any]:
    service = (
        _default_websocket_service
    )

    service.set_symbols(
        service.build_symbols(
            stock_symbols=symbols
        )
    )

    # If already connected, subscribe the dynamic symbols too.
    service.add_symbols(
        symbols
    )

    return service.status()
