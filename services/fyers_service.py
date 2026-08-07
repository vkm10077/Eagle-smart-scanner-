from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fyers_apiv3 import fyersModel

from config import Config
from utils.helpers import (
    clean_text,
    mask_secret,
    normalize_symbol,
    to_fyers_symbol,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("services.fyers_service")


class FyersConfigurationError(RuntimeError):
    """Raised when required FYERS configuration is missing."""


class FyersAuthenticationError(RuntimeError):
    """Raised when FYERS authentication fails."""


class FyersAPIError(RuntimeError):
    """Raised when FYERS returns an unsuccessful API response."""


@dataclass
class FyersTokenResult:
    success: bool
    access_token: str = ""
    refresh_token: str = ""
    message: str = ""
    raw_response: dict[str, Any] | None = None

    def to_dict(
        self,
        *,
        include_token: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "has_access_token": bool(
                self.access_token
            ),
            "has_refresh_token": bool(
                self.refresh_token
            ),
            "raw_response": (
                self.raw_response
                or {}
            ),
        }

        if include_token:
            data["access_token"] = (
                self.access_token
            )
            data["refresh_token"] = (
                self.refresh_token
            )

        return data


class FyersService:
    """
    FYERS API v3 service for Eagle Smart Scanner.

    Responsibilities:
    - Generate FYERS login URL
    - Exchange auth code
    - Create authenticated client
    - Validate token
    - Profile / funds / holdings / positions
    - Live quotes
    - Historical candles
    - Intraday candle sets
    - Swing daily candle sets
    - Live LTP
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        secret_key: str | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        self.client_id = clean_text(
            client_id
            or Config.FYERS_CLIENT_ID
        )

        self.secret_key = clean_text(
            secret_key
            or Config.FYERS_SECRET_KEY
        )

        self.redirect_uri = clean_text(
            redirect_uri
            or Config.FYERS_REDIRECT_URI
        )

        self._client_lock = (
            threading.RLock()
        )

        self._clients: dict[
            str,
            Any,
        ] = {}

    # ==========================================================
    # CONFIGURATION
    # ==========================================================

    def configuration_status(
        self,
    ) -> dict[str, Any]:
        missing_fields: list[str] = []

        if not self.client_id:
            missing_fields.append(
                "FYERS_CLIENT_ID"
            )

        if not self.secret_key:
            missing_fields.append(
                "FYERS_SECRET_KEY"
            )

        if not self.redirect_uri:
            missing_fields.append(
                "FYERS_REDIRECT_URI"
            )

        return {
            "configured": (
                not missing_fields
            ),
            "missing_fields": (
                missing_fields
            ),
            "client_id": (
                mask_secret(
                    self.client_id
                )
                if self.client_id
                else ""
            ),
            "redirect_uri": (
                self.redirect_uri
            ),
            "checked_at": (
                utc_now().isoformat()
            ),
        }

    def validate_configuration(
        self,
    ) -> None:
        status = (
            self.configuration_status()
        )

        if not status["configured"]:
            missing = ", ".join(
                status[
                    "missing_fields"
                ]
            )

            raise FyersConfigurationError(
                (
                    "Missing FYERS "
                    f"configuration: {missing}"
                )
            )

    # ==========================================================
    # LOGIN
    # ==========================================================

    def _create_session_model(
        self,
    ) -> Any:
        self.validate_configuration()

        return fyersModel.SessionModel(
            client_id=self.client_id,
            secret_key=self.secret_key,
            redirect_uri=self.redirect_uri,
            response_type="code",
            grant_type=(
                "authorization_code"
            ),
        )

    def generate_login_url(
        self,
    ) -> str:
        try:
            session_model = (
                self._create_session_model()
            )

            login_url = (
                session_model
                .generate_authcode()
            )

            login_url = clean_text(
                login_url
            )

            if not login_url:
                raise FyersAuthenticationError(
                    (
                        "FYERS did not generate "
                        "a login URL."
                    )
                )

            logger.info(
                (
                    "FYERS login URL "
                    "generated."
                ),
                extra=build_log_extra(
                    component=(
                        "fyers_service"
                    ),
                    event=(
                        "login_url_generated"
                    ),
                    status="success",
                ),
            )

            return login_url

        except FyersConfigurationError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                (
                    "Unable to generate "
                    "FYERS login URL"
                ),
                exception=exception,
                component=(
                    "fyers_service"
                ),
                error_code=(
                    "FYERS_LOGIN_URL_FAILED"
                ),
            )

            raise FyersAuthenticationError(
                (
                    "Unable to generate "
                    "FYERS login URL."
                )
            ) from exception

    def exchange_auth_code(
        self,
        auth_code: str,
    ) -> FyersTokenResult:
        normalized_auth_code = (
            clean_text(
                auth_code
            )
        )

        if not normalized_auth_code:
            return FyersTokenResult(
                success=False,
                message=(
                    "FYERS authorization "
                    "code is missing."
                ),
            )

        try:
            session_model = (
                self._create_session_model()
            )

            session_model.set_token(
                normalized_auth_code
            )

            response = (
                session_model
                .generate_token()
            )

            if not isinstance(
                response,
                dict,
            ):
                return FyersTokenResult(
                    success=False,
                    message=(
                        "FYERS returned an "
                        "invalid token response."
                    ),
                    raw_response={
                        "response": str(
                            response
                        )
                    },
                )

            access_token = clean_text(
                response.get(
                    "access_token"
                )
            )

            refresh_token = clean_text(
                response.get(
                    "refresh_token"
                )
            )

            response_code = (
                response.get(
                    "code"
                )
            )

            response_status = (
                clean_text(
                    response.get("s")
                    or response.get(
                        "status"
                    )
                )
                .casefold()
            )

            success = bool(
                access_token
            )

            if response_status in {
                "error",
                "failed",
                "failure",
            }:
                success = False

            if isinstance(
                response_code,
                int,
            ):
                if response_code < 0:
                    success = False

            message = clean_text(
                response.get(
                    "message"
                )
                or response.get(
                    "msg"
                )
            )

            if success:
                logger.info(
                    (
                        "FYERS access "
                        "token generated."
                    ),
                    extra=build_log_extra(
                        component=(
                            "fyers_service"
                        ),
                        event=(
                            "access_token_generated"
                        ),
                        status="success",
                    ),
                )

                return FyersTokenResult(
                    success=True,
                    access_token=(
                        access_token
                    ),
                    refresh_token=(
                        refresh_token
                    ),
                    message=(
                        message
                        or (
                            "FYERS login "
                            "successful."
                        )
                    ),
                    raw_response=response,
                )

            logger.warning(
                (
                    "FYERS token generation "
                    "failed: %s"
                ),
                (
                    message
                    or (
                        "Unknown FYERS "
                        "error"
                    )
                ),
                extra=build_log_extra(
                    component=(
                        "fyers_service"
                    ),
                    event=(
                        "access_token_failed"
                    ),
                    status="failed",
                    error_code=(
                        response_code
                    ),
                ),
            )

            return FyersTokenResult(
                success=False,
                message=(
                    message
                    or (
                        "FYERS authentication "
                        "failed."
                    )
                ),
                raw_response=response,
            )

        except FyersConfigurationError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                (
                    "FYERS auth-code "
                    "exchange failed"
                ),
                exception=exception,
                component=(
                    "fyers_service"
                ),
                error_code=(
                    "FYERS_TOKEN_EXCHANGE_FAILED"
                ),
            )

            return FyersTokenResult(
                success=False,
                message=(
                    "Unable to complete "
                    "FYERS authentication."
                ),
                raw_response={
                    "error": str(
                        exception
                    )
                },
            )

    # ==========================================================
    # CLIENT
    # ==========================================================

    def create_client(
        self,
        access_token: str,
        *,
        use_cache: bool = True,
    ) -> Any:
        normalized_token = clean_text(
            access_token
        )

        if not normalized_token:
            raise FyersAuthenticationError(
                (
                    "FYERS access token "
                    "is missing."
                )
            )

        self.validate_configuration()

        cache_key = (
            normalized_token[-24:]
        )

        with self._client_lock:
            if (
                use_cache
                and cache_key
                in self._clients
            ):
                return (
                    self._clients[
                        cache_key
                    ]
                )

            try:
                client = (
                    fyersModel.FyersModel(
                        client_id=(
                            self.client_id
                        ),
                        token=(
                            normalized_token
                        ),
                        is_async=False,
                        log_path="",
                    )
                )

                if use_cache:
                    self._clients[
                        cache_key
                    ] = client

                return client

            except Exception as exception:
                log_exception(
                    logger,
                    (
                        "Unable to create "
                        "FYERS client"
                    ),
                    exception=exception,
                    component=(
                        "fyers_service"
                    ),
                    error_code=(
                        "FYERS_CLIENT_FAILED"
                    ),
                )

                raise FyersAuthenticationError(
                    (
                        "Unable to initialize "
                        "FYERS client."
                    )
                ) from exception

    def clear_client_cache(
        self,
    ) -> None:
        with self._client_lock:
            self._clients.clear()

    # ==========================================================
    # RESPONSE HANDLING
    # ==========================================================

    @staticmethod
    def _response_is_successful(
        response: Any,
    ) -> bool:
        if not isinstance(
            response,
            dict,
        ):
            return False

        status = (
            clean_text(
                response.get("s")
                or response.get(
                    "status"
                )
            )
            .casefold()
        )

        code = response.get(
            "code"
        )

        if status in {
            "error",
            "failed",
            "failure",
        }:
            return False

        if (
            isinstance(
                code,
                int,
            )
            and code < 0
        ):
            return False

        return True

    @staticmethod
    def _response_message(
        response: Any,
        default: str,
    ) -> str:
        if not isinstance(
            response,
            dict,
        ):
            return default

        return clean_text(
            response.get(
                "message"
            )
            or response.get(
                "msg"
            ),
            default=default,
        )

    def _call_client_method(
        self,
        access_token: str,
        method_name: str,
        payload: (
            dict[str, Any]
            | None
        ) = None,
    ) -> dict[str, Any]:
        client = self.create_client(
            access_token
        )

        method = getattr(
            client,
            method_name,
            None,
        )

        if (
            method is None
            or not callable(
                method
            )
        ):
            raise FyersAPIError(
                (
                    "FYERS method "
                    f"'{method_name}' "
                    "is unavailable."
                )
            )

        try:
            if payload is None:
                response = method()
            else:
                response = (
                    method(
                        payload
                    )
                )

            if not isinstance(
                response,
                dict,
            ):
                raise FyersAPIError(
                    (
                        "FYERS returned "
                        "an invalid response."
                    )
                )

            if not (
                self
                ._response_is_successful(
                    response
                )
            ):
                logger.error(
                    (
                        "FYERS API FAILED | "
                        "method=%s | "
                        "payload=%s | "
                        "response=%s"
                    ),
                    method_name,
                    payload,
                    response,
                    extra=build_log_extra(
                        component=(
                            "fyers_service"
                        ),
                        event=(
                            "api_failed"
                        ),
                        status="failed",
                    ),
                )

                message = (
                    self
                    ._response_message(
                        response,
                        (
                            "FYERS API "
                            "request failed."
                        ),
                    )
                )

                raise FyersAPIError(
                    message
                )

            return response

        except FyersAPIError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                (
                    "FYERS method "
                    f"{method_name} failed"
                ),
                exception=exception,
                component=(
                    "fyers_service"
                ),
                error_code=(
                    "FYERS_API_CALL_FAILED"
                ),
                method_name=(
                    method_name
                ),
            )

            raise FyersAPIError(
                (
                    "FYERS request failed: "
                    f"{method_name}"
                )
            ) from exception

    # ==========================================================
    # ACCOUNT API
    # ==========================================================

    def get_profile(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        return (
            self._call_client_method(
                access_token,
                "get_profile",
            )
        )

    def validate_access_token(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        try:
            response = (
                self.get_profile(
                    access_token
                )
            )

            profile_data = (
                response.get(
                    "data"
                )
                if isinstance(
                    response.get(
                        "data"
                    ),
                    dict,
                )
                else response
            )

            return {
                "valid": True,
                "profile": (
                    profile_data
                ),
                "message": (
                    "FYERS token is valid."
                ),
                "checked_at": (
                    utc_now().isoformat()
                ),
            }

        except Exception as exception:
            return {
                "valid": False,
                "profile": {},
                "message": str(
                    exception
                ),
                "checked_at": (
                    utc_now().isoformat()
                ),
            }

    def get_funds(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        return (
            self._call_client_method(
                access_token,
                "funds",
            )
        )

    def get_holdings(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        return (
            self._call_client_method(
                access_token,
                "holdings",
            )
        )

    def get_positions(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        return (
            self._call_client_method(
                access_token,
                "positions",
            )
        )

    # ==========================================================
    # QUOTES
    # ==========================================================

    def get_quotes(
        self,
        access_token: str,
        symbols: (
            list[str]
            | tuple[str, ...]
            | str
        ),
    ) -> dict[str, Any]:
        if isinstance(
            symbols,
            str,
        ):
            raw_symbols = [
                item.strip()
                for item
                in symbols.split(",")
                if item.strip()
            ]

        else:
            raw_symbols = list(
                symbols
            )

        fyers_symbols: list[
            str
        ] = []

        for raw_symbol in raw_symbols:
            text_symbol = clean_text(
                raw_symbol
            )

            if not text_symbol:
                continue

            if (
                ":"
                in text_symbol
                and "-"
                in text_symbol
            ):
                final_symbol = (
                    text_symbol.upper()
                )

            else:
                final_symbol = (
                    to_fyers_symbol(
                        text_symbol
                    )
                )

            if (
                final_symbol
                and final_symbol
                not in fyers_symbols
            ):
                fyers_symbols.append(
                    final_symbol
                )

        if not fyers_symbols:
            raise ValueError(
                (
                    "At least one valid "
                    "stock symbol is required."
                )
            )

        payload = {
            "symbols": ",".join(
                fyers_symbols
            )
        }

        return (
            self._call_client_method(
                access_token,
                "quotes",
                payload,
            )
        )

    # ==========================================================
    # HISTORY
    # ==========================================================

    def get_history(
        self,
        access_token: str,
        *,
        symbol: str,
        resolution: str = "D",
        range_from: str,
        range_to: str,
        date_format: str = "1",
        continuous: str = "1",
    ) -> dict[str, Any]:
        normalized_symbol = (
            clean_text(
                symbol
            )
        )

        if ":" not in normalized_symbol:
            normalized_symbol = (
                to_fyers_symbol(
                    normalized_symbol
                )
            )

        if not normalized_symbol:
            raise ValueError(
                (
                    "A valid stock symbol "
                    "is required."
                )
            )

        payload = {
            "symbol": (
                normalized_symbol
            ),
            "resolution": (
                clean_text(
                    resolution,
                    default="D",
                )
            ),
            "date_format": (
                clean_text(
                    date_format,
                    default="1",
                )
            ),
            "range_from": (
                clean_text(
                    range_from
                )
            ),
            "range_to": (
                clean_text(
                    range_to
                )
            ),
            "cont_flag": (
                clean_text(
                    continuous,
                    default="1",
                )
            ),
        }

        if (
            not payload[
                "range_from"
            ]
            or not payload[
                "range_to"
            ]
        ):
            raise ValueError(
                (
                    "History start and "
                    "end dates are required."
                )
            )

        return (
            self._call_client_method(
                access_token,
                "history",
                payload,
            )
        )

    # ==========================================================
    # PARSE CANDLES
    # ==========================================================

    def parse_history_candles(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not isinstance(
            response,
            dict,
        ):
            raise FyersAPIError(
                (
                    "Invalid FYERS "
                    "history response."
                )
            )

        raw_candles = (
            response.get(
                "candles",
                [],
            )
        )

        if not isinstance(
            raw_candles,
            list,
        ):
            raise FyersAPIError(
                (
                    "FYERS candle data "
                    "is invalid."
                )
            )

        candles: list[
            dict[str, Any]
        ] = []

        for candle in raw_candles:
            if (
                not isinstance(
                    candle,
                    (
                        list,
                        tuple,
                    ),
                )
                or len(candle) < 6
            ):
                continue

            try:
                timestamp = int(
                    candle[0]
                )

                open_price = float(
                    candle[1]
                )

                high_price = float(
                    candle[2]
                )

                low_price = float(
                    candle[3]
                )

                close_price = float(
                    candle[4]
                )

                volume = float(
                    candle[5]
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if (
                open_price <= 0
                or high_price <= 0
                or low_price <= 0
                or close_price <= 0
            ):
                continue

            if (
                high_price
                < max(
                    open_price,
                    close_price,
                )
            ):
                continue

            if (
                low_price
                > min(
                    open_price,
                    close_price,
                )
            ):
                continue

            candles.append(
                {
                    "timestamp": (
                        timestamp
                    ),
                    "open": (
                        open_price
                    ),
                    "high": (
                        high_price
                    ),
                    "low": (
                        low_price
                    ),
                    "close": (
                        close_price
                    ),
                    "volume": max(
                        0.0,
                        volume,
                    ),
                }
            )

        candles.sort(
            key=lambda item: (
                item["timestamp"]
            )
        )

        return candles

    # ==========================================================
    # CLEAN CANDLE FETCH
    # ==========================================================

    def get_candles(
        self,
        access_token: str,
        *,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
    ) -> list[dict[str, Any]]:
        response = (
            self.get_history(
                access_token,
                symbol=symbol,
                resolution=(
                    resolution
                ),
                range_from=(
                    range_from
                ),
                range_to=(
                    range_to
                ),
                date_format="1",
                continuous="1",
            )
        )

        candles = (
            self.parse_history_candles(
                response
            )
        )

        if not candles:
            raise FyersAPIError(
                (
                    "FYERS returned no "
                    "valid candles for "
                    f"{symbol}."
                )
            )

        return candles

    # ==========================================================
    # DATE RANGE
    # ==========================================================

    @staticmethod
    def _history_date_range(
        *,
        mode: str,
        resolution: str,
    ) -> tuple[str, str]:
        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        today = (
            datetime.now(
                timezone.utc
            )
            .date()
        )

        clean_resolution = (
            clean_text(
                resolution
            )
            .upper()
        )

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):
            if clean_resolution == "5":
                calendar_days = 30

            elif clean_resolution == "15":
                calendar_days = 60

            elif clean_resolution == "D":
                calendar_days = 420

            else:
                calendar_days = 60

        else:
            calendar_days = 550

        start_date = (
            today
            - timedelta(
                days=(
                    calendar_days
                )
            )
        )

        return (
            start_date.isoformat(),
            today.isoformat(),
        )

    # ==========================================================
    # MODE-BASED CANDLES
    # ==========================================================

    def get_mode_candles(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
    ) -> dict[str, Any]:
        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        if not normalized_symbol:
            raise ValueError(
                (
                    "A valid stock symbol "
                    "is required."
                )
            )

        # ======================================================
        # INTRADAY
        # ======================================================

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):
            primary_resolution = (
                Config
                .INTRADAY_PRIMARY_RESOLUTION
            )

            confirmation_resolution = (
                Config
                .INTRADAY_CONFIRMATION_RESOLUTION
            )

            higher_resolution = (
                Config
                .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
            )

            (
                primary_from,
                primary_to,
            ) = (
                self._history_date_range(
                    mode=(
                        normalized_mode
                    ),
                    resolution=(
                        primary_resolution
                    ),
                )
            )

            (
                confirmation_from,
                confirmation_to,
            ) = (
                self._history_date_range(
                    mode=(
                        normalized_mode
                    ),
                    resolution=(
                        confirmation_resolution
                    ),
                )
            )

            (
                higher_from,
                higher_to,
            ) = (
                self._history_date_range(
                    mode=(
                        normalized_mode
                    ),
                    resolution=(
                        higher_resolution
                    ),
                )
            )

            primary_candles = (
                self.get_candles(
                    access_token,
                    symbol=(
                        normalized_symbol
                    ),
                    resolution=(
                        primary_resolution
                    ),
                    range_from=(
                        primary_from
                    ),
                    range_to=(
                        primary_to
                    ),
                )
            )

            confirmation_candles = (
                self.get_candles(
                    access_token,
                    symbol=(
                        normalized_symbol
                    ),
                    resolution=(
                        confirmation_resolution
                    ),
                    range_from=(
                        confirmation_from
                    ),
                    range_to=(
                        confirmation_to
                    ),
                )
            )

            higher_candles = (
                self.get_candles(
                    access_token,
                    symbol=(
                        normalized_symbol
                    ),
                    resolution=(
                        higher_resolution
                    ),
                    range_from=(
                        higher_from
                    ),
                    range_to=(
                        higher_to
                    ),
                )
            )

            return {
                "symbol": (
                    normalized_symbol
                ),
                "mode": (
                    normalized_mode
                ),
                "primary_resolution": (
                    primary_resolution
                ),
                "confirmation_resolution": (
                    confirmation_resolution
                ),
                "higher_resolution": (
                    higher_resolution
                ),
                "primary": (
                    primary_candles
                ),
                "confirmation": (
                    confirmation_candles
                ),
                "higher_timeframe": (
                    higher_candles
                ),
            }

        # ======================================================
        # SWING
        # ======================================================

        primary_resolution = (
            Config
            .SWING_PRIMARY_RESOLUTION
        )

        (
            range_from,
            range_to,
        ) = (
            self._history_date_range(
                mode=(
                    normalized_mode
                ),
                resolution=(
                    primary_resolution
                ),
            )
        )

        daily_candles = (
            self.get_candles(
                access_token,
                symbol=(
                    normalized_symbol
                ),
                resolution=(
                    primary_resolution
                ),
                range_from=(
                    range_from
                ),
                range_to=(
                    range_to
                ),
            )
        )

        return {
            "symbol": (
                normalized_symbol
            ),
            "mode": (
                normalized_mode
            ),
            "primary_resolution": (
                primary_resolution
            ),
            "confirmation_resolution": (
                "weekly_from_daily"
            ),
            "primary": (
                daily_candles
            ),
            "confirmation_source": (
                daily_candles
            ),
        }

    # ==========================================================
    # LIVE PRICE
    # ==========================================================

    def get_latest_price(
        self,
        access_token: str,
        *,
        symbol: str,
    ) -> float:
        response = (
            self.get_quotes(
                access_token,
                [symbol],
            )
        )

        quote_rows = response.get(
            "d",
            [],
        )

        if not isinstance(
            quote_rows,
            list,
        ):
            raise FyersAPIError(
                (
                    "Invalid FYERS "
                    "quote response."
                )
            )

        for item in quote_rows:
            if not isinstance(
                item,
                dict,
            ):
                continue

            values = (
                item.get(
                    "v",
                    {},
                )
            )

            if not isinstance(
                values,
                dict,
            ):
                continue

            ltp = (
                values.get(
                    "lp"
                )
                or values.get(
                    "ltp"
                )
            )

            try:
                price = float(
                    ltp
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if price > 0:
                return price

        raise FyersAPIError(
            (
                "Live FYERS price "
                "is unavailable for "
                f"{symbol}."
            )
        )

    # ==========================================================
    # MARKET DEPTH
    # ==========================================================

    def get_market_depth(
        self,
        access_token: str,
        symbol: str,
        *,
        include_ohlcv: bool = True,
    ) -> dict[str, Any]:
        normalized_symbol = (
            clean_text(
                symbol
            )
        )

        if ":" not in normalized_symbol:
            normalized_symbol = (
                to_fyers_symbol(
                    normalized_symbol
                )
            )

        payload = {
            "symbol": (
                normalized_symbol
            ),
            "ohlcv_flag": (
                "1"
                if include_ohlcv
                else "0"
            ),
        }

        return (
            self._call_client_method(
                access_token,
                "depth",
                payload,
            )
        )

    # ==========================================================
    # HEALTH
    # ==========================================================

    def health(
        self,
        access_token: (
            str | None
        ) = None,
    ) -> dict[str, Any]:
        configuration = (
            self.configuration_status()
        )

        result: dict[
            str,
            Any,
        ] = {
            "service": (
                "FYERS API"
            ),
            "configured": (
                configuration[
                    "configured"
                ]
            ),
            "missing_fields": (
                configuration[
                    "missing_fields"
                ]
            ),
            "authenticated": False,
            "status": (
                "configured"
                if configuration[
                    "configured"
                ]
                else (
                    "not_configured"
                )
            ),
            "checked_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        normalized_token = (
            clean_text(
                access_token
            )
        )

        if (
            configuration[
                "configured"
            ]
            and normalized_token
        ):
            token_status = (
                self
                .validate_access_token(
                    normalized_token
                )
            )

            result[
                "authenticated"
            ] = token_status[
                "valid"
            ]

            result["status"] = (
                "healthy"
                if token_status[
                    "valid"
                ]
                else (
                    "authentication_failed"
                )
            )

            result["message"] = (
                token_status[
                    "message"
                ]
            )

        return result


# ==============================================================
# GLOBAL SERVICE
# ==============================================================

_global_fyers_service: (
    FyersService | None
) = None

_global_fyers_lock = (
    threading.Lock()
)


def get_fyers_service(
) -> FyersService:
    global _global_fyers_service

    if (
        _global_fyers_service
        is not None
    ):
        return (
            _global_fyers_service
        )

    with _global_fyers_lock:
        if (
            _global_fyers_service
            is None
        ):
            _global_fyers_service = (
                FyersService()
            )

    return (
        _global_fyers_service
    )
