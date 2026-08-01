from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from io import StringIO
from threading import Lock
from typing import Any

import pandas as pd
import requests


logger = logging.getLogger(__name__)


NIFTY_500_CSV_URL = (
    "https://www.niftyindices.com/IndexConstituent/"
    "ind_nifty500list.csv"
)

REQUEST_TIMEOUT_SECONDS = 25
CACHE_DURATION_SECONDS = 6 * 60 * 60
MAX_EXPECTED_STOCKS = 550
MIN_VALID_STOCKS = 450


@dataclass(frozen=True)
class Nifty500Stock:
    company_name: str
    symbol: str
    industry: str
    series: str = "EQ"
    isin_code: str = ""

    @property
    def fyers_symbol(self) -> str:
        return f"NSE:{self.symbol}-EQ"

    @property
    def nse_symbol(self) -> str:
        return self.symbol

    @property
    def yahoo_symbol(self) -> str:
        return f"{self.symbol}.NS"

    def to_dict(self) -> dict[str, str]:
        return {
            "company_name": self.company_name,
            "symbol": self.symbol,
            "industry": self.industry,
            "sector": self.industry,
            "series": self.series,
            "isin_code": self.isin_code,
            "fyers_symbol": self.fyers_symbol,
            "nse_symbol": self.nse_symbol,
            "yahoo_symbol": self.yahoo_symbol,
        }


_cache_lock = Lock()
_cached_stocks: list[Nifty500Stock] = []
_cache_timestamp: float = 0.0


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return " ".join(text.split())


def _normalize_symbol(value: Any) -> str:
    symbol = _clean_text(value).upper()

    symbol = symbol.replace("NSE:", "")
    symbol = symbol.replace(".NS", "")
    symbol = symbol.replace("-EQ", "")
    symbol = symbol.strip()

    return symbol


def _find_column(
    dataframe: pd.DataFrame,
    possible_names: list[str],
) -> str | None:
    normalized_columns = {
        str(column).strip().lower(): str(column)
        for column in dataframe.columns
    }

    for name in possible_names:
        normalized_name = name.strip().lower()

        if normalized_name in normalized_columns:
            return normalized_columns[normalized_name]

    return None


def _validate_dataframe(dataframe: pd.DataFrame) -> None:
    if dataframe.empty:
        raise ValueError("Nifty 500 constituent file is empty.")

    if len(dataframe) < MIN_VALID_STOCKS:
        raise ValueError(
            f"Nifty 500 list contains only {len(dataframe)} stocks."
        )

    if len(dataframe) > MAX_EXPECTED_STOCKS:
        raise ValueError(
            f"Nifty 500 list contains unexpected {len(dataframe)} rows."
        )


def _parse_constituents(csv_text: str) -> list[Nifty500Stock]:
    dataframe = pd.read_csv(StringIO(csv_text))
    dataframe.columns = [
        str(column).strip()
        for column in dataframe.columns
    ]

    _validate_dataframe(dataframe)

    company_column = _find_column(
        dataframe,
        [
            "Company Name",
            "Company",
            "Name",
        ],
    )

    symbol_column = _find_column(
        dataframe,
        [
            "Symbol",
            "Ticker",
            "Trading Symbol",
        ],
    )

    industry_column = _find_column(
        dataframe,
        [
            "Industry",
            "Sector",
            "Industry Name",
        ],
    )

    series_column = _find_column(
        dataframe,
        [
            "Series",
        ],
    )

    isin_column = _find_column(
        dataframe,
        [
            "ISIN Code",
            "ISIN",
        ],
    )

    if company_column is None:
        raise ValueError("Company Name column is missing.")

    if symbol_column is None:
        raise ValueError("Symbol column is missing.")

    stocks: list[Nifty500Stock] = []
    seen_symbols: set[str] = set()

    for _, row in dataframe.iterrows():
        symbol = _normalize_symbol(row.get(symbol_column))
        company_name = _clean_text(row.get(company_column))

        if not symbol or not company_name:
            continue

        if symbol in seen_symbols:
            continue

        industry = (
            _clean_text(row.get(industry_column))
            if industry_column
            else "Unknown"
        )

        series = (
            _clean_text(row.get(series_column)).upper()
            if series_column
            else "EQ"
        )

        isin_code = (
            _clean_text(row.get(isin_column)).upper()
            if isin_column
            else ""
        )

        if not series:
            series = "EQ"

        stock = Nifty500Stock(
            company_name=company_name,
            symbol=symbol,
            industry=industry or "Unknown",
            series=series,
            isin_code=isin_code,
        )

        stocks.append(stock)
        seen_symbols.add(symbol)

    if len(stocks) < MIN_VALID_STOCKS:
        raise ValueError(
            f"Only {len(stocks)} valid Nifty 500 stocks were parsed."
        )

    stocks.sort(
        key=lambda item: item.company_name.casefold()
    )

    return stocks


