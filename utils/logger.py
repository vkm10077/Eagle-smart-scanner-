from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO",
).upper()

LOG_DIRECTORY = Path(
    os.getenv(
        "LOG_DIRECTORY",
        "logs",
    )
)

LOG_FILE_NAME = os.getenv(
    "LOG_FILE_NAME",
    "eagle_smart_scanner.log",
)

MAX_LOG_FILE_SIZE = int(
    os.getenv(
        "MAX_LOG_FILE_SIZE",
        str(5 * 1024 * 1024),
    )
)

LOG_BACKUP_COUNT = int(
    os.getenv(
        "LOG_BACKUP_COUNT",
        "3",
    )
)

ENABLE_FILE_LOGGING = os.getenv(
    "ENABLE_FILE_LOGGING",
    "true",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ENABLE_JSON_LOGGING = os.getenv(
    "ENABLE_JSON_LOGGING",
    "false",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class SafeExtraFormatter(logging.Formatter):
    """
    Logging formatter that safely includes optional contextual fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"

        if not hasattr(record, "symbol"):
            record.symbol = "-"

        if not hasattr(record, "timeframe"):
            record.timeframe = "-"

        if not hasattr(record, "component"):
            record.component = "-"

        return super().format(record)


class JsonFormatter(logging.Formatter):
    """
    JSON formatter useful for structured logs on Render.
    """

    DEFAULT_FIELDS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }

        optional_fields = (
            "request_id",
            "symbol",
            "timeframe",
            "component",
            "event",
            "duration_ms",
            "status",
            "error_code",
        )

        for field_name in optional_fields:
            field_value = getattr(
                record,
                field_name,
                None,
            )

            if field_value not in {
                None,
                "",
                "-",
            }:
                log_data[field_name] = field_value

        for key, value in record.__dict__.items():
            if key in self.DEFAULT_FIELDS:
                continue

            if key.startswith("_"):
                continue

            if key in log_data:
                continue

            try:
                json.dumps(value)
                log_data[key] = value
            except (TypeError, ValueError):
                log_data[key] = str(value)

        if record.exc_info:
            log_data["exception"] = "".join(
                traceback.format_exception(
                    *record.exc_info
                )
            )

        return json.dumps(
            log_data,
            ensure_ascii=False,
            default=str,
        )


def _resolve_log_level(
    level_name: str | int | None,
) -> int:
    if isinstance(level_name, int):
        return level_name

    normalized_level = str(
        level_name or DEFAULT_LOG_LEVEL
    ).strip().upper()

    return getattr(
        logging,
        normalized_level,
        logging.INFO,
    )


def _create_console_handler(
    level: int,
) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if ENABLE_JSON_LOGGING:
        handler.setFormatter(
            JsonFormatter()
        )
    else:
        handler.setFormatter(
            SafeExtraFormatter(
                fmt=(
                    "%(asctime)s | %(levelname)s | "
                    "%(name)s | %(component)s | "
                    "%(symbol)s | %(timeframe)s | "
                    "%(message)s"
                ),
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    return handler


def _create_file_handler(
    level: int,
) -> logging.Handler | None:
    if not ENABLE_FILE_LOGGING:
        return None

    try:
        LOG_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        log_file_path = (
            LOG_DIRECTORY / LOG_FILE_NAME
        )

        handler = (
            logging.handlers.RotatingFileHandler(
                filename=log_file_path,
                maxBytes=MAX_LOG_FILE_SIZE,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )

        handler.setLevel(level)

        handler.setFormatter(
            SafeExtraFormatter(
                fmt=(
                    "%(asctime)s | %(levelname)s | "
                    "%(name)s | %(component)s | "
                    "%(request_id)s | %(symbol)s | "
                    "%(timeframe)s | %(message)s"
                ),
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        return handler

    except Exception:
        fallback_logger = logging.getLogger(
            "eagle.logger"
        )

        fallback_logger.warning(
            "File logging could not be initialized.",
            exc_info=True,
        )

        return None


def configure_logging(
    level: str | int | None = None,
    force: bool = False,
) -> logging.Logger:
    """
    Configure application-wide logging.

    This function is safe to call multiple times.
    """

    resolved_level = _resolve_log_level(
        level
    )

    root_logger = logging.getLogger()

    if root_logger.handlers and not force:
        root_logger.setLevel(resolved_level)

        for handler in root_logger.handlers:
            handler.setLevel(resolved_level)

        return logging.getLogger(
            "eagle"
        )

    if force:
        for handler in list(
            root_logger.handlers
        ):
            root_logger.removeHandler(handler)

            try:
                handler.close()
            except Exception:
                pass

    root_logger.setLevel(resolved_level)

    console_handler = (
        _create_console_handler(
            resolved_level
        )
    )

    root_logger.addHandler(
        console_handler
    )

    file_handler = _create_file_handler(
        resolved_level
    )

    if file_handler is not None:
        root_logger.addHandler(
            file_handler
        )

    logging.captureWarnings(True)

    noisy_loggers = {
        "urllib3": logging.WARNING,
        "requests": logging.WARNING,
        "apscheduler": logging.INFO,
        "gunicorn.error": logging.INFO,
        "gunicorn.access": logging.WARNING,
        "werkzeug": logging.INFO,
    }

    for logger_name, logger_level in (
        noisy_loggers.items()
    ):
        logging.getLogger(
            logger_name
        ).setLevel(
            logger_level
        )

    app_logger = logging.getLogger(
        "eagle"
    )

    app_logger.info(
        "Eagle Smart Scanner logging initialized.",
        extra={
            "component": "logger",
            "event": "logging_initialized",
        },
    )

    return app_logger


def get_logger(
    name: str | None = None,
) -> logging.Logger:
    """
    Return a child logger under the eagle namespace.
    """

    normalized_name = str(
        name or ""
    ).strip()

    if not logging.getLogger().handlers:
        configure_logging()

    if not normalized_name:
        return logging.getLogger(
            "eagle"
        )

    if normalized_name.startswith(
        "eagle"
    ):
        return logging.getLogger(
            normalized_name
        )

    return logging.getLogger(
        f"eagle.{normalized_name}"
    )


def build_log_extra(
    *,
    request_id: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    component: str | None = None,
    event: str | None = None,
    status: str | None = None,
    error_code: str | None = None,
    duration_ms: float | int | None = None,
    **additional_fields: Any,
) -> dict[str, Any]:
    """
    Build a safe dictionary for logging extra fields.
    """

    extra: dict[str, Any] = {
        "request_id": request_id or "-",
        "symbol": symbol or "-",
        "timeframe": timeframe or "-",
        "component": component or "-",
    }

    optional_values = {
        "event": event,
        "status": status,
        "error_code": error_code,
        "duration_ms": duration_ms,
    }

    for key, value in optional_values.items():
        if value is not None:
            extra[key] = value

    for key, value in (
        additional_fields.items()
    ):
        if value is not None:
            extra[key] = value

    return extra


def log_exception(
    logger: logging.Logger,
    message: str,
    *,
    exception: BaseException | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    component: str | None = None,
    request_id: str | None = None,
    error_code: str | None = None,
    **additional_fields: Any,
) -> None:
    """
    Log an exception with scanner context.
    """

    extra = build_log_extra(
        request_id=request_id,
        symbol=symbol,
        timeframe=timeframe,
        component=component,
        event="exception",
        status="failed",
        error_code=error_code,
        exception_type=(
            type(exception).__name__
            if exception
            else None
        ),
        **additional_fields,
    )

    if exception is not None:
        logger.error(
            "%s: %s",
            message,
            str(exception),
            exc_info=(
                type(exception),
                exception,
                exception.__traceback__,
            ),
            extra=extra,
        )
        return

    logger.exception(
        message,
        extra=extra,
    )


def log_scan_started(
    logger: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    component: str = "scanner",
) -> None:
    logger.info(
        "Stock scan started.",
        extra=build_log_extra(
            symbol=symbol,
            timeframe=timeframe,
            component=component,
            event="scan_started",
            status="running",
        ),
    )


def log_scan_completed(
    logger: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    signal: str,
    probability: float,
    duration_ms: float,
    component: str = "scanner",
) -> None:
    logger.info(
        (
            "Stock scan completed with signal=%s "
            "and probability=%.2f."
        ),
        signal,
        probability,
        extra=build_log_extra(
            symbol=symbol,
            timeframe=timeframe,
            component=component,
            event="scan_completed",
            status="success",
            duration_ms=round(
                duration_ms,
                2,
            ),
            signal=signal,
            probability=round(
                probability,
                2,
            ),
        ),
    )


def log_data_rejected(
    logger: logging.Logger,
    *,
    reason: str,
    symbol: str | None = None,
    timeframe: str | None = None,
    component: str = "validator",
    **details: Any,
) -> None:
    logger.warning(
        "Data rejected: %s",
        reason,
        extra=build_log_extra(
            symbol=symbol,
            timeframe=timeframe,
            component=component,
            event="data_rejected",
            status="rejected",
            rejection_reason=reason,
            **details,
        ),
    )


def log_api_call(
    logger: logging.Logger,
    *,
    service: str,
    endpoint: str,
    status: str,
    duration_ms: float | None = None,
    symbol: str | None = None,
    **details: Any,
) -> None:
    log_method = (
        logger.info
        if status == "success"
        else logger.warning
    )

    log_method(
        "API call %s: %s",
        status,
        endpoint,
        extra=build_log_extra(
            symbol=symbol,
            component=service,
            event="api_call",
            status=status,
            duration_ms=duration_ms,
            endpoint=endpoint,
            **details,
        ),
    )


configure_logging()
