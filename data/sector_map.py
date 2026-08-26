from __future__ import annotations

"""
Eagle Smart Scanner - NSE Sector Map

Purpose
-------
This module contains ONLY sector/index metadata and normalization helpers.

It does NOT contain:
- NIFTY 500 universe
- fundamental filters
- hard-coded "top stocks"
- BUY/SELL logic
- scanner scoring logic

Top sectors are selected dynamically by services/sector_scanner.py.
Top stocks inside those sectors are selected dynamically by
services/nse_sector_universe_service.py + services/stock_ranker.py.
"""

from typing import Final


# ============================================================
# BENCHMARK INDICES
# ============================================================

BENCHMARK_INDICES: Final[dict[str, dict[str, str]]] = {
    "NIFTY_50": {
        "name": "NIFTY 50",
        "fyers_symbol": "NSE:NIFTY50-INDEX",
        "type": "benchmark",
    },
    "NIFTY_BANK": {
        "name": "NIFTY BANK",
        "fyers_symbol": "NSE:NIFTYBANK-INDEX",
        "type": "benchmark",
    },
}


# ============================================================
# SECTOR INDEX MASTER
# ============================================================
#
# These are candidate NSE sector/thematic indices from which the
# scanner will dynamically rank and select TOP_SECTORS_COUNT.
#
# The order here is NOT a performance ranking.
# ============================================================

SECTOR_INDEX_MASTER: Final[dict[str, dict[str, str]]] = {
    "BANK": {
        "name": "NIFTY BANK",
        "fyers_symbol": "NSE:NIFTYBANK-INDEX",
        "nse_name": "NIFTY BANK",
        "slug": "bank",
    },
    "FINANCIAL_SERVICES": {
        "name": "NIFTY FINANCIAL SERVICES",
        "fyers_symbol": "NSE:NIFTYFINSERVICE-INDEX",
        "nse_name": "NIFTY FINANCIAL SERVICES",
        "slug": "financial_services",
    },
    "PRIVATE_BANK": {
        "name": "NIFTY PRIVATE BANK",
        "fyers_symbol": "NSE:NIFTYPVTBANK-INDEX",
        "nse_name": "NIFTY PRIVATE BANK",
        "slug": "private_bank",
    },
    "PSU_BANK": {
        "name": "NIFTY PSU BANK",
        "fyers_symbol": "NSE:NIFTYPSUBANK-INDEX",
        "nse_name": "NIFTY PSU BANK",
        "slug": "psu_bank",
    },
    "IT": {
        "name": "NIFTY IT",
        "fyers_symbol": "NSE:NIFTYIT-INDEX",
        "nse_name": "NIFTY IT",
        "slug": "it",
    },
    "AUTO": {
        "name": "NIFTY AUTO",
        "fyers_symbol": "NSE:NIFTYAUTO-INDEX",
        "nse_name": "NIFTY AUTO",
        "slug": "auto",
    },
    "FMCG": {
        "name": "NIFTY FMCG",
        "fyers_symbol": "NSE:NIFTYFMCG-INDEX",
        "nse_name": "NIFTY FMCG",
        "slug": "fmcg",
    },
    "PHARMA": {
        "name": "NIFTY PHARMA",
        "fyers_symbol": "NSE:NIFTYPHARMA-INDEX",
        "nse_name": "NIFTY PHARMA",
        "slug": "pharma",
    },
    "HEALTHCARE": {
        "name": "NIFTY HEALTHCARE INDEX",
        "fyers_symbol": "NSE:NIFTYHEALTHCARE-INDEX",
        "nse_name": "NIFTY HEALTHCARE INDEX",
        "slug": "healthcare",
    },
    "METAL": {
        "name": "NIFTY METAL",
        "fyers_symbol": "NSE:NIFTYMETAL-INDEX",
        "nse_name": "NIFTY METAL",
        "slug": "metal",
    },
    "ENERGY": {
        "name": "NIFTY ENERGY",
        "fyers_symbol": "NSE:NIFTYENERGY-INDEX",
        "nse_name": "NIFTY ENERGY",
        "slug": "energy",
    },
    "OIL_GAS": {
        "name": "NIFTY OIL & GAS",
        "fyers_symbol": "NSE:NIFTYOILANDGAS-INDEX",
        "nse_name": "NIFTY OIL & GAS",
        "slug": "oil_gas",
    },
    "REALTY": {
        "name": "NIFTY REALTY",
        "fyers_symbol": "NSE:NIFTYREALTY-INDEX",
        "nse_name": "NIFTY REALTY",
        "slug": "realty",
    },
    "MEDIA": {
        "name": "NIFTY MEDIA",
        "fyers_symbol": "NSE:NIFTYMEDIA-INDEX",
        "nse_name": "NIFTY MEDIA",
        "slug": "media",
    },
    "CONSUMER_DURABLES": {
        "name": "NIFTY CONSUMER DURABLES",
        "fyers_symbol": "NSE:NIFTYCONSRDURBL-INDEX",
        "nse_name": "NIFTY CONSUMER DURABLES",
        "slug": "consumer_durables",
    },
}


