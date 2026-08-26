from __future__ import annotations

"""
Eagle Smart Scanner - NSE Sector Universe Service

Purpose
-------
Fetch the REAL current constituent stocks for NSE/NIFTY sector indices.

Data sources
------------
1) NSE India official equity-stockIndices API
2) Nifty Indices official constituent CSV as fallback

Rules
-----
- No NIFTY500 master universe
- No hard-coded constituent stock list
- No random/fake fallback symbols
- Only official-source constituent data
- Short-lived cache is allowed because constituents do not change tick-by-tick
- If official sources and a valid cache are unavailable, the sector is rejected

The output of this service is consumed by stock_ranker.py.
"""

import csv
import io
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from config import Config
from data.sector_map import (
    get_candidate_sector_keys,
    get_sector_info,
    normalize_sector_key,
    normalize_stock_symbol,
    to_fyers_equity_symbol,
)


class SectorUniverseError(RuntimeError):
    """Base sector-universe error."""


class SectorUniverseUnavailableError(SectorUniverseError):
    """Raised when official constituent data cannot be obtained."""


@dataclass(frozen=True)
class SectorConstituent:
    sector_key: str
    sector_name: str
    symbol: str
    fyers_symbol: str
    company_name: str
    industry: str
    series: str
    weight: float | None
    source: str


@dataclass
class _CacheEntry:
    fetched_at: float
    constituents: list[SectorConstituent]


