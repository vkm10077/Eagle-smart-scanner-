from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    key: str
    display_name: str
    fyers_symbol: str
    short_name: str
    category: str
    enabled: bool = True

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "fyers_symbol": self.fyers_symbol,
            "short_name": self.short_name,
            "category": self.category,
            "enabled": self.enabled,
        }


MAIN_INDICES: Final[tuple[IndexDefinition, ...]] = (
    IndexDefinition("nifty_50", "NIFTY 50", "NSE:NIFTY50-INDEX", "NIFTY", "benchmark"),
    IndexDefinition("nifty_bank", "NIFTY BANK", "NSE:NIFTYBANK-INDEX", "BANKNIFTY", "benchmark"),
    IndexDefinition("nifty_financial_services", "NIFTY FINANCIAL SERVICES", "NSE:FINNIFTY-INDEX", "FINNIFTY", "benchmark"),
    IndexDefinition("nifty_midcap_select", "NIFTY MIDCAP SELECT", "NSE:MIDCPNIFTY-INDEX", "MIDCPNIFTY", "benchmark"),
    IndexDefinition("nifty_next_50", "NIFTY NEXT 50", "NSE:NIFTYNXT50-INDEX", "NIFTYNXT50", "benchmark"),
    IndexDefinition("india_vix", "INDIA VIX", "NSE:INDIAVIX-INDEX", "INDIAVIX", "volatility"),
)


ACTIVE_SECTORS: Final[tuple[IndexDefinition, ...]] = (
    IndexDefinition("bank", "NIFTY BANK", "NSE:NIFTYBANK-INDEX", "BANK", "sector"),
    IndexDefinition("financial_services", "NIFTY FINANCIAL SERVICES", "NSE:FINNIFTY-INDEX", "FIN SERVICES", "sector"),
    IndexDefinition("information_technology", "NIFTY IT", "NSE:NIFTYIT-INDEX", "IT", "sector"),
    IndexDefinition("auto", "NIFTY AUTO", "NSE:NIFTYAUTO-INDEX", "AUTO", "sector"),
    IndexDefinition("fmcg", "NIFTY FMCG", "NSE:NIFTYFMCG-INDEX", "FMCG", "sector"),
    IndexDefinition("pharma", "NIFTY PHARMA", "NSE:NIFTYPHARMA-INDEX", "PHARMA", "sector"),
    IndexDefinition("healthcare", "NIFTY HEALTHCARE", "NSE:NIFTYHEALTHCARE-INDEX", "HEALTHCARE", "sector"),
    IndexDefinition("metal", "NIFTY METAL", "NSE:NIFTYMETAL-INDEX", "METAL", "sector"),
    IndexDefinition("realty", "NIFTY REALTY", "NSE:NIFTYREALTY-INDEX", "REALTY", "sector"),
    IndexDefinition("media", "NIFTY MEDIA", "NSE:NIFTYMEDIA-INDEX", "MEDIA", "sector"),
    IndexDefinition("psu_bank", "NIFTY PSU BANK", "NSE:NIFTYPSUBANK-INDEX", "PSU BANK", "sector"),
    IndexDefinition("private_bank", "NIFTY PRIVATE BANK", "NSE:NIFTYPVTBANK-INDEX", "PRIVATE BANK", "sector"),
    IndexDefinition("energy", "NIFTY ENERGY", "NSE:NIFTYENERGY-INDEX", "ENERGY", "sector"),
    IndexDefinition("oil_gas", "NIFTY OIL & GAS", "NSE:NIFTYOILANDGAS-INDEX", "OIL & GAS", "sector"),
    IndexDefinition("consumer_durables", "NIFTY CONSUMER DURABLES", "NSE:NIFTYCONSRDURBL-INDEX", "CONSUMER DURABLES", "sector"),
    IndexDefinition("commodities", "NIFTY COMMODITIES", "NSE:NIFTYCOMMODITIES-INDEX", "COMMODITIES", "sector"),
    IndexDefinition("consumption", "NIFTY INDIA CONSUMPTION", "NSE:NIFTYCONSUMPTION-INDEX", "CONSUMPTION", "sector"),
    IndexDefinition("infrastructure", "NIFTY INFRASTRUCTURE", "NSE:NIFTYINFRA-INDEX", "INFRA", "sector"),
    IndexDefinition("chemicals", "NIFTY CHEMICALS", "NSE:NIFTYCHEMICALS-INDEX", "CHEMICALS", "sector"),
    IndexDefinition("capital_markets", "NIFTY CAPITAL MARKETS", "NSE:NIFTYCAPITALMKT-INDEX", "CAPITAL MARKETS", "sector"),
)


