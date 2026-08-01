from __future__ import annotations

from collections import Counter
from typing import Iterable

from data.nifty500 import (
    Nifty500Stock,
    get_nifty500_stocks,
)


UNKNOWN_SECTOR = "Unknown"


SECTOR_ALIASES: dict[str, str] = {
    "automobile and auto components": "Automobile",
    "automobiles": "Automobile",
    "auto components": "Automobile",
    "capital goods": "Capital Goods",
    "consumer durables": "Consumer Durables",
    "consumer services": "Consumer Services",
    "fast moving consumer goods": "FMCG",
    "financial services": "Financial Services",
    "healthcare": "Healthcare",
    "information technology": "Information Technology",
    "media entertainment & publication": "Media",
    "media, entertainment & publication": "Media",
    "metals & mining": "Metals and Mining",
    "oil gas & consumable fuels": "Oil and Gas",
    "oil, gas & consumable fuels": "Oil and Gas",
    "power": "Power",
    "realty": "Real Estate",
    "services": "Services",
    "telecommunication": "Telecommunication",
    "textiles": "Textiles",
    "chemicals": "Chemicals",
    "construction": "Construction",
    "construction materials": "Construction Materials",
    "diversified": "Diversified",
    "forest materials": "Forest Materials",
}


SECTOR_GROUPS: dict[str, tuple[str, ...]] = {
    "Banking and Finance": (
        "Bank",
        "Financial Services",
        "Finance",
        "Insurance",
        "Capital Markets",
    ),
    "Technology": (
        "Information Technology",
        "Software",
        "Technology",
        "IT Services",
    ),
    "Consumer": (
        "FMCG",
        "Consumer Durables",
        "Consumer Services",
        "Retail",
    ),
    "Industrials": (
        "Capital Goods",
        "Construction",
        "Construction Materials",
        "Engineering",
        "Industrial Products",
    ),
    "Energy": (
        "Oil and Gas",
        "Power",
        "Energy",
    ),
    "Healthcare": (
        "Healthcare",
        "Pharmaceuticals",
        "Hospitals",
    ),
    "Materials": (
        "Metals and Mining",
        "Chemicals",
        "Cement",
        "Forest Materials",
    ),
    "Automobile": (
        "Automobile",
        "Auto Components",
    ),
    "Communication": (
        "Telecommunication",
        "Media",
    ),
    "Real Estate": (
        "Real Estate",
        "Realty",
    ),
}


def _clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {
        "",
        "nan",
        "none",
        "null",
        "n/a",
        "na",
    }:
        return ""

    return " ".join(text.split())


def normalize_sector_name(sector_name: object) -> str:
    cleaned_sector = _clean_text(sector_name)

    if not cleaned_sector:
        return UNKNOWN_SECTOR

    alias_key = cleaned_sector.casefold()

    if alias_key in SECTOR_ALIASES:
        return SECTOR_ALIASES[alias_key]

    return cleaned_sector


def get_stock_sector(
    symbol: str,
    stocks: Iterable[Nifty500Stock] | None = None,
) -> str:
    normalized_symbol = _clean_text(symbol).upper()

    normalized_symbol = normalized_symbol.replace(
        "NSE:",
        "",
    )
    normalized_symbol = normalized_symbol.replace(
        "-EQ",
        "",
    )
    normalized_symbol = normalized_symbol.replace(
        ".NS",
        "",
    )

    if not normalized_symbol:
        return UNKNOWN_SECTOR

    stock_list = (
        list(stocks)
        if stocks is not None
        else get_nifty500_stocks()
    )

    for stock in stock_list:
        if stock.symbol.upper() == normalized_symbol:
            return normalize_sector_name(stock.industry)

    return UNKNOWN_SECTOR


def build_sector_map(
    force_refresh: bool = False,
) -> dict[str, str]:
    stocks = get_nifty500_stocks(
        force_refresh=force_refresh
    )

    return {
        stock.symbol: normalize_sector_name(
            stock.industry
        )
        for stock in stocks
    }


def get_sector_stocks(
    sector_name: str,
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    normalized_requested_sector = normalize_sector_name(
        sector_name
    ).casefold()

    stocks = get_nifty500_stocks(
        force_refresh=force_refresh
    )

    matching_stocks: list[dict[str, str]] = []

    for stock in stocks:
        normalized_stock_sector = normalize_sector_name(
            stock.industry
        )

        if (
            normalized_stock_sector.casefold()
            != normalized_requested_sector
        ):
            continue

        matching_stocks.append(
            {
                "company_name": stock.company_name,
                "symbol": stock.symbol,
                "sector": normalized_stock_sector,
                "fyers_symbol": stock.fyers_symbol,
            }
        )

    matching_stocks.sort(
        key=lambda item: item["company_name"].casefold()
    )

    return matching_stocks


def get_all_sectors(
    force_refresh: bool = False,
) -> list[str]:
    sector_map = build_sector_map(
        force_refresh=force_refresh
    )

    sectors = {
        sector
        for sector in sector_map.values()
        if sector != UNKNOWN_SECTOR
    }

    return sorted(
        sectors,
        key=str.casefold,
    )


def get_sector_counts(
    force_refresh: bool = False,
) -> dict[str, int]:
    sector_map = build_sector_map(
        force_refresh=force_refresh
    )

    sector_counter = Counter(
        sector_map.values()
    )

    return dict(
        sorted(
            sector_counter.items(),
            key=lambda item: (
                -item[1],
                item[0].casefold(),
            ),
        )
    )


def get_sector_group(
    sector_name: str,
) -> str:
    normalized_sector = normalize_sector_name(
        sector_name
    )

    normalized_sector_casefold = (
        normalized_sector.casefold()
    )

    for group_name, group_sectors in SECTOR_GROUPS.items():
        for group_sector in group_sectors:
            group_sector_casefold = group_sector.casefold()

            if (
                group_sector_casefold
                in normalized_sector_casefold
                or normalized_sector_casefold
                in group_sector_casefold
            ):
                return group_name

    return "Other"


def build_sector_group_map(
    force_refresh: bool = False,
) -> dict[str, str]:
    sector_map = build_sector_map(
        force_refresh=force_refresh
    )

    return {
        symbol: get_sector_group(sector)
        for symbol, sector in sector_map.items()
    }


def get_sector_summary(
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    sector_counts = get_sector_counts(
        force_refresh=force_refresh
    )

    summary: list[dict[str, object]] = []

    for sector, stock_count in sector_counts.items():
        summary.append(
            {
                "sector": sector,
                "sector_group": get_sector_group(
                    sector
                ),
                "stock_count": stock_count,
            }
        )

    return summary


def search_sectors(
    query: str,
    limit: int = 20,
) -> list[str]:
    normalized_query = _clean_text(query).casefold()

    if not normalized_query:
        return []

    safe_limit = max(
        1,
        min(int(limit), 50),
    )

    matched_sectors = [
        sector
        for sector in get_all_sectors()
        if normalized_query in sector.casefold()
    ]

    return matched_sectors[:safe_limit]
