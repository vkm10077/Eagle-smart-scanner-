from __future__ import annotations

"""
Eagle Smart Scanner - FYERS Service

Responsibilities
----------------
- FYERS API v3 authentication helpers
- REST client creation
- Quotes
- Historical candles
- Market status
- Profile
- Safe response validation
- Symbol normalization
- API error handling
- NO fake/random fallback data

This service is intentionally data-only.
It does NOT place orders.

The rest of Eagle Smart Scanner should use this service instead of
calling FYERS SDK methods directly.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from config import Config
from data.sector_map import normalize_stock_symbol, to_fyers_equity_symbol


logger = logging.getLogger(__name__)


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================

class FyersAPIError(RuntimeError):
    """Base FYERS service exception."""


class FyersNotConfiguredError(FyersAPIError):
    """Raised when required FYERS app credentials are missing."""


class FyersAuthenticationError(FyersAPIError):
    """Raised when authentication/access token is missing or rejected."""


class FyersDataError(FyersAPIError):
    """Raised when FYERS returns invalid, incomplete, or unusable data."""


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(frozen=True)
class Quote:
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
    timestamp: int | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


# ============================================================
# FYERS SERVICE
# ============================================================

class FyersService:
    """
    Central FYERS REST API wrapper for Eagle Smart Scanner.

    Notes
    -----
    - Lazy imports keep application startup stable if the SDK import fails.
    - The service never fabricates price/candle data.
    - Quote API requests are automatically split into batches of <= 50.
    """

    QUOTE_BATCH_SIZE = 50

    def __init__(
        self,
        client_id: str | None = None,
        secret_key: str | None = None,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self.client_id = str(
            client_id
            if client_id is not None
            else Config.FYERS_CLIENT_ID
        ).strip()

        self.secret_key = str(
            secret_key
            if secret_key is not None
            else Config.FYERS_SECRET_KEY
        ).strip()

        self.redirect_uri = str(
            redirect_uri
            if redirect_uri is not None
            else Config.FYERS_REDIRECT_URI
        ).strip()

        self.access_token = str(
            access_token
            if access_token is not None
            else Config.FYERS_ACCESS_TOKEN
        ).strip()

        self._client: Any | None = None
        self._client_lock = threading.RLock()

    # ========================================================
    # SDK IMPORTS
    # ========================================================

    @staticmethod
    def _import_fyers_module() -> Any:
        try:
            from fyers_apiv3 import fyersModel
            return fyersModel
        except Exception as exc:
            raise FyersAPIError(
                "FYERS Python SDK 'fyers-apiv3' is not installed or "
                f"could not be imported: {exc}"
            ) from exc

    # ========================================================
    # CONFIGURATION / AUTH STATE
    # ========================================================

    def is_app_configured(self) -> bool:
        return bool(
            self.client_id
            and self.secret_key
            and self.redirect_uri
        )

    def has_access_token(self) -> bool:
        return bool(self.access_token)

    def is_ready(self) -> bool:
        return self.is_app_configured() and self.has_access_token()

    def require_app_configuration(self) -> None:
        if not self.is_app_configured():
            raise FyersNotConfiguredError(
                "FYERS is not fully configured. Required environment "
                "variables: FYERS_CLIENT_ID, FYERS_SECRET_KEY, "
                "FYERS_REDIRECT_URI."
            )

    def require_access_token(self) -> None:
        if not self.has_access_token():
            raise FyersAuthenticationError(
                "FYERS access token is missing. Complete FYERS login "
                "and store a valid access token."
            )

    def set_access_token(self, token: str | None) -> None:
        token_value = str(token or "").strip()

        with self._client_lock:
            self.access_token = token_value
            self._client = None

    # ========================================================
    # AUTHENTICATION
    # ========================================================

    def create_auth_url(
        self,
        state: str = "eagle-smart-scanner",
    ) -> str:
        """
        Generate FYERS login URL.
        """
        self.require_app_configuration()

        fyers_model = self._import_fyers_module()

        try:
            session = fyers_model.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type="code",
                grant_type="authorization_code",
                state=state,
            )

            url = session.generate_authcode()

        except Exception as exc:
            raise FyersAuthenticationError(
                f"Unable to generate FYERS authentication URL: {exc}"
            ) from exc

        if not url:
            raise FyersAuthenticationError(
                "FYERS did not return an authentication URL."
            )

        return str(url)

    def exchange_auth_code(
        self,
        auth_code: str,
    ) -> str:
        """
        Exchange FYERS auth code for an access token.
        """
        self.require_app_configuration()

        code = str(auth_code or "").strip()

        if not code:
            raise FyersAuthenticationError(
                "FYERS auth code is empty."
            )

        fyers_model = self._import_fyers_module()

        try:
            session = fyers_model.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )

            session.set_token(code)
            response = session.generate_token()

        except Exception as exc:
            raise FyersAuthenticationError(
                f"FYERS token generation failed: {exc}"
            ) from exc

        if not isinstance(response, dict):
            raise FyersAuthenticationError(
                "FYERS returned an invalid token response."
            )

        if self._response_failed(response):
            raise FyersAuthenticationError(
                self._extract_error_message(
                    response,
                    default="FYERS token generation failed.",
                )
            )

        token = str(
            response.get("access_token")
            or response.get("token")
            or ""
        ).strip()

        if not token:
            raise FyersAuthenticationError(
                "FYERS token response did not contain access_token."
            )

        self.set_access_token(token)
        return token

    # ========================================================
    # CLIENT
    # ========================================================

    def get_client(self) -> Any:
        self.require_access_token()

        with self._client_lock:
            if self._client is not None:
                return self._client

            fyers_model = self._import_fyers_module()

            try:
                self._client = fyers_model.FyersModel(
                    client_id=self.client_id,
                    token=self.access_token,
                    is_async=False,
                    log_path="",
                )
            except TypeError:
                # Compatibility with SDK versions that do not accept log_path.
                self._client = fyers_model.FyersModel(
                    client_id=self.client_id,
                    token=self.access_token,
                    is_async=False,
                )
            except Exception as exc:
                raise FyersAuthenticationError(
                    f"Unable to create FYERS REST client: {exc}"
                ) from exc

            return self._client

    # ========================================================
    # PROFILE / TOKEN VALIDATION
    # ========================================================

    def get_profile(self) -> dict[str, Any]:
        client = self.get_client()

        try:
            response = client.get_profile()
        except Exception as exc:
            raise FyersAuthenticationError(
                f"FYERS profile request failed: {exc}"
            ) from exc

        return self._validate_dict_response(
            response,
            operation="profile",
        )

    def validate_access_token(self) -> bool:
        if not self.has_access_token():
            return False

        try:
            self.get_profile()
            return True
        except FyersAPIError:
            return False

    # ========================================================
    # MARKET STATUS
    # ========================================================

    def get_market_status(self) -> dict[str, Any]:
        client = self.get_client()

        try:
            response = client.market_status()
        except AttributeError:
            raise FyersAPIError(
                "Installed FYERS SDK does not expose market_status(). "
                "Update fyers-apiv3."
            )
        except Exception as exc:
            raise FyersAPIError(
                f"FYERS market status request failed: {exc}"
            ) from exc

        return self._validate_dict_response(
            response,
            operation="market status",
        )

    # ========================================================
    # QUOTES
    # ========================================================

    def get_quotes(
        self,
        symbols: str | Iterable[str],
    ) -> list[Quote]:
        """
        Fetch live/full quotes.

        FYERS Quotes API supports up to 50 symbols per request, therefore
        larger inputs are split automatically.
        """
        normalized = self._normalize_symbol_list(symbols)

        if not normalized:
            return []

        results: list[Quote] = []

        for start in range(0, len(normalized), self.QUOTE_BATCH_SIZE):
            batch = normalized[
                start : start + self.QUOTE_BATCH_SIZE
            ]

            response = self._fetch_quote_batch(batch)
            results.extend(self._parse_quotes_response(response))

        return results

    def get_quote(
        self,
        symbol: str,
    ) -> Quote:
        quotes = self.get_quotes([symbol])

        if not quotes:
            raise FyersDataError(
                f"No quote received for {symbol}."
            )

        return quotes[0]

    def get_ltp(
        self,
        symbol: str,
    ) -> float:
        quote = self.get_quote(symbol)

        if quote.ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
            raise FyersDataError(
                f"Invalid LTP for {quote.fyers_symbol}: {quote.ltp}"
            )

        return quote.ltp

    def _fetch_quote_batch(
        self,
        symbols: list[str],
    ) -> dict[str, Any]:
        client = self.get_client()

        payload = {
            "symbols": ",".join(symbols),
        }

        try:
            response = client.quotes(data=payload)
        except TypeError:
            response = client.quotes(payload)
        except Exception as exc:
            raise FyersAPIError(
                f"FYERS quotes request failed: {exc}"
            ) from exc

        return self._validate_dict_response(
            response,
            operation="quotes",
        )

    # ========================================================
    # HISTORY
    # ========================================================

    def get_history(
        self,
        symbol: str,
        resolution: str,
        range_from: str | int | date | datetime,
        range_to: str | int | date | datetime,
        *,
        cont_flag: int = 1,
        date_format: int = 1,
    ) -> list[Candle]:
        """
        Fetch historical OHLCV candles.

        For live prices use get_quote()/WebSocket, not History API.
        """
        fyers_symbol = self.normalize_fyers_symbol(symbol)

        if not fyers_symbol:
            raise FyersDataError("History symbol is empty.")

        resolution_value = str(resolution or "").strip()

        if not resolution_value:
            raise FyersDataError(
                "History resolution is empty."
            )

        range_from_value = self._format_history_boundary(
            range_from,
            date_format=date_format,
        )

        range_to_value = self._format_history_boundary(
            range_to,
            date_format=date_format,
        )

        payload = {
            "symbol": fyers_symbol,
            "resolution": resolution_value,
            "date_format": int(date_format),
            "range_from": range_from_value,
            "range_to": range_to_value,
            "cont_flag": int(cont_flag),
        }

        client = self.get_client()

        try:
            response = client.history(data=payload)
        except TypeError:
            response = client.history(payload)
        except Exception as exc:
            raise FyersAPIError(
                f"FYERS history request failed for "
                f"{fyers_symbol}: {exc}"
            ) from exc

        validated = self._validate_dict_response(
            response,
            operation=f"history {fyers_symbol}",
        )

        candles_raw = validated.get("candles")

        if not isinstance(candles_raw, list):
            raise FyersDataError(
                f"FYERS history response for {fyers_symbol} "
                "did not contain a valid candles list."
            )

        candles: list[Candle] = []

        for row in candles_raw:
            if not isinstance(row, (list, tuple)):
                continue

            if len(row) < 6:
                continue

            try:
                candle = Candle(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            except (TypeError, ValueError):
                continue

            if not self._valid_candle(candle):
                continue

            candles.append(candle)

        if not candles:
            raise FyersDataError(
                f"No valid candles received for {fyers_symbol}."
            )

        candles.sort(key=lambda item: item.timestamp)
        return candles

    def get_recent_history(
        self,
        symbol: str,
        resolution: str,
        *,
        days: int,
    ) -> list[Candle]:
        if days <= 0:
            raise ValueError("days must be greater than zero")

        end = date.today()
        start = end - timedelta(days=int(days))

        return self.get_history(
            symbol=symbol,
            resolution=resolution,
            range_from=start,
            range_to=end,
            date_format=1,
        )

    # ========================================================
    # SYMBOLS
    # ========================================================

    @staticmethod
    def normalize_fyers_symbol(
        symbol: str | None,
    ) -> str:
        """
        Preserve already-valid FYERS index symbols.
        Convert regular equity symbols to NSE:<SYMBOL>-EQ.
        """
        value = str(symbol or "").strip().upper()

        if not value:
            return ""

        if value.startswith("NSE:") and value.endswith("-INDEX"):
            return value

        if value.startswith("BSE:") or value.startswith("MCX:"):
            return value

        if value.startswith("NSE:") and "-" in value:
            return value

        return to_fyers_equity_symbol(value)

    @classmethod
    def _normalize_symbol_list(
        cls,
        symbols: str | Iterable[str],
    ) -> list[str]:
        if isinstance(symbols, str):
            raw_symbols = [
                item.strip()
                for item in symbols.split(",")
                if item.strip()
            ]
        else:
            raw_symbols = [
                str(item).strip()
                for item in symbols
                if str(item).strip()
            ]

        result: list[str] = []
        seen: set[str] = set()

        for symbol in raw_symbols:
            normalized = cls.normalize_fyers_symbol(symbol)

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(normalized)

        return result

    # ========================================================
    # RESPONSE PARSING
    # ========================================================

    def _parse_quotes_response(
        self,
        response: dict[str, Any],
    ) -> list[Quote]:
        data = response.get("d")

        if data is None:
            data = response.get("data")

        if not isinstance(data, list):
            raise FyersDataError(
                "FYERS quotes response did not contain a valid data list."
            )

        quotes: list[Quote] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            values = item.get("v")
            if not isinstance(values, dict):
                values = item

            fyers_symbol = str(
                item.get("n")
                or values.get("symbol")
                or values.get("short_name")
                or ""
            ).strip()

            if not fyers_symbol:
                continue

            ltp = self._number(
                values,
                "lp",
                "ltp",
                "last_price",
                default=0.0,
            )

            if ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
                logger.warning(
                    "Ignoring invalid zero/negative quote for %s",
                    fyers_symbol,
                )
                continue

            quote = Quote(
                symbol=normalize_stock_symbol(fyers_symbol),
                fyers_symbol=fyers_symbol,
                ltp=ltp,
                change=self._number(
                    values,
                    "ch",
                    "change",
                    default=0.0,
                ),
                change_percent=self._number(
                    values,
                    "chp",
                    "change_percent",
                    "p_change",
                    default=0.0,
                ),
                open=self._number(
                    values,
                    "open_price",
                    "open",
                    default=0.0,
                ),
                high=self._number(
                    values,
                    "high_price",
                    "high",
                    default=0.0,
                ),
                low=self._number(
                    values,
                    "low_price",
                    "low",
                    default=0.0,
                ),
                previous_close=self._number(
                    values,
                    "prev_close_price",
                    "prev_close",
                    "previous_close",
                    default=0.0,
                ),
                volume=self._number(
                    values,
                    "volume",
                    "vol_traded_today",
                    default=0.0,
                ),
                bid=self._number(
                    values,
                    "bid",
                    "bid_price",
                    default=0.0,
                ),
                ask=self._number(
                    values,
                    "ask",
                    "ask_price",
                    default=0.0,
                ),
                timestamp=self._int_or_none(
                    values.get("tt")
                    or values.get("timestamp")
                ),
                raw=item,
            )

            quotes.append(quote)

        return quotes

    # ========================================================
    # VALIDATION
    # ========================================================

    @classmethod
    def _validate_dict_response(
        cls,
        response: Any,
        *,
        operation: str,
    ) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise FyersDataError(
                f"FYERS {operation} returned a non-dictionary response."
            )

        if cls._response_failed(response):
            message = cls._extract_error_message(
                response,
                default=f"FYERS {operation} failed.",
            )

            if cls._looks_like_auth_error(response, message):
                raise FyersAuthenticationError(message)

            raise FyersAPIError(message)

        return response

    @staticmethod
    def _response_failed(
        response: dict[str, Any],
    ) -> bool:
        status = str(
            response.get("s")
            or response.get("status")
            or ""
        ).strip().lower()

        code = response.get("code")

        if status in {
            "error",
            "failed",
            "fail",
            "failure",
        }:
            return True

        if isinstance(code, int) and code < 0:
            return True

        return False

    @staticmethod
    def _extract_error_message(
        response: dict[str, Any],
        *,
        default: str,
    ) -> str:
        for key in (
            "message",
            "msg",
            "error",
            "description",
        ):
            value = response.get(key)

            if value:
                return str(value)

        return default

    @staticmethod
    def _looks_like_auth_error(
        response: dict[str, Any],
        message: str,
    ) -> bool:
        text = str(message or "").lower()
        code = response.get("code")

        auth_words = (
            "token",
            "auth",
            "unauthorized",
            "invalid app",
            "session",
            "access denied",
        )

        if any(word in text for word in auth_words):
            return True

        return code in {
            -8,
            -15,
            -16,
            -17,
        }

    @staticmethod
    def _valid_candle(
        candle: Candle,
    ) -> bool:
        if candle.timestamp <= 0:
            return False

        prices = (
            candle.open,
            candle.high,
            candle.low,
            candle.close,
        )

        if not Config.ALLOW_ZERO_PRICE:
            if any(value <= 0 for value in prices):
                return False

        if candle.high < candle.low:
            return False

        if candle.high < max(
            candle.open,
            candle.close,
        ):
            return False

        if candle.low > min(
            candle.open,
            candle.close,
        ):
            return False

        if candle.volume < 0:
            return False

        return True

    # ========================================================
    # SMALL UTILITIES
    # ========================================================

    @staticmethod
    def _number(
        data: dict[str, Any],
        *keys: str,
        default: float = 0.0,
    ) -> float:
        for key in keys:
            value = data.get(key)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                continue

        return float(default)

    @staticmethod
    def _int_or_none(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_history_boundary(
        value: str | int | date | datetime,
        *,
        date_format: int,
    ) -> str | int:
        if int(date_format) == 0:
            if isinstance(value, datetime):
                return int(value.timestamp())

            if isinstance(value, date):
                dt = datetime.combine(
                    value,
                    datetime.min.time(),
                )
                return int(dt.timestamp())

            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise FyersDataError(
                    f"Invalid epoch history boundary: {value}"
                ) from exc

        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")

        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")

        text = str(value or "").strip()

        if not text:
            raise FyersDataError(
                "History date boundary is empty."
            )

        return text


# ============================================================
# DEFAULT SINGLETON
# ============================================================

_default_service: FyersService | None = None
_default_service_lock = threading.Lock()


def get_fyers_service() -> FyersService:
    global _default_service

    if _default_service is not None:
        return _default_service

    with _default_service_lock:
        if _default_service is None:
            _default_service = FyersService()

    return _default_service


# ============================================================
# BACKWARD-COMPATIBLE MODULE HELPERS
# ============================================================

def get_auth_url(
    state: str = "eagle-smart-scanner",
) -> str:
    return get_fyers_service().create_auth_url(
        state=state,
    )


def generate_access_token(
    auth_code: str,
) -> str:
    return get_fyers_service().exchange_auth_code(
        auth_code,
    )


def get_quotes(
    symbols: str | Iterable[str],
) -> list[Quote]:
    return get_fyers_service().get_quotes(
        symbols,
    )


def get_quote(
    symbol: str,
) -> Quote:
    return get_fyers_service().get_quote(
        symbol,
    )


def get_history(
    symbol: str,
    resolution: str,
    range_from: str | int | date | datetime,
    range_to: str | int | date | datetime,
    *,
    cont_flag: int = 1,
    date_format: int = 1,
) -> list[Candle]:
    return get_fyers_service().get_history(
        symbol=symbol,
        resolution=resolution,
        range_from=range_from,
        range_to=range_to,
        cont_flag=cont_flag,
        date_format=date_format,
    )