MAIN_INDEX_BY_KEY: Final[dict[str, IndexDefinition]] = {
    item.key: item for item in MAIN_INDICES
}

SECTOR_BY_KEY: Final[dict[str, IndexDefinition]] = {
    item.key: item for item in ACTIVE_SECTORS
}

INDEX_BY_SYMBOL: Final[dict[str, IndexDefinition]] = {
    item.fyers_symbol: item for item in (*MAIN_INDICES, *ACTIVE_SECTORS)
}


def normalize_key(value: str | None) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("&", "and")
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )


def get_sector(key: str) -> IndexDefinition:
    normalized = normalize_key(key)
    aliases = {
        "it": "information_technology",
        "fin_services": "financial_services",
        "financial_service": "financial_services",
        "pvt_bank": "private_bank",
        "oil_and_gas": "oil_gas",
        "consumer_durable": "consumer_durables",
        "infra": "infrastructure",
        "capital_market": "capital_markets",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return SECTOR_BY_KEY[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown Eagle sector: {key}") from exc


def get_main_index(key: str) -> IndexDefinition:
    normalized = normalize_key(key)
    aliases = {
        "nifty": "nifty_50",
        "nifty50": "nifty_50",
        "banknifty": "nifty_bank",
        "niftybank": "nifty_bank",
        "finnifty": "nifty_financial_services",
        "midcpnifty": "nifty_midcap_select",
        "niftynext50": "nifty_next_50",
        "nifty_next50": "nifty_next_50",
        "vix": "india_vix",
        "indiavix": "india_vix",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return MAIN_INDEX_BY_KEY[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown main index: {key}") from exc


def sector_symbols() -> list[str]:
    return [item.fyers_symbol for item in ACTIVE_SECTORS if item.enabled]


def main_index_symbols() -> list[str]:
    return [item.fyers_symbol for item in MAIN_INDICES if item.enabled]


def all_required_index_symbols() -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in (*MAIN_INDICES, *ACTIVE_SECTORS):
        if item.enabled and item.fyers_symbol not in seen:
            seen.add(item.fyers_symbol)
            output.append(item.fyers_symbol)
    return output


def serialize_definitions(
    definitions: Iterable[IndexDefinition],
) -> list[dict[str, str | bool]]:
    return [item.as_dict() for item in definitions]


def public_sector_map() -> list[dict[str, str | bool]]:
    return serialize_definitions(ACTIVE_SECTORS)


def public_main_index_map() -> list[dict[str, str | bool]]:
    return serialize_definitions(MAIN_INDICES)


if len(ACTIVE_SECTORS) != 20:
    raise RuntimeError(
        f"Eagle sector universe must contain exactly 20 sectors; found {len(ACTIVE_SECTORS)}."
    )

_sector_keys = [item.key for item in ACTIVE_SECTORS]
if len(_sector_keys) != len(set(_sector_keys)):
    raise RuntimeError("Duplicate sector key found in ACTIVE_SECTORS.")

_sector_symbols = [item.fyers_symbol for item in ACTIVE_SECTORS]
if len(_sector_symbols) != len(set(_sector_symbols)):
    raise RuntimeError("Duplicate FYERS sector symbol found.")

_main_keys = [item.key for item in MAIN_INDICES]
if len(_main_keys) != len(set(_main_keys)):
    raise RuntimeError("Duplicate main-index key found.")

for _definition in (*MAIN_INDICES, *ACTIVE_SECTORS):
    if not _definition.fyers_symbol.startswith("NSE:"):
        raise RuntimeError(f"Invalid NSE FYERS symbol: {_definition.fyers_symbol}")
    if not _definition.fyers_symbol.endswith("-INDEX"):
        raise RuntimeError(
            f"Expected index symbol ending in -INDEX: {_definition.fyers_symbol}"
        )
    if not _definition.key.strip():
        raise RuntimeError("Index definition key cannot be blank.")
    if not _definition.display_name.strip():
        raise RuntimeError("Index display name cannot be blank.")