def _download_constituents() -> list[Nifty500Stock]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14) "
            "AppleWebKit/537.36 "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.niftyindices.com/",
        "Cache-Control": "no-cache",
    }

    response = requests.get(
        NIFTY_500_CSV_URL,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    csv_text = response.text.strip()

    if not csv_text:
        raise ValueError("Downloaded Nifty 500 CSV is empty.")

    return _parse_constituents(csv_text)


def get_nifty500_stocks(
    force_refresh: bool = False,
) -> list[Nifty500Stock]:
    global _cached_stocks
    global _cache_timestamp

    current_time = time.time()

    cache_is_valid = (
        bool(_cached_stocks)
        and not force_refresh
        and current_time - _cache_timestamp
        < CACHE_DURATION_SECONDS
    )

    if cache_is_valid:
        return list(_cached_stocks)

    with _cache_lock:
        current_time = time.time()

        cache_is_valid = (
            bool(_cached_stocks)
            and not force_refresh
            and current_time - _cache_timestamp
            < CACHE_DURATION_SECONDS
        )

        if cache_is_valid:
            return list(_cached_stocks)

        try:
            downloaded_stocks = _download_constituents()

            _cached_stocks = downloaded_stocks
            _cache_timestamp = time.time()

            logger.info(
                "Loaded %s Nifty 500 stocks.",
                len(downloaded_stocks),
            )

            return list(downloaded_stocks)

        except Exception:
            logger.exception(
                "Unable to download the latest Nifty 500 list."
            )

            if _cached_stocks:
                logger.warning(
                    "Using previously cached Nifty 500 list."
                )
                return list(_cached_stocks)

            raise RuntimeError(
                "Nifty 500 stock list is currently unavailable."
            )


def get_nifty500_as_dicts(
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    stocks = get_nifty500_stocks(
        force_refresh=force_refresh
    )

    return [
        stock.to_dict()
        for stock in stocks
    ]


def get_nifty500_symbols(
    format_type: str = "plain",
    force_refresh: bool = False,
) -> list[str]:
    stocks = get_nifty500_stocks(
        force_refresh=force_refresh
    )

    normalized_format = format_type.strip().lower()

    if normalized_format == "fyers":
        return [
            stock.fyers_symbol
            for stock in stocks
        ]

    if normalized_format == "yahoo":
        return [
            stock.yahoo_symbol
            for stock in stocks
        ]

    return [
        stock.symbol
        for stock in stocks
    ]


def find_stock(
    query: str,
    force_refresh: bool = False,
) -> Nifty500Stock | None:
    normalized_query = _clean_text(query).casefold()

    if not normalized_query:
        return None

    stocks = get_nifty500_stocks(
        force_refresh=force_refresh
    )

    exact_symbol_match = next(
        (
            stock
            for stock in stocks
            if stock.symbol.casefold() == normalized_query
        ),
        None,
    )

    if exact_symbol_match:
        return exact_symbol_match

    exact_name_match = next(
        (
            stock
            for stock in stocks
            if stock.company_name.casefold()
            == normalized_query
        ),
        None,
    )

    if exact_name_match:
        return exact_name_match

    partial_match = next(
        (
            stock
            for stock in stocks
            if normalized_query
            in stock.company_name.casefold()
            or normalized_query
            in stock.symbol.casefold()
        ),
        None,
    )

    return partial_match


def search_stocks(
    query: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    normalized_query = _clean_text(query).casefold()

    if not normalized_query:
        return []

    safe_limit = max(1, min(int(limit), 50))

    stocks = get_nifty500_stocks()

    matches: list[Nifty500Stock] = []

    for stock in stocks:
        searchable_text = (
            f"{stock.company_name} "
            f"{stock.symbol} "
            f"{stock.industry}"
        ).casefold()

        if normalized_query in searchable_text:
            matches.append(stock)

        if len(matches) >= safe_limit:
            break

    return [
        stock.to_dict()
        for stock in matches
    ]


def get_sector_map() -> dict[str, str]:
    stocks = get_nifty500_stocks()

    return {
        stock.symbol: stock.industry
        for stock in stocks
    }


def clear_nifty500_cache() -> None:
    global _cached_stocks
    global _cache_timestamp

    with _cache_lock:
        _cached_stocks = []
        _cache_timestamp = 0.0

    logger.info("Nifty 500 cache cleared.")