# ============================================================
# SECTOR ALIASES
# ============================================================

SECTOR_ALIASES: Final[dict[str, str]] = {
    # Bank
    "BANK": "BANK",
    "BANKING": "BANK",
    "NIFTY BANK": "BANK",
    "NIFTYBANK": "BANK",

    # Financial Services
    "FINANCIAL": "FINANCIAL_SERVICES",
    "FINANCIAL SERVICES": "FINANCIAL_SERVICES",
    "FIN SERVICES": "FINANCIAL_SERVICES",
    "FIN SERVICE": "FINANCIAL_SERVICES",
    "NIFTY FINANCIAL SERVICES": "FINANCIAL_SERVICES",
    "NIFTYFINSERVICE": "FINANCIAL_SERVICES",

    # Private Bank
    "PRIVATE BANK": "PRIVATE_BANK",
    "PVT BANK": "PRIVATE_BANK",
    "NIFTY PRIVATE BANK": "PRIVATE_BANK",
    "NIFTYPVTBANK": "PRIVATE_BANK",

    # PSU Bank
    "PSU BANK": "PSU_BANK",
    "PUBLIC SECTOR BANK": "PSU_BANK",
    "NIFTY PSU BANK": "PSU_BANK",
    "NIFTYPSUBANK": "PSU_BANK",

    # IT
    "IT": "IT",
    "INFORMATION TECHNOLOGY": "IT",
    "NIFTY IT": "IT",
    "NIFTYIT": "IT",

    # Auto
    "AUTO": "AUTO",
    "AUTOMOBILE": "AUTO",
    "AUTOMOTIVE": "AUTO",
    "NIFTY AUTO": "AUTO",
    "NIFTYAUTO": "AUTO",

    # FMCG
    "FMCG": "FMCG",
    "NIFTY FMCG": "FMCG",
    "NIFTYFMCG": "FMCG",

    # Pharma
    "PHARMA": "PHARMA",
    "PHARMACEUTICAL": "PHARMA",
    "PHARMACEUTICALS": "PHARMA",
    "NIFTY PHARMA": "PHARMA",
    "NIFTYPHARMA": "PHARMA",

    # Healthcare
    "HEALTHCARE": "HEALTHCARE",
    "HEALTH CARE": "HEALTHCARE",
    "NIFTY HEALTHCARE": "HEALTHCARE",
    "NIFTY HEALTHCARE INDEX": "HEALTHCARE",
    "NIFTYHEALTHCARE": "HEALTHCARE",

    # Metal
    "METAL": "METAL",
    "METALS": "METAL",
    "NIFTY METAL": "METAL",
    "NIFTYMETAL": "METAL",

    # Energy
    "ENERGY": "ENERGY",
    "NIFTY ENERGY": "ENERGY",
    "NIFTYENERGY": "ENERGY",

    # Oil & Gas
    "OIL & GAS": "OIL_GAS",
    "OIL AND GAS": "OIL_GAS",
    "OIL GAS": "OIL_GAS",
    "NIFTY OIL & GAS": "OIL_GAS",
    "NIFTY OIL AND GAS": "OIL_GAS",
    "NIFTYOILANDGAS": "OIL_GAS",

    # Realty
    "REALTY": "REALTY",
    "REAL ESTATE": "REALTY",
    "NIFTY REALTY": "REALTY",
    "NIFTYREALTY": "REALTY",

    # Media
    "MEDIA": "MEDIA",
    "NIFTY MEDIA": "MEDIA",
    "NIFTYMEDIA": "MEDIA",

    # Consumer Durables
    "CONSUMER DURABLES": "CONSUMER_DURABLES",
    "CONSUMER DURABLE": "CONSUMER_DURABLES",
    "DURABLES": "CONSUMER_DURABLES",
    "NIFTY CONSUMER DURABLES": "CONSUMER_DURABLES",
    "NIFTYCONSRDURBL": "CONSUMER_DURABLES",
}