class NSESectorUniverseService:
    """
    Fetches and caches official sector-index constituents.

    The scanner must NOT assume that every candidate sector is available.
    A sector with unavailable/invalid official constituent data is skipped.
    """

    NSE_HOME_URL = "https://www.nseindia.com"
    NSE_INDEX_API = (
        "https://www.nseindia.com/api/equity-stockIndices?index={index_name}"
    )

    NIFTY_INDICES_BASE = (
        "https://www.niftyindices.com/IndexConstituent/{filename}"
    )

    MEMORY_CACHE_TTL_SECONDS = 6 * 60 * 60
    DISK_CACHE_TTL_SECONDS = 24 * 60 * 60
    HTTP_TIMEOUT_SECONDS = 12

    # Candidate filenames only. These are NOT stock lists.
    # The service tries official NSE API first.
    CSV_FILENAME_CANDIDATES: dict[str, tuple[str, ...]] = {
        "BANK": (
            "ind_niftybanklist.csv",
        ),
        "FINANCIAL_SERVICES": (
            "ind_niftyfinancelist.csv",
            "ind_niftyfinancialserviceslist.csv",
        ),
        "PRIVATE_BANK": (
            "ind_niftyprivatebanklist.csv",
            "ind_niftypvtbanklist.csv",
        ),
        "PSU_BANK": (
            "ind_niftypsubanklist.csv",
        ),
        "IT": (
            "ind_niftyitlist.csv",
        ),
        "AUTO": (
            "ind_niftyautolist.csv",
        ),
        "FMCG": (
            "ind_niftyfmcglist.csv",
        ),
        "PHARMA": (
            "ind_niftypharmalist.csv",
        ),
        "HEALTHCARE": (
            "ind_niftyhealthcarelist.csv",
        ),
        "METAL": (
            "ind_niftymetallist.csv",
        ),
        "ENERGY": (
            "ind_niftyenergylist.csv",
        ),
        "OIL_GAS": (
            "ind_niftyoilgaslist.csv",
            "ind_niftyoilandgaslist.csv",
        ),
        "REALTY": (
            "ind_niftyrealtylist.csv",
        ),
        "MEDIA": (
            "ind_niftymedialist.csv",
        ),
        "CONSUMER_DURABLES": (
            "ind_niftyconsumerdurableslist.csv",
            "ind_niftyconsdurableslist.csv",
        ),
    }

    def __init__(
        self,
        *,
        cache_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, _CacheEntry] = {}

        self.cache_dir = Path(
            cache_dir
            or os.path.join(
                Config.DATA_DIR,
                "sector_universe",
            )
        )

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._session = requests.Session()

        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": (
                    "application/json,text/plain,*/*"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": (
                    "https://www.nseindia.com/market-data/"
                    "live-equity-market"
                ),
                "Connection": "keep-alive",
            }
        )

        self._nse_cookie_initialized = False

    # ========================================================
    # PUBLIC API
    # ========================================================

    def get_sector_constituents(
        self,
        sector: str,
        *,
        force_refresh: bool = False,
    ) -> list[SectorConstituent]:
        sector_key = normalize_sector_key(sector)

        if not sector_key:
            raise SectorUniverseError(
                f"Unsupported sector: {sector}"
            )

        if (
            sector_key
            not in get_candidate_sector_keys()
        ):
            raise SectorUniverseError(
                f"Sector is not part of Eagle candidate universe: "
                f"{sector_key}"
            )

        if not force_refresh:
            cached = self._get_memory_cache(
                sector_key
            )

            if cached is not None:
                return list(cached)

            cached = self._read_disk_cache(
                sector_key
            )

            if cached is not None:
                self._set_memory_cache(
                    sector_key,
                    cached,
                )
                return list(cached)

        errors: list[str] = []

        # First choice: official NSE endpoint.
        try:
            constituents = (
                self._fetch_from_nse_api(
                    sector_key
                )
            )

            if constituents:
                self._save_valid_result(
                    sector_key,
                    constituents,
                )
                return constituents

        except Exception as exc:
            errors.append(
                f"NSE API: {exc}"
            )

        # Second choice: official Nifty Indices constituent CSV.
        try:
            constituents = (
                self._fetch_from_nifty_indices_csv(
                    sector_key
                )
            )

            if constituents:
                self._save_valid_result(
                    sector_key,
                    constituents,
                )
                return constituents

        except Exception as exc:
            errors.append(
                f"Nifty Indices CSV: {exc}"
            )

        raise SectorUniverseUnavailableError(
            f"Unable to obtain official constituents for "
            f"{sector_key}. "
            + " | ".join(errors)
        )

    def get_all_sector_constituents(
        self,
        *,
        force_refresh: bool = False,
    ) -> dict[str, list[SectorConstituent]]:
        result: dict[
            str,
            list[SectorConstituent],
        ] = {}

        for sector_key in get_candidate_sector_keys():
            try:
                constituents = (
                    self.get_sector_constituents(
                        sector_key,
                        force_refresh=force_refresh,
                    )
                )
            except SectorUniverseError:
                continue

            if constituents:
                result[sector_key] = constituents

        return result

    def get_symbols(
        self,
        sector: str,
        *,
        force_refresh: bool = False,
    ) -> list[str]:
        return [
            item.symbol
            for item in self.get_sector_constituents(
                sector,
                force_refresh=force_refresh,
            )
        ]

    def get_fyers_symbols(
        self,
        sector: str,
        *,
        force_refresh: bool = False,
    ) -> list[str]:
        return [
            item.fyers_symbol
            for item in self.get_sector_constituents(
                sector,
                force_refresh=force_refresh,
            )
        ]

    # ========================================================
    # NSE INDIA API
    # ========================================================

    def _fetch_from_nse_api(
        self,
        sector_key: str,
    ) -> list[SectorConstituent]:
        info = get_sector_info(
            sector_key
        )

        index_name = str(
            info.get("nse_name")
            or info.get("name")
            or ""
        ).strip()

        if not index_name:
            raise SectorUniverseError(
                f"Missing NSE index name for {sector_key}"
            )

        self._ensure_nse_cookie()

        url = self.NSE_INDEX_API.format(
            index_name=quote(
                index_name,
                safe="",
            )
        )

        response = self._session.get(
            url,
            timeout=self.HTTP_TIMEOUT_SECONDS,
        )

        # NSE can invalidate cookies; retry once with a fresh session cookie.
        if response.status_code in {
            401,
            403,
        }:
            self._nse_cookie_initialized = False
            self._ensure_nse_cookie()

            response = self._session.get(
                url,
                timeout=self.HTTP_TIMEOUT_SECONDS,
            )

        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, dict):
            raise SectorUniverseError(
                "NSE response is not a JSON object."
            )

        data = payload.get("data")

        if not isinstance(data, list):
            raise SectorUniverseError(
                "NSE response does not contain a valid data list."
            )

        result: list[
            SectorConstituent
        ] = []

        for row in data:
            if not isinstance(row, dict):
                continue

            symbol = normalize_stock_symbol(
                row.get("symbol")
            )

            if not self._valid_equity_symbol(
                symbol
            ):
                continue

            # Some NSE index responses can include the index itself.
            if symbol.startswith("NIFTY"):
                continue

            company_name = str(
                row.get("meta", {}).get(
                    "companyName",
                    "",
                )
                if isinstance(
                    row.get("meta"),
                    dict,
                )
                else ""
            ).strip()

            industry = str(
                row.get("meta", {}).get(
                    "industry",
                    "",
                )
                if isinstance(
                    row.get("meta"),
                    dict,
                )
                else ""
            ).strip()

            series = str(
                row.get("meta", {}).get(
                    "series",
                    "EQ",
                )
                if isinstance(
                    row.get("meta"),
                    dict,
                )
                else "EQ"
            ).strip().upper()

            weight = self._optional_float(
                row.get("weightage")
                or row.get("weight")
            )

            result.append(
                SectorConstituent(
                    sector_key=sector_key,
                    sector_name=str(
                        info.get("name")
                        or sector_key
                    ),
                    symbol=symbol,
                    fyers_symbol=(
                        to_fyers_equity_symbol(
                            symbol
                        )
                    ),
                    company_name=company_name,
                    industry=industry,
                    series=series or "EQ",
                    weight=weight,
                    source="nse_india",
                )
            )

        return self._validate_constituents(
            sector_key,
            result,
        )

    def _ensure_nse_cookie(
        self,
    ) -> None:
        if self._nse_cookie_initialized:
            return

        response = self._session.get(
            self.NSE_HOME_URL,
            timeout=self.HTTP_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        self._nse_cookie_initialized = True

    # ========================================================
    # NIFTY INDICES CSV FALLBACK
    # ========================================================

    def _fetch_from_nifty_indices_csv(
        self,
        sector_key: str,
    ) -> list[SectorConstituent]:
        filenames = (
            self.CSV_FILENAME_CANDIDATES.get(
                sector_key,
                (),
            )
        )

        if not filenames:
            raise SectorUniverseError(
                f"No official CSV filename candidate "
                f"configured for {sector_key}."
            )

        errors: list[str] = []

        for filename in filenames:
            try:
                result = self._fetch_one_csv(
                    sector_key,
                    filename,
                )

                if result:
                    return result

            except Exception as exc:
                errors.append(
                    f"{filename}: {exc}"
                )

        raise SectorUniverseError(
            " | ".join(errors)
            or "No official constituent CSV available."
        )

    def _fetch_one_csv(
        self,
        sector_key: str,
        filename: str,
    ) -> list[SectorConstituent]:
        url = self.NIFTY_INDICES_BASE.format(
            filename=filename
        )

        response = self._session.get(
            url,
            timeout=self.HTTP_TIMEOUT_SECONDS,
            headers={
                "Referer": "https://www.niftyindices.com/",
                "Accept": (
                    "text/csv,text/plain,*/*"
                ),
            },
        )

        response.raise_for_status()

        text = response.text

        if not text.strip():
            raise SectorUniverseError(
                "CSV response is empty."
            )

        reader = csv.DictReader(
            io.StringIO(text)
        )

        info = get_sector_info(
            sector_key
        )

        result: list[
            SectorConstituent
        ] = []

        for row in reader:
            normalized_row = {
                str(key or "")
                .strip()
                .lower()
                .replace(" ", "")
                .replace("_", ""): value
                for key, value in row.items()
            }

            raw_symbol = (
                normalized_row.get("symbol")
                or normalized_row.get(
                    "ticker"
                )
                or ""
            )

            symbol = normalize_stock_symbol(
                raw_symbol
            )

            if not self._valid_equity_symbol(
                symbol
            ):
                continue

            company_name = str(
                normalized_row.get(
                    "companyname"
                )
                or normalized_row.get(
                    "company"
                )
                or ""
            ).strip()

            industry = str(
                normalized_row.get(
                    "industry"
                )
                or ""
            ).strip()

            series = str(
                normalized_row.get(
                    "series"
                )
                or "EQ"
            ).strip().upper()

            weight = self._optional_float(
                normalized_row.get(
                    "weightage"
                )
                or normalized_row.get(
                    "weight"
                )
            )

            result.append(
                SectorConstituent(
                    sector_key=sector_key,
                    sector_name=str(
                        info.get("name")
                        or sector_key
                    ),
                    symbol=symbol,
                    fyers_symbol=(
                        to_fyers_equity_symbol(
                            symbol
                        )
                    ),
                    company_name=company_name,
                    industry=industry,
                    series=series or "EQ",
                    weight=weight,
                    source=(
                        "nifty_indices_csv"
                    ),
                )
            )

        return self._validate_constituents(
            sector_key,
            result,
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def _validate_constituents(
        self,
        sector_key: str,
        rows: list[SectorConstituent],
    ) -> list[SectorConstituent]:
        seen: set[str] = set()

        valid: list[
            SectorConstituent
        ] = []

        for row in rows:
            symbol = normalize_stock_symbol(
                row.symbol
            )

            if not self._valid_equity_symbol(
                symbol
            ):
                continue

            if symbol in seen:
                continue

            fyers_symbol = (
                to_fyers_equity_symbol(
                    symbol
                )
            )

            if not fyers_symbol:
                continue

            seen.add(symbol)

            valid.append(
                SectorConstituent(
                    sector_key=sector_key,
                    sector_name=row.sector_name,
                    symbol=symbol,
                    fyers_symbol=fyers_symbol,
                    company_name=row.company_name,
                    industry=row.industry,
                    series=row.series or "EQ",
                    weight=row.weight,
                    source=row.source,
                )
            )

        # A real NIFTY sector index should not resolve to 0 or 1 stocks.
        # This catches HTML/error pages incorrectly parsed as CSV.
        if len(valid) < 2:
            raise SectorUniverseError(
                f"Official source returned too few valid "
                f"constituents for {sector_key}: {len(valid)}"
            )

        return valid

    @staticmethod
    def _valid_equity_symbol(
        symbol: str,
    ) -> bool:
        value = str(
            symbol or ""
        ).strip().upper()

        if not value:
            return False

        if len(value) > 30:
            return False

        invalid = {
            "SYMBOL",
            "INDEX",
            "NIFTY",
            "NA",
            "N/A",
            "-",
        }

        if value in invalid:
            return False

        return True

    # ========================================================
    # MEMORY CACHE
    # ========================================================

    def _get_memory_cache(
        self,
        sector_key: str,
    ) -> list[SectorConstituent] | None:
        now = time.time()

        with self._lock:
            entry = self._cache.get(
                sector_key
            )

            if entry is None:
                return None

            age = (
                now
                - entry.fetched_at
            )

            if (
                age
                > self.MEMORY_CACHE_TTL_SECONDS
            ):
                self._cache.pop(
                    sector_key,
                    None,
                )
                return None

            return list(
                entry.constituents
            )

    def _set_memory_cache(
        self,
        sector_key: str,
        constituents: list[SectorConstituent],
    ) -> None:
        with self._lock:
            self._cache[sector_key] = (
                _CacheEntry(
                    fetched_at=time.time(),
                    constituents=list(
                        constituents
                    ),
                )
            )

    # ========================================================
    # DISK CACHE
    # ========================================================

    def _cache_file(
        self,
        sector_key: str,
    ) -> Path:
        safe_name = (
            sector_key.lower()
            .replace("/", "_")
            .replace(" ", "_")
        )

        return (
            self.cache_dir
            / f"{safe_name}.json"
        )

    def _read_disk_cache(
        self,
        sector_key: str,
    ) -> list[SectorConstituent] | None:
        path = self._cache_file(
            sector_key
        )

        if not path.exists():
            return None

        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return None

        if not isinstance(
            payload,
            dict,
        ):
            return None

        fetched_at = self._optional_float(
            payload.get("fetched_at")
        )

        if fetched_at is None:
            return None

        age = (
            time.time()
            - fetched_at
        )

        if age > self.DISK_CACHE_TTL_SECONDS:
            return None

        raw_rows = payload.get(
            "constituents"
        )

        if not isinstance(
            raw_rows,
            list,
        ):
            return None

        rows: list[
            SectorConstituent
        ] = []

        for item in raw_rows:
            if not isinstance(
                item,
                dict,
            ):
                continue

            try:
                rows.append(
                    SectorConstituent(
                        sector_key=str(
                            item.get(
                                "sector_key",
                                sector_key,
                            )
                        ),
                        sector_name=str(
                            item.get(
                                "sector_name",
                                "",
                            )
                        ),
                        symbol=str(
                            item.get(
                                "symbol",
                                "",
                            )
                        ),
                        fyers_symbol=str(
                            item.get(
                                "fyers_symbol",
                                "",
                            )
                        ),
                        company_name=str(
                            item.get(
                                "company_name",
                                "",
                            )
                        ),
                        industry=str(
                            item.get(
                                "industry",
                                "",
                            )
                        ),
                        series=str(
                            item.get(
                                "series",
                                "EQ",
                            )
                        ),
                        weight=(
                            self._optional_float(
                                item.get(
                                    "weight"
                                )
                            )
                        ),
                        source=str(
                            item.get(
                                "source",
                                "cache",
                            )
                        ),
                    )
                )
            except Exception:
                continue

        try:
            rows = self._validate_constituents(
                sector_key,
                rows,
            )
        except SectorUniverseError:
            return None

        return rows

    def _write_disk_cache(
        self,
        sector_key: str,
        constituents: list[SectorConstituent],
    ) -> None:
        path = self._cache_file(
            sector_key
        )

        payload = {
            "sector_key": sector_key,
            "fetched_at": time.time(),
            "constituents": [
                asdict(item)
                for item in constituents
            ],
        }

        temp_path = path.with_suffix(
            ".tmp"
        )

        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            ),
            encoding="utf-8",
        )

        temp_path.replace(path)

    def _save_valid_result(
        self,
        sector_key: str,
        constituents: list[SectorConstituent],
    ) -> None:
        validated = (
            self._validate_constituents(
                sector_key,
                constituents,
            )
        )

        self._set_memory_cache(
            sector_key,
            validated,
        )

        try:
            self._write_disk_cache(
                sector_key,
                validated,
            )
        except Exception:
            # Failure to persist cache must not corrupt valid live result.
            pass

    # ========================================================
    # CACHE / HEALTH
    # ========================================================

    def clear_cache(
        self,
        sector: str | None = None,
    ) -> None:
        if sector is None:
            with self._lock:
                self._cache.clear()

            for path in self.cache_dir.glob(
                "*.json"
            ):
                try:
                    path.unlink()
                except OSError:
                    pass

            return

        sector_key = normalize_sector_key(
            sector
        )

        if not sector_key:
            return

        with self._lock:
            self._cache.pop(
                sector_key,
                None,
            )

        path = self._cache_file(
            sector_key
        )

        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def health(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            memory_keys = sorted(
                self._cache.keys()
            )

        disk_files = sorted(
            path.stem
            for path in self.cache_dir.glob(
                "*.json"
            )
        )

        return {
            "candidate_sectors": len(
                get_candidate_sector_keys()
            ),
            "memory_cached_sectors": (
                memory_keys
            ),
            "disk_cached_sectors": (
                disk_files
            ),
            "memory_cache_ttl_seconds": (
                self.MEMORY_CACHE_TTL_SECONDS
            ),
            "disk_cache_ttl_seconds": (
                self.DISK_CACHE_TTL_SECONDS
            ),
            "fake_constituents_allowed": False,
        }

    # ========================================================
    # SMALL HELPERS
    # ========================================================

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        text = (
            text.replace("%", "")
            .replace(",", "")
        )

        try:
            return float(text)
        except (
            TypeError,
            ValueError,
        ):
            return None


# ============================================================
# SINGLETON
# ============================================================

_default_sector_universe_service: (
    NSESectorUniverseService | None
) = None

_default_sector_universe_lock = (
    threading.Lock()
)


def get_nse_sector_universe_service(
) -> NSESectorUniverseService:
    global _default_sector_universe_service

    if (
        _default_sector_universe_service
        is not None
    ):
        return (
            _default_sector_universe_service
        )

    with _default_sector_universe_lock:
        if (
            _default_sector_universe_service
            is None
        ):
            _default_sector_universe_service = (
                NSESectorUniverseService()
            )

    return (
        _default_sector_universe_service
    )


# ============================================================
# BACKWARD-COMPATIBLE HELPERS
# ============================================================

def get_sector_constituents(
    sector: str,
    *,
    force_refresh: bool = False,
) -> list[SectorConstituent]:
    return (
        get_nse_sector_universe_service()
        .get_sector_constituents(
            sector,
            force_refresh=force_refresh,
        )
    )


def get_sector_symbols(
    sector: str,
    *,
    force_refresh: bool = False,
) -> list[str]:
    return (
        get_nse_sector_universe_service()
        .get_symbols(
            sector,
            force_refresh=force_refresh,
        )
    )


def get_sector_fyers_symbols(
    sector: str,
    *,
    force_refresh: bool = False,
) -> list[str]:
    return (
        get_nse_sector_universe_service()
        .get_fyers_symbols(
            sector,
            force_refresh=force_refresh,
        )
    )
