from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping


# ---------------------------------------------------------
# Normalized sector names used by Eagle Smart Scanner
# ---------------------------------------------------------
SECTOR_ALIASES: dict[str, str] = {
    "financial services": "Financial Services",
    "finance": "Financial Services",
    "banks": "Financial Services",
    "banking": "Financial Services",

    "information technology": "Information Technology",
    "it": "Information Technology",
    "technology": "Information Technology",

    "oil gas & consumable fuels": "Oil Gas & Consumable Fuels",
    "oil & gas": "Oil Gas & Consumable Fuels",
    "energy": "Oil Gas & Consumable Fuels",

    "fast moving consumer goods": "FMCG",
    "fmcg": "FMCG",

    "automobile and auto components": "Automobile & Auto Components",
    "automobile": "Automobile & Auto Components",
    "auto": "Automobile & Auto Components",

    "healthcare": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "pharma": "Healthcare",

    "metals & mining": "Metals & Mining",
    "metal": "Metals & Mining",
    "metals": "Metals & Mining",

    "consumer durables": "Consumer Durables",

    "consumer services": "Consumer Services",

    "telecommunication": "Telecommunication",
    "telecom": "Telecommunication",

    "power": "Power",

    "construction": "Construction",

    "construction materials": "Construction Materials",

    "realty": "Realty",
    "real estate": "Realty",

    "capital goods": "Capital Goods",

    "chemicals": "Chemicals",

    "services": "Services",

    "textiles": "Textiles",

    "media entertainment & publication": "Media & Entertainment",
    "media": "Media & Entertainment",

    "forest materials": "Forest Materials",

    "diversified": "Diversified",
}


def normalize_sector_name(value: str | None) -> str:
    """
    Convert raw sector names into one consistent sector label.
    """
    if not value:
        return "Unknown"

    clean = " ".join(str(value).strip().split())

    if not clean:
        return "Unknown"

    alias_key = clean.lower()

    return SECTOR_ALIASES.get(alias_key, clean)


def normalize_symbol(symbol: str | None) -> str:
    """
    Normalize NSE stock symbol.

    Examples:
        NSE:RELIANCE-EQ -> RELIANCE
        RELIANCE-EQ     -> RELIANCE
        reliance        -> RELIANCE
    """
    if not symbol:
        return ""

    value = str(symbol).strip().upper()

    if value.startswith("NSE:"):
        value = value[4:]

    if value.endswith("-EQ"):
        value = value[:-3]

    return value.strip()


def to_fyers_symbol(symbol: str | None) -> str:
    """
    Convert normal NSE symbol into FYERS equity format.

    Example:
        RELIANCE -> NSE:RELIANCE-EQ
    """
    clean = normalize_symbol(symbol)

    if not clean:
        return ""

    return f"NSE:{clean}-EQ"


def build_sector_map(
    stocks: Iterable[Mapping[str, object]],
) -> Dict[str, List[dict]]:
    """
    Group stock records sector-wise.

    Expected stock record example:

        {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "sector": "Oil Gas & Consumable Fuels"
        }

    Output:

        {
            "Oil Gas & Consumable Fuels": [
                {...},
                {...}
            ]
        }
    """
    sector_map: defaultdict[str, List[dict]] = defaultdict(list)

    seen_symbols: set[str] = set()

    for stock in stocks:
        symbol = normalize_symbol(
            str(stock.get("symbol", "") or "")
        )

        if not symbol:
            continue

        # Avoid duplicate stocks
        if symbol in seen_symbols:
            continue

        seen_symbols.add(symbol)

        sector = normalize_sector_name(
            str(stock.get("sector", "") or "")
        )

        name = str(
            stock.get("name")
            or stock.get("company_name")
            or symbol
        ).strip()

        sector_map[sector].append(
            {
                "symbol": symbol,
                "fyers_symbol": to_fyers_symbol(symbol),
                "name": name,
                "sector": sector,
            }
        )

    # Stable alphabetical ordering
    result: Dict[str, List[dict]] = {}

    for sector in sorted(sector_map.keys()):
        result[sector] = sorted(
            sector_map[sector],
            key=lambda item: item["symbol"],
        )

    return result


def get_sector_for_symbol(
    symbol: str,
    stocks: Iterable[Mapping[str, object]],
) -> str:
    """
    Return sector for a particular stock symbol.
    """
    target = normalize_symbol(symbol)

    for stock in stocks:
        stock_symbol = normalize_symbol(
            str(stock.get("symbol", "") or "")
        )

        if stock_symbol == target:
            return normalize_sector_name(
                str(stock.get("sector", "") or "")
            )

    return "Unknown"


def flatten_sector_map(
    sector_map: Mapping[str, Iterable[Mapping[str, object]]],
) -> List[dict]:
    """
    Convert a sector-wise dictionary back into one clean stock list.
    """
    stocks: List[dict] = []
    seen: set[str] = set()

    for sector, sector_stocks in sector_map.items():
        clean_sector = normalize_sector_name(sector)

        for stock in sector_stocks:
            symbol = normalize_symbol(
                str(stock.get("symbol", "") or "")
            )

            if not symbol or symbol in seen:
                continue

            seen.add(symbol)

            stocks.append(
                {
                    "symbol": symbol,
                    "fyers_symbol": to_fyers_symbol(symbol),
                    "name": str(
                        stock.get("name")
                        or stock.get("company_name")
                        or symbol
                    ),
                    "sector": clean_sector,
                }
            )

    return stocks


def sector_summary(
    sector_map: Mapping[str, Iterable[Mapping[str, object]]],
) -> List[dict]:
    """
    Simple summary used later by dashboard/debugging.
    """
    rows: List[dict] = []

    for sector, stocks in sector_map.items():
        stock_list = list(stocks)

        rows.append(
            {
                "sector": normalize_sector_name(sector),
                "stock_count": len(stock_list),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            -row["stock_count"],
            row["sector"],
        ),
    )
