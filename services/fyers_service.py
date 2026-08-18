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


logger = get_logger(
    "services.fyers_service"
)


# ============================================================
# ERRORS
# ============================================================


class FyersConfigurationError(
    RuntimeError
):
    """Raised when FYERS configuration is incomplete."""


class FyersAuthenticationError(
    RuntimeError
):
    """Raised when FYERS authentication fails."""


class FyersAPIError(
    RuntimeError
):
    """Raised when FYERS API returns an error."""


# ============================================================
# TOKEN RESULT
# ============================================================


@dataclass
class FyersTokenResult:

    success: bool

    access_token: str = ""

    refresh_token: str = ""

    message: str = ""

    raw_response: (
        dict[str, Any]
        | None
    ) = None

    def to_dict(
        self,
        *,
        include_token: bool = False,
    ) -> dict[str, Any]:

        result: dict[
            str,
            Any,
        ] = {
            "success": (
                self.success
            ),
            "message": (
                self.message
            ),
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

            result[
                "access_token"
            ] = (
                self.access_token
            )

            result[
                "refresh_token"
            ] = (
                self.refresh_token
            )

        return result


# ============================================================
# FYERS SERVICE
# ============================================================


class FyersService:
    """
    FYERS API v3 service for Eagle Smart Scanner.

    Supported scanner modes:

    INTRADAY
        Primary      = 5 minute
        Confirmation = 15 minute
        Higher       = Daily

    BTST
        Primary      = 15 minute
        Confirmation = 60 minute
        Higher       = Daily

    SWING
        Primary      = Daily
        Weekly confirmation is derived later
        by MarketDataService.

    Provides:

    - Login URL
    - Auth code -> token
    - Token validation
    - Profile
    - Funds
    - Holdings
    - Positions
    - Quotes
    - Historical candles
    - Mode-specific candle bundles
    - Latest price
    - Market depth

    No fundamental data.
    No fake data.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        *,
        client_id: (
            str | None
        ) = None,
        secret_key: (
            str | None
        ) = None,
        redirect_uri: (
            str | None
        ) = None,
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

    # ========================================================
    # CONFIGURATION
    # ========================================================

    def configuration_status(
        self,
    ) -> dict[str, Any]:

        missing_fields: list[
            str
        ] = []

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
                len(
                    missing_fields
                )
                == 0
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
            "supported_modes": [
                Config.MODE_INTRADAY,
                Config.MODE_BTST,
                Config.MODE_SWING,
            ],
            "checked_at": (
                utc_now()
                .isoformat()
            ),
        }

    def validate_configuration(
        self,
    ) -> None:

        status = (
            self.configuration_status()
        )

        if status[
            "configured"
        ]:
            return

        missing = ", ".join(
            status[
                "missing_fields"
            ]
        )

        raise (
            FyersConfigurationError(
                (
                    "Missing FYERS "
                    "configuration: "
                    f"{missing}"
                )
            )
        )

    # ========================================================
    # LOGIN
    # ========================================================

    def _create_session_model(
        self,
    ) -> Any:

        self.validate_configuration()

        return (
            fyersModel
            .SessionModel(
                client_id=(
                    self.client_id
                ),
                secret_key=(
                    self.secret_key
                ),
                redirect_uri=(
                    self.redirect_uri
                ),
                response_type="code",
                grant_type=(
                    "authorization_code"
                ),
            )
        )

    def generate_login_url(
        self,
    ) -> str:

        try:

            session_model = (
                self
                ._create_session_model()
            )

            login_url = (
                session_model
                .generate_authcode()
            )

            login_url = clean_text(
                login_url
            )

            if not login_url:

                raise (
                    FyersAuthenticationError(
                        (
                            "FYERS did not "
                            "generate login URL."
                        )
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

            raise (
                FyersAuthenticationError(
                    (
                        "Unable to generate "
                        "FYERS login URL."
                    )
                )
            ) from exception

    # ========================================================
    # AUTH CODE -> TOKEN
    # ========================================================

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
                self
                ._create_session_model()
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
                        "FYERS returned "
                        "an invalid token "
                        "response."
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

            status = (
                clean_text(
                    response.get("s")
                    or response.get(
                        "status"
                    )
                )
                .casefold()
            )

            response_code = (
                response.get(
                    "code"
                )
            )

            success = bool(
                access_token
            )

            if status in {
                "error",
                "failed",
                "failure",
            }:
                success = False

            if (
                isinstance(
                    response_code,
                    int,
                )
                and response_code < 0
            ):
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
                        "FYERS access token "
                        "generated."
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
                    raw_response=(
                        response
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

    # ========================================================
    # CLIENT
    # ========================================================

    def create_client(
        self,
        access_token: str,
        *,
        use_cache: bool = True,
    ) -> Any:

        normalized_token = (
            clean_text(
                access_token
            )
        )

        if not normalized_token:

            raise (
                FyersAuthenticationError(
                    (
                        "FYERS access token "
                        "is missing."
                    )
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
                    fyersModel
                    .FyersModel(
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

                raise (
                    FyersAuthenticationError(
                        (
                            "Unable to "
                            "initialize "
                            "FYERS client."
                        )
                    )
                ) from exception

    def clear_client_cache(
        self,
    ) -> None:

        with self._client_lock:
            self._clients.clear()

    # ========================================================
    # API RESPONSE HANDLING
    # ========================================================

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

        response_code = (
            response.get(
                "code"
            )
        )

        if status in {
            "error",
            "failed",
            "failure",
        }:
            return False

        if (
            isinstance(
                response_code,
                int,
            )
            and response_code < 0
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
                    f"FYERS method "
                    f"'{method_name}' "
                    "is unavailable."
                )
            )

        try:

            if payload is None:
                response = method()

            else:
                response = method(
                    payload
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

                logger.error(
                    (
                        "FYERS API FAILED | "
                        "method=%s | "
                        "message=%s | "
                        "payload=%s | "
                        "response=%s"
                    ),
                    method_name,
                    message,
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
                    f"FYERS method "
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

            raise (
                FyersAPIError(
                    (
                        "FYERS request "
                        "failed: "
                        f"{method_name}"
                    )
                )
            ) from exception

    # ========================================================
    # PROFILE
    # ========================================================

    def get_profile(
        self,
        access_token: str,
    ) -> dict[str, Any]:

        return (
            self
            ._call_client_method(
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

            profile = (
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
                "profile": profile,
                "message": (
                    "FYERS token "
                    "is valid."
                ),
                "checked_at": (
                    utc_now()
                    .isoformat()
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
                    utc_now()
                    .isoformat()
                ),
            }

    # ========================================================
    # ACCOUNT
    # ========================================================

    def get_funds(
        self,
        access_token: str,
    ) -> dict[str, Any]:

        return (
            self
            ._call_client_method(
                access_token,
                "funds",
            )
        )

    def get_holdings(
        self,
        access_token: str,
    ) -> dict[str, Any]:

        return (
            self
            ._call_client_method(
                access_token,
                "holdings",
            )
        )

    def get_positions(
        self,
        access_token: str,
    ) -> dict[str, Any]:

        return (
            self
            ._call_client_method(
                access_token,
                "positions",
            )
        )

    # ========================================================
    # SYMBOL
    # ========================================================

    @staticmethod
    def _to_market_symbol(
        symbol: str,
    ) -> str:

        normalized = (
            clean_text(
                symbol
            )
            .upper()
        )

        if not normalized:
            return ""

        # Already a complete FYERS symbol.
        if ":" in normalized:
            return normalized

        clean_symbol = (
            normalize_symbol(
                normalized
            )
        )

        if not clean_symbol:
            return ""

        return to_fyers_symbol(
            clean_symbol
        )

    # ========================================================
    # QUOTES
    # ========================================================

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

        final_symbols: list[
            str
        ] = []

        for raw_symbol in (
            raw_symbols
        ):

            symbol = (
                self
                ._to_market_symbol(
                    raw_symbol
                )
            )

            if (
                symbol
                and symbol
                not in final_symbols
            ):

                final_symbols.append(
                    symbol
                )

        if not final_symbols:

            raise ValueError(
                (
                    "At least one valid "
                    "stock symbol is "
                    "required."
                )
            )

        payload = {
            "symbols": ",".join(
                final_symbols
            )
        }

        return (
            self
            ._call_client_method(
                access_token,
                "quotes",
                payload,
            )
        )

    # ========================================================
    # HISTORY
    # ========================================================

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

        fyers_symbol = (
            self
            ._to_market_symbol(
                symbol
            )
        )

        if not fyers_symbol:

            raise ValueError(
                (
                    "A valid stock symbol "
                    "is required."
                )
            )

        normalized_resolution = (
            clean_text(
                resolution,
                default="D",
            )
        )

        normalized_from = (
            clean_text(
                range_from
            )
        )

        normalized_to = (
            clean_text(
                range_to
            )
        )

        if (
            not normalized_from
            or not normalized_to
        ):

            raise ValueError(
                (
                    "History start and "
                    "end dates are "
                    "required."
                )
            )

        payload = {
            "symbol": (
                fyers_symbol
            ),
            "resolution": (
                normalized_resolution
            ),
            "date_format": (
                clean_text(
                    date_format,
                    default="1",
                )
            ),
            "range_from": (
                normalized_from
            ),
            "range_to": (
                normalized_to
            ),
            "cont_flag": (
                clean_text(
                    continuous,
                    default="1",
                )
            ),
        }

        return (
            self
            ._call_client_method(
                access_token,
                "history",
                payload,
            )
        )

    # ========================================================
    # HISTORY RESPONSE -> CANDLES
    # ========================================================

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
                "candles"
            )
        )

        if raw_candles is None:

            data = response.get(
                "data"
            )

            if isinstance(
                data,
                dict,
            ):

                raw_candles = (
                    data.get(
                        "candles"
                    )
                )

        if not isinstance(
            raw_candles,
            list,
        ):

            raise FyersAPIError(
                (
                    "FYERS history "
                    "response does not "
                    "contain candles."
                )
            )

        candles: list[
            dict[str, Any]
        ] = []

        seen_timestamps: set[
            int
        ] = set()

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

            if timestamp in seen_timestamps:
                continue

            if min(
                open_price,
                high_price,
                low_price,
                close_price,
            ) <= 0:
                continue

            if (
                high_price
                < max(
                    open_price,
                    close_price,
                    low_price,
                )
            ):
                continue

            if (
                low_price
                > min(
                    open_price,
                    close_price,
                    high_price,
                )
            ):
                continue

            if volume < 0:
                continue

            seen_timestamps.add(
                timestamp
            )

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
                    "volume": (
                        volume
                    ),
                }
            )

        candles.sort(
            key=lambda item: (
                item[
                    "timestamp"
                ]
            )
        )

        return candles

    # ========================================================
    # GET CLEAN CANDLES
    # ========================================================

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
            self
            .parse_history_candles(
                response
            )
        )

        if not candles:

            raise FyersAPIError(
                (
                    "FYERS returned no "
                    "valid candles for "
                    f"{symbol} at "
                    f"{resolution} resolution."
                )
            )

        return candles

    # ========================================================
    # HISTORY RANGE
    # ========================================================

    @staticmethod
    def _history_date_range(
        *,
        mode: str,
        resolution: str,
    ) -> tuple[
        str,
        str,
    ]:
        """
        Calendar range used to collect enough completed
        candles for technical calculations.

        This does NOT generate synthetic candles.
        """

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        clean_resolution = (
            clean_text(
                resolution
            )
            .upper()
        )

        today = (
            datetime.now(
                timezone.utc
            )
            .date()
        )

        # ====================================================
        # INTRADAY
        # ====================================================

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            if clean_resolution == "5":

                calendar_days = 20

            elif clean_resolution == "15":

                calendar_days = 45

            elif clean_resolution == "D":

                calendar_days = 365

            else:

                calendar_days = 45

        # ====================================================
        # BTST
        # ====================================================

        elif (
            normalized_mode
            == Config.MODE_BTST
        ):

            if clean_resolution == "15":

                # Enough completed 15m candles.
                calendar_days = 45

            elif clean_resolution == "60":

                # Enough 60m candles for EMA/RSI/MACD.
                calendar_days = 120

            elif clean_resolution == "D":

                # Daily trend confirmation.
                calendar_days = 365

            else:

                calendar_days = 120

        # ====================================================
        # SWING
        # ====================================================

        else:

            # Enough Daily candles for EMA200
            # plus technical lookback.
            calendar_days = 450

        start_date = (
            today
            - timedelta(
                days=calendar_days
            )
        )

        return (
            start_date.isoformat(),
            today.isoformat(),
        )

    # ========================================================
    # FETCH MULTI-TIMEFRAME BUNDLE
    # ========================================================

    def _fetch_multi_timeframe_bundle(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
        primary_resolution: str,
        confirmation_resolution: str,
        higher_resolution: str,
    ) -> dict[str, Any]:
        """
        Common loader used by Intraday and BTST.

        Keeps all three timeframe branches structurally
        identical for MarketDataService.
        """

        (
            primary_from,
            primary_to,
        ) = (
            self
            ._history_date_range(
                mode=mode,
                resolution=(
                    primary_resolution
                ),
            )
        )

        (
            confirmation_from,
            confirmation_to,
        ) = (
            self
            ._history_date_range(
                mode=mode,
                resolution=(
                    confirmation_resolution
                ),
            )
        )

        (
            higher_from,
            higher_to,
        ) = (
            self
            ._history_date_range(
                mode=mode,
                resolution=(
                    higher_resolution
                ),
            )
        )

        primary_candles = (
            self.get_candles(
                access_token,
                symbol=symbol,
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
                symbol=symbol,
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
                symbol=symbol,
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
                symbol
            ),
            "mode": (
                mode
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
            "source": "FYERS",
            "verified": True,
            "generated_at": (
                utc_now()
                .isoformat()
            ),
        }

    # ========================================================
    # MODE CANDLES
    # ========================================================

    def get_mode_candles(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
    ) -> dict[str, Any]:

        normalized_mode = (
            Config
            .normalize_trading_mode(
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
                    "A valid stock "
                    "symbol is required."
                )
            )

        # ====================================================
        # INTRADAY
        # ====================================================

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            return (
                self
                ._fetch_multi_timeframe_bundle(
                    access_token,
                    symbol=(
                        normalized_symbol
                    ),
                    mode=(
                        normalized_mode
                    ),
                    primary_resolution=(
                        Config
                        .INTRADAY_PRIMARY_RESOLUTION
                    ),
                    confirmation_resolution=(
                        Config
                        .INTRADAY_CONFIRMATION_RESOLUTION
                    ),
                    higher_resolution=(
                        Config
                        .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
                    ),
                )
            )

        # ====================================================
        # BTST
        # ====================================================

        if (
            normalized_mode
            == Config.MODE_BTST
        ):

            return (
                self
                ._fetch_multi_timeframe_bundle(
                    access_token,
                    symbol=(
                        normalized_symbol
                    ),
                    mode=(
                        normalized_mode
                    ),
                    primary_resolution=(
                        Config
                        .BTST_PRIMARY_RESOLUTION
                    ),
                    confirmation_resolution=(
                        Config
                        .BTST_CONFIRMATION_RESOLUTION
                    ),
                    higher_resolution=(
                        Config
                        .BTST_HIGHER_TIMEFRAME_RESOLUTION
                    ),
                )
            )

        # ====================================================
        # SWING
        # ====================================================

        primary_resolution = (
            Config
            .SWING_PRIMARY_RESOLUTION
        )

        (
            range_from,
            range_to,
        ) = (
            self
            ._history_date_range(
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
                Config
                .SWING_CONFIRMATION_RESOLUTION
            ),
            "higher_resolution": (
                Config
                .SWING_HIGHER_TIMEFRAME_RESOLUTION
            ),

            # MarketDataService derives
            # weekly candles from this.
            "primary": (
                daily_candles
            ),
            "confirmation_source": (
                daily_candles
            ),
            "higher_timeframe_source": (
                daily_candles
            ),
            "source": "FYERS",
            "verified": True,
            "generated_at": (
                utc_now()
                .isoformat()
            ),
        }

    # ========================================================
    # LATEST PRICE
    # ========================================================

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

        rows = response.get(
            "d"
        )

        if not isinstance(
            rows,
            list,
        ):

            data = response.get(
                "data"
            )

            if isinstance(
                data,
                list,
            ):

                rows = data

            elif isinstance(
                data,
                dict,
            ):

                rows = (
                    data.get(
                        "d"
                    )
                    or data.get(
                        "quotes"
                    )
                )

        if not isinstance(
            rows,
            list,
        ):

            raise FyersAPIError(
                (
                    "Invalid FYERS "
                    "quote response."
                )
            )

        for item in rows:

            if not isinstance(
                item,
                dict,
            ):
                continue

            values = (
                item.get(
                    "v"
                )
            )

            if not isinstance(
                values,
                dict,
            ):
                values = item

            price_value = (
                values.get("lp")
                or values.get(
                    "ltp"
                )
                or values.get(
                    "last_price"
                )
            )

            try:

                price = float(
                    price_value
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

    # ========================================================
    # MARKET DEPTH
    # ========================================================

    def get_market_depth(
        self,
        access_token: str,
        symbol: str,
        *,
        include_ohlcv: bool = True,
    ) -> dict[str, Any]:

        normalized_symbol = (
            self
            ._to_market_symbol(
                symbol
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "A valid stock "
                    "symbol is required."
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
            self
            ._call_client_method(
                access_token,
                "depth",
                payload,
            )
        )

    # ========================================================
    # HEALTH
    # ========================================================

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
            "supported_modes": [
                Config.MODE_INTRADAY,
                Config.MODE_BTST,
                Config.MODE_SWING,
            ],
            "timeframes": {
                "intraday": {
                    "primary": (
                        Config
                        .INTRADAY_PRIMARY_RESOLUTION
                    ),
                    "confirmation": (
                        Config
                        .INTRADAY_CONFIRMATION_RESOLUTION
                    ),
                    "higher": (
                        Config
                        .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
                    ),
                },
                "btst": {
                    "primary": (
                        Config
                        .BTST_PRIMARY_RESOLUTION
                    ),
                    "confirmation": (
                        Config
                        .BTST_CONFIRMATION_RESOLUTION
                    ),
                    "higher": (
                        Config
                        .BTST_HIGHER_TIMEFRAME_RESOLUTION
                    ),
                },
                "swing": {
                    "primary": (
                        Config
                        .SWING_PRIMARY_RESOLUTION
                    ),
                    "confirmation": (
                        Config
                        .SWING_CONFIRMATION_RESOLUTION
                    ),
                    "higher": (
                        Config
                        .SWING_HIGHER_TIMEFRAME_RESOLUTION
                    ),
                },
            },
            "technical_only": True,
            "fake_data_allowed": bool(
                Config.ALLOW_FAKE_DATA
            ),
            "checked_at": (
                datetime.now(
                    timezone.utc
                )
                .isoformat()
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
            ] = bool(
                token_status.get(
                    "valid"
                )
            )

            result[
                "status"
            ] = (
                "healthy"
                if result[
                    "authenticated"
                ]
                else (
                    "authentication_failed"
                )
            )

            result[
                "message"
            ] = (
                token_status.get(
                    "message",
                    "",
                )
            )

        return result

# ============================================================
# GLOBAL INSTANCE
# ============================================================

_global_fyers_service: (
    FyersService | None
) = None

_global_fyers_lock = (
    threading.Lock()
)


# ============================================================
# GET FYERS SERVICE
# ============================================================

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
