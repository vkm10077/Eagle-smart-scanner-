from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import pytz
from fyers_apiv3 import fyersModel



logger = logging.getLogger(__name__)


class FyersServiceError(RuntimeError):
    """FYERS authentication, quotes और historical-data errors."""


class FyersService:
    """
    FYERS API v3 live-data service.

    Fixes included:
    - Index symbols पर गलत -EQ suffix नहीं जोड़ा जाता।
    - Daily historical resolution 1D भेजा जाता है।
    - History payload से unsupported oi_flag हटाया गया है।
    - बड़े date ranges को 365-day chunks में fetch किया जाता है।
    """

    MAX_QUOTE_SYMBOLS_PER_REQUEST = 50
    MAX_HISTORY_DAYS_PER_REQUEST = 365

    def __init__(
        self,
        access_token: Optional[str] = None,
        client_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        response_type: str = "code",
        grant_type: str = "authorization_code",
        log_path: str = "",
        **_: Any,
    ) -> None:
        # Current Eagle Smart Scanner config.py exposes plain constants.
        # Do not depend on old FyersConfig/load_fyers_config objects.
        self.client_id = self._clean_text(
            client_id
            or os.getenv("FYERS_CLIENT_ID")
            or os.getenv("FYERS_APP_ID")
        )
        self.secret_key = self._clean_text(
            secret_key
            or os.getenv("FYERS_SECRET_KEY")
            or os.getenv("FYERS_SECRET_ID")
        )
        self.redirect_uri = self._clean_text(
            redirect_uri
            or os.getenv("FYERS_REDIRECT_URI")
        )
        self.response_type = self._clean_text(response_type) or "code"
        self.grant_type = (
            self._clean_text(grant_type)
            or "authorization_code"
        )
        self.log_path = self._clean_text(
            log_path
            or os.getenv("FYERS_LOG_PATH", "")
        )

        self.access_token = self._clean_text(access_token)
        self._client: Optional[fyersModel.FyersModel] = None

        if self.access_token:
            self._client = self._build_client(self.access_token)

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    @staticmethod
    def _clean_text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Examples:
        RELIANCE          -> NSE:RELIANCE-EQ
        RELIANCE-EQ       -> NSE:RELIANCE-EQ
        NSE:RELIANCE-EQ   -> NSE:RELIANCE-EQ
        NSE:NIFTY50-INDEX -> NSE:NIFTY50-INDEX
        NSE:NIFTYBEES-EQ  -> NSE:NIFTYBEES-EQ
        """

        cleaned = str(symbol or "").strip().upper()

        if not cleaned:
            raise FyersServiceError("Stock symbol is required.")

        if ":" in cleaned:
            exchange, instrument = cleaned.split(":", 1)
            exchange = exchange.strip()
            instrument = instrument.strip()

            if not exchange or not instrument:
                raise FyersServiceError(
                    f"Invalid FYERS symbol format: {symbol}"
                )

            # किसी existing FYERS suffix को न बदलें।
            if "-" in instrument:
                return f"{exchange}:{instrument}"

            if exchange == "NSE":
                instrument = f"{instrument}-EQ"

            return f"{exchange}:{instrument}"

        # Exchange prefix नहीं है।
        if "-" in cleaned:
            return f"NSE:{cleaned}"

        return f"NSE:{cleaned}-EQ"

    @staticmethod
    def clean_display_symbol(symbol: str) -> str:
        cleaned = str(symbol or "").strip().upper()
        cleaned = cleaned.replace("NSE:", "")

        if cleaned.endswith("-EQ"):
            cleaned = cleaned[:-3]

        return cleaned

    @staticmethod
    def _chunks(
        values: Sequence[str],
        size: int,
    ) -> Iterable[Sequence[str]]:
        for start in range(0, len(values), size):
            yield values[start:start + size]

    @staticmethod
    def _require_success(
        response: Any,
        operation: str,
    ) -> Dict[str, Any]:
        if not isinstance(response, dict):
            raise FyersServiceError(
                f"{operation} failed: invalid FYERS response."
            )

        status = str(response.get("s", "")).strip().lower()
        code = response.get("code")
        message = (
            response.get("message")
            or response.get("msg")
            or "Unknown FYERS API error."
        )

        if status not in {"ok", "success"}:
            code_text = (
                f" (code {code})"
                if code is not None
                else ""
            )

            raise FyersServiceError(
                f"{operation} failed{code_text}: {message}"
            )

        return response

    # =========================================================
    # AUTHENTICATION
    # =========================================================

    def create_login_url(self, **_: Any) -> str:
        if not self.client_id:
            raise FyersServiceError("FYERS_CLIENT_ID is missing.")
        if not self.secret_key:
            raise FyersServiceError("FYERS_SECRET_KEY is missing.")
        if not self.redirect_uri:
            raise FyersServiceError("FYERS_REDIRECT_URI is missing.")

        try:
            auth_session = fyersModel.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type=self.response_type,
                grant_type=self.grant_type,
            )

            login_url = auth_session.generate_authcode()

            if not login_url:
                raise FyersServiceError(
                    "FYERS login URL could not be generated."
                )

            return str(login_url)

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception("FYERS login URL generation failed.")
            raise FyersServiceError(
                f"FYERS login URL generation failed: {exc}"
            ) from exc

    generate_auth_url = create_login_url
    generate_login_url = create_login_url
    get_auth_url = create_login_url
    get_login_url = create_login_url
    create_auth_url = create_login_url

    def exchange_auth_code(
        self,
        auth_code: str = "",
        code: str = "",
        authorization_code: str = "",
        **_: Any,
    ) -> str:
        clean_code = self._clean_text(
            auth_code or code or authorization_code
        )

        if not clean_code:
            raise FyersServiceError(
                "FYERS auth code is missing."
            )

        try:
            auth_session = fyersModel.SessionModel(
                client_id=self.client_id,
                secret_key=self.secret_key,
                redirect_uri=self.redirect_uri,
                response_type=self.response_type,
                grant_type=self.grant_type,
            )

            auth_session.set_token(clean_code)
            response = auth_session.generate_token()

            validated = self._require_success(
                response,
                "FYERS access-token generation",
            )

            access_token = self._clean_text(
                validated.get("access_token")
            )

            if not access_token:
                raise FyersServiceError(
                    "FYERS returned success but access_token is missing."
                )

            self.set_access_token(access_token)
            return access_token

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception("FYERS auth-code exchange failed.")
            raise FyersServiceError(
                f"FYERS auth-code exchange failed: {exc}"
            ) from exc

    generate_access_token = exchange_auth_code
    exchange_code_for_token = exchange_auth_code
    create_access_token = exchange_auth_code

    def set_access_token(self, access_token: str) -> None:
        clean_token = self._clean_text(access_token)

        if not clean_token:
            raise FyersServiceError(
                "FYERS access token is required."
            )

        self.access_token = clean_token
        self._client = self._build_client(clean_token)

    def _build_client(
        self,
        access_token: str,
    ) -> fyersModel.FyersModel:
        if not self.client_id:
            raise FyersServiceError(
                "FYERS_CLIENT_ID is missing; client cannot be created."
            )

        try:
            return fyersModel.FyersModel(
                client_id=self.client_id,
                token=access_token,
                is_async=False,
                log_path=self.log_path,
            )
        except Exception as exc:
            logger.exception("FYERS client creation failed.")
            raise FyersServiceError(
                f"FYERS client creation failed: {exc}"
            ) from exc

    def get_client(self) -> fyersModel.FyersModel:
        if self._client is None:
            if not self.access_token:
                raise FyersServiceError(
                    "FYERS access token is not available. "
                    "Please log in again."
                )

            self._client = self._build_client(
                self.access_token
            )

        return self._client

    def verify_access_token(self) -> bool:
        try:
            self.get_profile()
            return True
        except FyersServiceError:
            return False

    # =========================================================
    # PROFILE
    # =========================================================

    def get_profile(self, **_: Any) -> Dict[str, Any]:
        try:
            response = self.get_client().get_profile()
            validated = self._require_success(
                response,
                "FYERS profile request",
            )

            profile = validated.get("data")
            return profile if isinstance(profile, dict) else {}

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception("FYERS profile request failed.")
            raise FyersServiceError(
                f"FYERS profile request failed: {exc}"
            ) from exc

    profile = get_profile
    fetch_profile = get_profile
    user_profile = get_profile

    # =========================================================
    # LIVE QUOTES
    # =========================================================

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        results = self.get_quotes([symbol])

        if not results:
            raise FyersServiceError(
                f"No live quote was returned for {symbol}."
            )

        return results[0]

    def get_quotes(
        self,
        symbols: Sequence[str],
        request_delay_seconds: float = 0.20,
    ) -> List[Dict[str, Any]]:
        if not symbols:
            return []

        normalized_symbols: List[str] = []
        seen = set()

        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)

            if normalized not in seen:
                normalized_symbols.append(normalized)
                seen.add(normalized)

        all_quotes: List[Dict[str, Any]] = []
        batches = list(
            self._chunks(
                normalized_symbols,
                self.MAX_QUOTE_SYMBOLS_PER_REQUEST,
            )
        )

        for batch_index, batch in enumerate(batches):
            try:
                response = self.get_client().quotes(
                    data={"symbols": ",".join(batch)}
                )

                validated = self._require_success(
                    response,
                    "FYERS quotes request",
                )

                rows = validated.get("d", [])

                if not isinstance(rows, list):
                    rows = []

                for row in rows:
                    parsed = self._parse_quote_row(row)

                    if parsed:
                        all_quotes.append(parsed)

            except FyersServiceError:
                raise

            except Exception as exc:
                logger.exception("FYERS quote batch failed.")
                raise FyersServiceError(
                    f"FYERS quote request failed: {exc}"
                ) from exc

            if (
                request_delay_seconds > 0
                and batch_index < len(batches) - 1
            ):
                time.sleep(request_delay_seconds)

        return all_quotes

    def _parse_quote_row(
        self,
        quote_row: Any,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(quote_row, dict):
            return None

        values = quote_row.get("v")

        if not isinstance(values, dict):
            return None

        fyers_symbol = self._clean_text(
            quote_row.get("n")
            or values.get("symbol")
            or ""
        )

        if not fyers_symbol:
            return None

        def number(
            key: str,
            default: Optional[float] = None,
        ) -> Optional[float]:
            value = values.get(key)

            if value in {None, ""}:
                return default

            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        return {
            "symbol": fyers_symbol,
            "display_symbol": self.clean_display_symbol(
                fyers_symbol
            ),
            "current_price": number("lp"),
            "open": number("open_price"),
            "high": number("high_price"),
            "low": number("low_price"),
            "previous_close": number("prev_close_price"),
            "change": number("ch"),
            "change_percent": number("chp"),
            "volume": number("volume"),
            "bid": number("bid"),
            "ask": number("ask"),
            "spread": number("spread"),
            "description": values.get("description"),
            "exchange": values.get("exchange"),
            "short_name": values.get("short_name"),
            "original_name": values.get("original_name"),
            "timestamp": values.get("tt"),
        }

    # =========================================================
    # HISTORICAL CANDLES
    # =========================================================

    def get_historical_data(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        date_format: str = "1",
        continuous: str = "1",
        open_interest: str = "0",
    ) -> pd.DataFrame:
        """
        FYERS historical OHLCV candles return करता है।

        open_interest argument compatibility के लिए रखा गया है,
        लेकिन History API payload में oi_flag नहीं भेजा जाता।
        """

        del open_interest

        normalized_symbol = self.normalize_symbol(symbol)
        clean_resolution = self._clean_text(
            resolution
        ).upper()

        if clean_resolution == "D":
            clean_resolution = "1D"

        clean_from = self._clean_text(range_from)
        clean_to = self._clean_text(range_to)

        if not clean_resolution:
            raise FyersServiceError(
                "Historical-data resolution is required."
            )

        if not clean_from:
            raise FyersServiceError(
                "Historical-data start date is required."
            )

        if not clean_to:
            raise FyersServiceError(
                "Historical-data end date is required."
            )

        payload = {
            "symbol": normalized_symbol,
            "resolution": clean_resolution,
            "date_format": self._clean_text(date_format) or "1",
            "range_from": clean_from,
            "range_to": clean_to,
            "cont_flag": self._clean_text(continuous) or "1",
        }

        logger.info(
            "FYERS history | symbol=%s | resolution=%s | from=%s | to=%s",
            normalized_symbol,
            clean_resolution,
            clean_from,
            clean_to,
        )

        try:
            response = self.get_client().history(
                data=payload
            )

            validated = self._require_success(
                response,
                f"FYERS historical-data request for "
                f"{normalized_symbol}",
            )

            candles = validated.get("candles")

            if not isinstance(candles, list):
                raise FyersServiceError(
                    f"No historical candles were returned for "
                    f"{normalized_symbol}."
                )

            dataframe = self._candles_to_dataframe(
                candles
            )

            if dataframe.empty:
                raise FyersServiceError(
                    f"Historical data is empty for "
                    f"{normalized_symbol}."
                )

            return dataframe

        except FyersServiceError:
            raise

        except Exception as exc:
            logger.exception(
                "FYERS historical-data request failed."
            )
            raise FyersServiceError(
                f"FYERS historical-data request failed for "
                f"{normalized_symbol}: {exc}"
            ) from exc

    def get_daily_history(
        self,
        symbol: str,
        days: int = 420,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Daily candles को 365-day chunks में fetch करता है।
        """

        try:
            requested_days = int(days)
        except (TypeError, ValueError) as exc:
            raise FyersServiceError(
                "Historical days must be an integer."
            ) from exc

        if requested_days < 1:
            raise FyersServiceError(
                "Historical days must be at least 1."
            )

        final_end_date = end_date or date.today()
        final_start_date = (
            final_end_date
            - timedelta(days=requested_days)
        )

        frames: List[pd.DataFrame] = []
        chunk_start = final_start_date

        while chunk_start <= final_end_date:
            chunk_end = min(
                chunk_start
                + timedelta(
                    days=self.MAX_HISTORY_DAYS_PER_REQUEST
                ),
                final_end_date,
            )

            frame = self.get_historical_data(
                symbol=symbol,
                resolution="1D",
                range_from=chunk_start.strftime(
                    "%Y-%m-%d"
                ),
                range_to=chunk_end.strftime(
                    "%Y-%m-%d"
                ),
                date_format="1",
                continuous="1",
            )

            if not frame.empty:
                frames.append(frame)

            chunk_start = chunk_end + timedelta(days=1)

            if chunk_start <= final_end_date:
                time.sleep(0.10)

        if not frames:
            raise FyersServiceError(
                f"Historical data is empty for "
                f"{self.normalize_symbol(symbol)}."
            )

        combined = pd.concat(
            frames,
            ignore_index=True,
        )

        combined.sort_values(
            "timestamp",
            inplace=True,
        )

        combined.drop_duplicates(
            subset=["timestamp"],
            keep="last",
            inplace=True,
        )

        combined.reset_index(
            drop=True,
            inplace=True,
        )

        return combined

    @staticmethod
    def _candles_to_dataframe(
        candles: List[Any],
    ) -> pd.DataFrame:
        valid_rows: List[List[Any]] = []

        for candle in candles:
            if (
                isinstance(candle, (list, tuple))
                and len(candle) >= 6
            ):
                valid_rows.append(
                    list(candle[:6])
                )

        columns = [
            "datetime",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        if not valid_rows:
            return pd.DataFrame(columns=columns)

        dataframe = pd.DataFrame(
            valid_rows,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        for column in [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

        dataframe.dropna(
            subset=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
            inplace=True,
        )

        dataframe["timestamp"] = (
            dataframe["timestamp"].astype("int64")
        )

        dataframe["datetime"] = pd.to_datetime(
            dataframe["timestamp"],
            unit="s",
            utc=True,
        ).dt.tz_convert("Asia/Kolkata")

        dataframe.sort_values(
            "timestamp",
            inplace=True,
        )

        dataframe.drop_duplicates(
            subset=["timestamp"],
            keep="last",
            inplace=True,
        )

        dataframe.reset_index(
            drop=True,
            inplace=True,
        )

        return dataframe[
            [
                "datetime",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ]

    # =========================================================
    # COMPATIBILITY / HEALTH HELPERS
    # =========================================================

    def validate_session(self) -> Dict[str, Any]:
        profile = self.get_profile()
        return {
            "valid": True,
            "profile": profile,
            "message": "FYERS session is valid.",
        }

    validate_access_token = validate_session
    check_session = validate_session

    def health_check(self) -> Dict[str, Any]:
        try:
            result = self.validate_session()
            return {
                "ok": True,
                "authenticated": True,
                "profile": result.get("profile"),
            }
        except Exception as exc:
            return {
                "ok": False,
                "authenticated": False,
                "error": str(exc),
            }

    def get_ltp(self, symbol: str) -> float:
        quote = self.get_quote(symbol)
        value = quote.get("current_price")
        try:
            ltp = float(value)
        except (TypeError, ValueError) as exc:
            raise FyersServiceError(
                f"Invalid LTP returned for {symbol}."
            ) from exc

        if ltp <= 0:
            raise FyersServiceError(
                f"Non-positive LTP returned for {symbol}."
            )

        return ltp

    quotes = get_quotes
    fetch_quotes = get_quotes

    # =========================================================
    # MARKET TIME
    # =========================================================

    @staticmethod
    def india_now() -> datetime:
        india_timezone = pytz.timezone(
            "Asia/Kolkata"
        )

        return datetime.now(
            india_timezone
        )

    @classmethod
    def is_regular_market_open(cls) -> bool:
        now = cls.india_now()

        if now.weekday() >= 5:
            return False

        market_open = now.replace(
            hour=9,
            minute=15,
            second=0,
            microsecond=0,
        )

        market_close = now.replace(
            hour=15,
            minute=30,
            second=0,
            microsecond=0,
        )

        return market_open <= now <= market_close
