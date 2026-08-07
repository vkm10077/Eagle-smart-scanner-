from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from data.sector_map import (
    normalize_sector_name,
    normalize_symbol,
    to_fyers_symbol,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NSEStock:
    """
    One NSE equity belonging to a sector universe.

    IMPORTANT:
    Eagle Smart Scanner does NOT keep a fixed NIFTY 500 universe.
    Stocks enter the scanner only through selected NSE sectors.
    """

    symbol: str
    company_name: str
    sector: str

    @property
    def fyers_symbol(self) -> str:
        return to_fyers_symbol(self.symbol)

    def to_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "name": self.company_name,
            "sector": self.sector,
            "fyers_symbol": self.fyers_symbol,
        }


def create_stock(
    symbol: str,
    company_name: str,
    sector: str,
) -> NSEStock | None:
    """
    Create one clean NSE stock object.
    """

    clean_symbol = normalize_symbol(symbol)

    clean_name = " ".join(
        str(company_name or "").strip().split()
    )

    clean_sector = normalize_sector_name(sector)

    if not clean_symbol:
        return None

    if not clean_name:
        clean_name = clean_symbol

    if not clean_sector or clean_sector == "Unknown":
        return None

    return NSEStock(
        symbol=clean_symbol,
        company_name=clean_name,
        sector=clean_sector,
    )


def clean_stock_universe(
    stocks: Iterable[dict],
) -> list[NSEStock]:
    """
    Clean stocks received from NSE sector constituent data.

    This function:
    - removes invalid records
    - removes duplicates
    - normalizes symbols
    - normalizes sectors

    It does NOT apply NIFTY 500 filtering.
    """

    cleaned: list[NSEStock] = []
    seen_symbols: set[str] = set()

    for item in stocks:
        stock = create_stock(
            symbol=str(
                item.get("symbol")
                or item.get("ticker")
                or ""
            ),
            company_name=str(
                item.get("company_name")
                or item.get("name")
                or ""
            ),
            sector=str(
                item.get("sector")
                or item.get("industry")
                or ""
            ),
        )

        if stock is None:
            continue

        if stock.symbol in seen_symbols:
            continue

        seen_symbols.add(stock.symbol)
        cleaned.append(stock)

    return cleaned


def group_by_sector(
    stocks: Iterable[NSEStock],
) -> dict[str, list[NSEStock]]:
    """
    Group available NSE equities by sector.
    """

    sector_map: dict[str, list[NSEStock]] = {}

    for stock in stocks:
        sector_map.setdefault(
            stock.sector,
            [],
        ).append(stock)

    for sector in sector_map:
        sector_map[sector].sort(
            key=lambda stock: stock.symbol
        )

    return sector_map


def flatten_sector_stocks(
    sector_map: dict[str, list[NSEStock]],
) -> list[NSEStock]:
    """
    Convert sector-wise stocks into one unique list.
    """

    output: list[NSEStock] = []
    seen_symbols: set[str] = set()

    for stocks in sector_map.values():
        for stock in stocks:
            if stock.symbol in seen_symbols:
                continue

            seen_symbols.add(stock.symbol)
            output.append(stock)

    return output


def stocks_to_dicts(
    stocks: Iterable[NSEStock],
) -> list[dict[str, str]]:
    return [
        stock.to_dict()
        for stock in stocks
    ]


def find_stock(
    query: str,
    stocks: Iterable[NSEStock],
) -> NSEStock | None:
    """
    Search within the currently available NSE sector universe.

    Search Bar later can use this.
    """

    clean_query = " ".join(
        str(query or "").strip().split()
    ).casefold()

    if not clean_query:
        return None

    stock_list = list(stocks)

    # Exact symbol first
    for stock in stock_list:
        if stock.symbol.casefold() == clean_query:
            return stock

    # Exact company name
    for stock in stock_list:
        if stock.company_name.casefold() == clean_query:
            return stock

    # Partial match
    for stock in stock_list:
        searchable = (
            f"{stock.symbol} "
            f"{stock.company_name} "
            f"{stock.sector}"
        ).casefold()

        if clean_query in searchable:
            return stock

    return None


def search_stocks(
    query: str,
    stocks: Iterable[NSEStock],
    limit: int = 20,
) -> list[dict[str, str]]:
    """
    Search stocks from dynamically loaded NSE sector stocks.

    No NIFTY 500 dependency.
    """

    clean_query = " ".join(
        str(query or "").strip().split()
    ).casefold()

    if not clean_query:
        return []

    safe_limit = max(
        1,
        min(int(limit), 50),
    )

    results: list[NSEStock] = []

    for stock in stocks:
        searchable = (
            f"{stock.symbol} "
            f"{stock.company_name} "
            f"{stock.sector}"
        ).casefold()

        if clean_query in searchable:
            results.append(stock)

        if len(results) >= safe_limit:
            break

    return stocks_to_dicts(results)