# ============================================================
# LEGACY COMPATIBILITY
# ============================================================
#
# Deliberately empty.
#
# Old NIFTY500 code may import STOCK_SECTOR_MAP.
# The new Eagle Smart Scanner must NOT depend on a hard-coded
# NIFTY500 stock-to-sector dictionary.
#
# Actual constituents are obtained dynamically by
# nse_sector_universe_service.py.
# ============================================================

STOCK_SECTOR_MAP: Final[dict[str, str]] = {}


# ============================================================
# HELPERS
# ============================================================

def _clean_text(value: str | None) -> str:
    text = str(value or "").strip().upper()

    text = (
        text.replace("_", " ")
        .replace("-", " ")
        .replace("/", " ")
    )

    return " ".join(text.split())


def normalize_stock_symbol(symbol: str | None) -> str:
    """
    Convert symbols like:
        NSE:RELIANCE-EQ
        RELIANCE-EQ
        RELIANCE

    into:
        RELIANCE
    """
    value = str(symbol or "").strip().upper()

    if ":" in value:
        value = value.split(":", 1)[1]

    for suffix in ("-EQ", "-BE", "-BZ", "-SM", "-ST"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break

    return value.strip()


def to_fyers_equity_symbol(symbol: str | None) -> str:
    """
    Convert RELIANCE / NSE:RELIANCE-EQ to canonical FYERS equity form.
    """
    value = normalize_stock_symbol(symbol)

    if not value:
        return ""

    return f"NSE:{value}-EQ"


def normalize_sector_key(value: str | None) -> str:
    """
    Resolve human-readable/legacy sector names to the canonical key.

    Examples:
        'Nifty IT' -> 'IT'
        'psu bank' -> 'PSU_BANK'
        'oil and gas' -> 'OIL_GAS'
    """
    cleaned = _clean_text(value)

    if not cleaned:
        return ""

    direct = cleaned.replace(" ", "_")

    if direct in SECTOR_INDEX_MASTER:
        return direct

    return SECTOR_ALIASES.get(cleaned, "")


def get_sector_info(value: str | None) -> dict[str, str]:
    key = normalize_sector_key(value)

    if not key:
        return {}

    return dict(SECTOR_INDEX_MASTER.get(key, {}))


def get_sector_name(value: str | None) -> str:
    info = get_sector_info(value)
    return info.get("name", "")


def get_sector_fyers_symbol(value: str | None) -> str:
    info = get_sector_info(value)
    return info.get("fyers_symbol", "")


def get_sector_nse_name(value: str | None) -> str:
    info = get_sector_info(value)
    return info.get("nse_name", "")


def get_candidate_sector_keys() -> list[str]:
    """
    Return all candidate sector keys.

    sector_scanner.py will rank these dynamically and choose
    Config.TOP_SECTORS_COUNT.
    """
    return list(SECTOR_INDEX_MASTER.keys())


def get_candidate_sector_symbols() -> list[str]:
    return [
        item["fyers_symbol"]
        for item in SECTOR_INDEX_MASTER.values()
        if item.get("fyers_symbol")
    ]


def get_candidate_sectors() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []

    for key, info in SECTOR_INDEX_MASTER.items():
        result.append(
            {
                "key": key,
                "name": info["name"],
                "fyers_symbol": info["fyers_symbol"],
                "nse_name": info["nse_name"],
                "slug": info["slug"],
            }
        )

    return result


def is_supported_sector(value: str | None) -> bool:
    return bool(normalize_sector_key(value))


def sector_key_from_fyers_symbol(symbol: str | None) -> str:
    target = str(symbol or "").strip().upper()

    if not target:
        return ""

    for key, info in SECTOR_INDEX_MASTER.items():
        if info["fyers_symbol"].upper() == target:
            return key

    return ""


def validate_sector_master() -> None:
    """
    Fail early for duplicate/invalid local metadata.
    """
    symbols: set[str] = set()
    slugs: set[str] = set()

    for key, info in SECTOR_INDEX_MASTER.items():
        required = {"name", "fyers_symbol", "nse_name", "slug"}

        missing = required.difference(info)

        if missing:
            raise ValueError(
                f"Sector {key} missing fields: {sorted(missing)}"
            )

        symbol = info["fyers_symbol"].strip().upper()
        slug = info["slug"].strip().lower()

        if not symbol.startswith("NSE:") or not symbol.endswith("-INDEX"):
            raise ValueError(
                f"Invalid FYERS index symbol for {key}: {symbol}"
            )

        if symbol in symbols:
            raise ValueError(
                f"Duplicate FYERS sector symbol: {symbol}"
            )

        if slug in slugs:
            raise ValueError(
                f"Duplicate sector slug: {slug}"
            )

        symbols.add(symbol)
        slugs.add(slug)


validate_sector_master()
