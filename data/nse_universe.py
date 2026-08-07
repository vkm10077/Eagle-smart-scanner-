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
    One NSE equity belonging to one sector universe.

    Eagle Smart Scanner does not use a fixed NIFTY 500 universe.
    Stocks enter the scanner through dynamically loaded NSE
    sector/index constituent data.
    """

    symbol: str
    company_name: str
    sector: str

    @property
    def fyers_symbol(self) -> str:
        return to_fyers_symbol(
            self.symbol
        )

    def to_dict(
        self,
    ) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "company_name": (
                self.company_name
            ),
            "name": (
                self.company_name
            ),
            "sector": (
                self.sector
            ),
            "fyers_symbol": (
                self.fyers_symbol
            ),
        }


def create_stock(
    symbol: str,
    company_name: str,
    sector: str,
) -> NSEStock | None:
    """
    Create one validated NSE stock record.
    """

    clean_symbol = (
        normalize_symbol(
            symbol
        )
    )

    clean_name = " ".join(
        str(
            company_name or ""
        )
        .strip()
        .split()
    )

    clean_sector = (
        normalize_sector_name(
            sector
        )
    )

    if not clean_symbol:
        return None

    if not clean_name:
        clean_name = clean_symbol

    if (
        not clean_sector
        or clean_sector == "Unknown"
    ):
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
    Clean dynamically loaded sector constituent records.

    Important:
    Duplicate protection is based on:

        sector + symbol

    not symbol alone.

    This preserves valid membership when the same NSE stock
    appears in more than one sector/index source.
    """

    cleaned: list[NSEStock] = []

    seen_memberships: set[
        tuple[str, str]
    ] = set()

    for item in stocks:
        if not isinstance(
            item,
            dict,
        ):
            continue

        stock = create_stock(
            symbol=str(
                item.get("symbol")
                or item.get("ticker")
                or ""
            ),
            company_name=str(
                item.get(
                    "company_name"
                )
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

        membership_key = (
            stock.sector,
            stock.symbol,
        )

        if (
            membership_key
            in seen_memberships
        ):
            continue

        seen_memberships.add(
            membership_key
        )

        cleaned.append(
            stock
        )

    cleaned.sort(
        key=lambda stock: (
            stock.sector.casefold(),
            stock.symbol.casefold(),
        )
    )

    return cleaned


def group_by_sector(
    stocks: Iterable[NSEStock],
) -> dict[
    str,
    list[NSEStock],
]:
    """
    Group NSE stocks by sector.
    """

    sector_map: dict[
        str,
        list[NSEStock],
    ] = {}

    seen_memberships: set[
        tuple[str, str]
    ] = set()

    for stock in stocks:
        if not isinstance(
            stock,
            NSEStock,
        ):
            continue

        key = (
            stock.sector,
            stock.symbol,
        )

        if key in seen_memberships:
            continue

        seen_memberships.add(
            key
        )

        sector_map.setdefault(
            stock.sector,
            [],
        ).append(
            stock
        )

    for sector in sector_map:
        sector_map[
            sector
        ].sort(
            key=lambda stock: (
                stock.symbol
            )
        )

    return sector_map


def flatten_sector_stocks(
    sector_map: dict[
        str,
        list[NSEStock],
    ],
) -> list[NSEStock]:
    """
    Flatten a sector map into a unique symbol list.

    This helper intentionally removes duplicate symbols,
    because some downstream operations such as FYERS quote
    fetching only need one request per stock symbol.
    """

    output: list[
        NSEStock
    ] = []

    seen_symbols: set[
        str
    ] = set()

    for stocks in (
        sector_map.values()
    ):
        for stock in stocks:
            if (
                stock.symbol
                in seen_symbols
            ):
                continue

            seen_symbols.add(
                stock.symbol
            )

            output.append(
                stock
            )

    output.sort(
        key=lambda stock: (
            stock.symbol
        )
    )

    return output


def stocks_to_dicts(
    stocks: Iterable[
        NSEStock
    ],
) -> list[
    dict[str, str]
]:
    return [
        stock.to_dict()
        for stock in stocks
    ]


def find_stock(
    query: str,
    stocks: Iterable[
        NSEStock
    ],
) -> NSEStock | None:
    """
    Search within the currently loaded dynamic NSE universe.
    """

    clean_query = " ".join(
        str(
            query or ""
        )
        .strip()
        .split()
    ).casefold()

    if not clean_query:
        return None

    stock_list = list(
        stocks
    )

    # Exact symbol
    for stock in stock_list:
        if (
            stock.symbol.casefold()
            == clean_query
        ):
            return stock

    # Exact company name
    for stock in stock_list:
        if (
            stock.company_name
            .casefold()
            == clean_query
        ):
            return stock

    # Partial match
    for stock in stock_list:
        searchable = (
            f"{stock.symbol} "
            f"{stock.company_name} "
            f"{stock.sector}"
        ).casefold()

        if (
            clean_query
            in searchable
        ):
            return stock

    return None


def search_stocks(
    query: str,
    stocks: Iterable[
        NSEStock
    ],
    limit: int = 20,
) -> list[
    dict[str, str]
]:
    """
    Search the dynamically loaded NSE sector universe.
    """

    clean_query = " ".join(
        str(
            query or ""
        )
        .strip()
        .split()
    ).casefold()

    if not clean_query:
        return []

    safe_limit = max(
        1,
        min(
            int(limit),
            50,
        ),
    )

    results: list[
        NSEStock
    ] = []

    seen_results: set[
        tuple[str, str]
    ] = set()

    for stock in stocks:
        searchable = (
            f"{stock.symbol} "
            f"{stock.company_name} "
            f"{stock.sector}"
        ).casefold()

        if (
            clean_query
            not in searchable
        ):
            continue

        result_key = (
            stock.symbol,
            stock.sector,
        )

        if result_key in seen_results:
            continue

        seen_results.add(
            result_key
        )

        results.append(
            stock
        )

        if (
            len(results)
            >= safe_limit
        ):
            break

    return stocks_to_dicts(
        results
    )
