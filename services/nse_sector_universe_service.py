from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from io import StringIO
from typing import Any

import pandas as pd
import requests

from data.nse_universe import (
    NSEStock,
    clean_stock_universe,
)
from utils.helpers import (
    clean_text,
    normalize_symbol,
    utc_now,
)


logger = logging.getLogger(
    "services.nse_sector_universe_service"
)


class NSESectorUniverseError(
    RuntimeError
):
    """Raised when sector constituent data cannot be loaded."""


@dataclass(frozen=True)
class SectorSource:
    sector: str
    index_name: str
    csv_url: str


class NSESectorUniverseService:
    """
    Loads NSE sector-wise stock constituents dynamically.

    IMPORTANT:
    - No NIFTY 500 dependency.
    - No fixed 500-stock universe.
    - Stocks come from official sector-index constituent files.
    - Sector constituents can change when the index provider updates them.

    Flow:
        Sector constituent source
            ↓
        Sector-wise stocks
            ↓
        Technical metrics
            ↓
        Rank all sectors
            ↓
        Top 10 sectors
            ↓
        Top 10 stocks per selected sector
    """

    REQUEST_TIMEOUT_SECONDS = 25

    CACHE_SECONDS = (
        6 * 60 * 60
    )

    BASE_URL = (
        "https://www.niftyindices.com/"
        "IndexConstituent/"
    )

    # ---------------------------------------------------------
    # SECTOR SOURCES
    #
    # This is NOT a fixed stock list.
    # Only official sector-index source definitions are listed.
    # Actual stocks are downloaded dynamically.
    # ---------------------------------------------------------

    SECTOR_SOURCES: tuple[
        SectorSource,
        ...,
    ] = (
        SectorSource(
            sector="Automobile & Auto Components",
            index_name="Nifty Auto",
            csv_url=(
                BASE_URL
                + "ind_niftyautolist.csv"
            ),
        ),

        SectorSource(
            sector="Financial Services",
            index_name="Nifty Bank",
            csv_url=(
                BASE_URL
                + "ind_niftybanklist.csv"
            ),
        ),

        SectorSource(
            sector="Financial Services",
            index_name="Nifty Financial Services",
            csv_url=(
                BASE_URL
                + "ind_niftyfinancelist.csv"
            ),
        ),

        SectorSource(
            sector="FMCG",
            index_name="Nifty FMCG",
            csv_url=(
                BASE_URL
                + "ind_niftyfmcglist.csv"
            ),
        ),

        SectorSource(
            sector="Information Technology",
            index_name="Nifty IT",
            csv_url=(
                BASE_URL
                + "ind_niftyitlist.csv"
            ),
        ),

        SectorSource(
            sector="Media & Entertainment",
            index_name="Nifty Media",
            csv_url=(
                BASE_URL
                + "ind_niftymedialist.csv"
            ),
        ),

        SectorSource(
            sector="Metals & Mining",
            index_name="Nifty Metal",
            csv_url=(
                BASE_URL
                + "ind_niftymetallist.csv"
            ),
        ),

        SectorSource(
            sector="Healthcare",
            index_name="Nifty Pharma",
            csv_url=(
                BASE_URL
                + "ind_niftypharmalist.csv"
            ),
        ),

        SectorSource(
            sector="Realty",
            index_name="Nifty Realty",
            csv_url=(
                BASE_URL
                + "ind_niftyrealtylist.csv"
            ),
        ),

        SectorSource(
            sector="Consumer Durables",
            index_name="Nifty Consumer Durables",
            csv_url=(
                BASE_URL
                + "ind_niftyconsumerdurableslist.csv"
            ),
        ),

        SectorSource(
            sector="Oil Gas & Consumable Fuels",
            index_name="Nifty Oil & Gas",
            csv_url=(
                BASE_URL
                + "ind_niftyoilgaslist.csv"
            ),
        ),

        SectorSource(
            sector="Healthcare",
            index_name="Nifty Healthcare",
            csv_url=(
                BASE_URL
                + "ind_niftyhealthcarelist.csv"
            ),
        ),

        SectorSource(
            sector="Chemicals",
            index_name="Nifty Chemicals",
            csv_url=(
                BASE_URL
                + "ind_niftychemicalslist.csv"
            ),
        ),

        SectorSource(
            sector="Telecommunication",
            index_name="Nifty Telecommunications",
            csv_url=(
                BASE_URL
                + "ind_niftytelecommunicationslist.csv"
            ),
        ),

        SectorSource(
            sector="Power",
            index_name="Nifty Power",
            csv_url=(
                BASE_URL
                + "ind_niftypowerlist.csv"
            ),
        ),

        SectorSource(
            sector="Capital Goods",
            index_name="Nifty Capital Goods",
            csv_url=(
                BASE_URL
                + "ind_niftycapitalgoodslist.csv"
            ),
        ),

        SectorSource(
            sector="Construction",
            index_name="Nifty Construction",
            csv_url=(
                BASE_URL
                + "ind_niftyconstructionlist.csv"
            ),
        ),

        SectorSource(
            sector="Consumer Services",
            index_name="Nifty Consumer Services",
            csv_url=(
                BASE_URL
                + "ind_niftyconsumerserviceslist.csv"
            ),
        ),

        SectorSource(
            sector="Financial Services",
            index_name="Nifty NBFC",
            csv_url=(
                BASE_URL
                + "ind_niftynbfclist.csv"
            ),
        ),

        SectorSource(
            sector="Financial Services",
            index_name="Nifty Insurance",
            csv_url=(
                BASE_URL
                + "ind_niftyinsurancelist.csv"
            ),
        ),
    )

    def __init__(
        self,
    ) -> None:
        self._lock = (
            threading.RLock()
        )

        self._cached_stocks: list[
            NSEStock
        ] = []

        self._cached_sector_map: dict[
            str,
            list[NSEStock],
        ] = {}

        self._cache_timestamp = 0.0

    # =========================================================
    # HTTP
    # =========================================================

    @staticmethod
    def _headers(
    ) -> dict[str, str]:

        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": (
                "text/csv,"
                "application/csv,"
                "text/plain,"
                "*/*"
            ),
            "Accept-Language": (
                "en-IN,en;q=0.9"
            ),
            "Referer": (
                "https://www.niftyindices.com/"
            ),
            "Cache-Control": (
                "no-cache"
            ),
        }

    # =========================================================
    # CSV HELPERS
    # =========================================================

    @staticmethod
    def _find_column(
        dataframe: pd.DataFrame,
        possible_names: list[str],
    ) -> str | None:

        normalized = {
            str(column)
            .strip()
            .casefold(): str(column)
            for column
            in dataframe.columns
        }

        for name in possible_names:

            key = (
                str(name)
                .strip()
                .casefold()
            )

            if key in normalized:
                return normalized[
                    key
                ]

        return None

    def _parse_csv(
        self,
        *,
        csv_text: str,
        source: SectorSource,
    ) -> list[dict[str, str]]:

        if not csv_text.strip():
            raise NSESectorUniverseError(
                (
                    f"{source.index_name}: "
                    "empty constituent file."
                )
            )

        try:
            dataframe = pd.read_csv(
                StringIO(
                    csv_text
                )
            )

        except Exception as exception:
            raise NSESectorUniverseError(
                (
                    f"{source.index_name}: "
                    "unable to parse constituent CSV."
                )
            ) from exception

        dataframe.columns = [
            str(column).strip()
            for column
            in dataframe.columns
        ]

        if dataframe.empty:
            raise NSESectorUniverseError(
                (
                    f"{source.index_name}: "
                    "no constituents found."
                )
            )

        symbol_column = (
            self._find_column(
                dataframe,
                [
                    "Symbol",
                    "Ticker",
                    "Trading Symbol",
                ],
            )
        )

        company_column = (
            self._find_column(
                dataframe,
                [
                    "Company Name",
                    "Company",
                    "Name",
                ],
            )
        )

        if symbol_column is None:
            raise NSESectorUniverseError(
                (
                    f"{source.index_name}: "
                    "Symbol column missing."
                )
            )

        rows: list[
            dict[str, str]
        ] = []

        for _, row in (
            dataframe.iterrows()
        ):

            symbol = normalize_symbol(
                row.get(
                    symbol_column
                )
            )

            if not symbol:
                continue

            company_name = (
                clean_text(
                    row.get(
                        company_column
                    )
                )
                if company_column
                else symbol
            )

            if not company_name:
                company_name = symbol

            rows.append(
                {
                    "symbol": symbol,
                    "company_name": (
                        company_name
                    ),
                    "sector": (
                        source.sector
                    ),
                    "index_name": (
                        source.index_name
                    ),
                }
            )

        if not rows:
            raise NSESectorUniverseError(
                (
                    f"{source.index_name}: "
                    "no valid stocks parsed."
                )
            )

        return rows

    # =========================================================
    # DOWNLOAD ONE SECTOR
    # =========================================================

    def _download_sector(
        self,
        source: SectorSource,
    ) -> list[dict[str, str]]:

        try:
            response = requests.get(
                source.csv_url,
                headers=self._headers(),
                timeout=(
                    self.REQUEST_TIMEOUT_SECONDS
                ),
            )

            response.raise_for_status()

            return self._parse_csv(
                csv_text=response.text,
                source=source,
            )

        except Exception as exception:

            logger.warning(
                (
                    "Unable to load sector "
                    "%s from %s: %s"
                ),
                source.index_name,
                source.csv_url,
                exception,
            )

            return []

    # =========================================================
    # BUILD COMPLETE SECTOR UNIVERSE
    # =========================================================

    def _download_universe(
        self,
    ) -> tuple[
        list[NSEStock],
        dict[
            str,
            list[NSEStock],
        ],
    ]:

        raw_records: list[
            dict[str, str]
        ] = []

        for source in (
            self.SECTOR_SOURCES
        ):

            sector_records = (
                self._download_sector(
                    source
                )
            )

            raw_records.extend(
                sector_records
            )

        if not raw_records:
            raise NSESectorUniverseError(
                (
                    "No NSE sector constituent "
                    "data could be loaded."
                )
            )

        #
        # A stock can occur in more than one related
        # sector index.
        #
        # For our scanner, keep one stock per
        # normalized sector.
        #

        sector_symbol_seen: set[
            tuple[str, str]
        ] = set()

        clean_records: list[
            dict[str, str]
        ] = []

        for record in raw_records:

            symbol = normalize_symbol(
                record.get(
                    "symbol"
                )
            )

            sector = clean_text(
                record.get(
                    "sector"
                )
            )

            if (
                not symbol
                or not sector
            ):
                continue

            key = (
                sector,
                symbol,
            )

            if key in (
                sector_symbol_seen
            ):
                continue

            sector_symbol_seen.add(
                key
            )

            clean_records.append(
                {
                    "symbol": symbol,
                    "company_name": (
                        clean_text(
                            record.get(
                                "company_name"
                            )
                        )
                        or symbol
                    ),
                    "sector": sector,
                }
            )

        stocks = clean_stock_universe(
            clean_records
        )

        if not stocks:
            raise NSESectorUniverseError(
                (
                    "No valid NSE sector "
                    "stocks were produced."
                )
            )

        sector_map: dict[
            str,
            list[NSEStock],
        ] = {}

        for stock in stocks:

            sector_map.setdefault(
                stock.sector,
                [],
            ).append(
                stock
            )

        for sector in (
            sector_map
        ):
            sector_map[
                sector
            ].sort(
                key=lambda item: (
                    item.symbol
                )
            )

        return (
            stocks,
            sector_map,
        )

    # =========================================================
    # CACHE
    # =========================================================

    def _cache_valid(
        self,
    ) -> bool:

        return (
            bool(
                self._cached_stocks
            )
            and (
                time.time()
                - self._cache_timestamp
            )
            < self.CACHE_SECONDS
        )

    # =========================================================
    # PUBLIC: ALL STOCKS
    # =========================================================

    def get_all_stocks(
        self,
        *,
        force_refresh: bool = False,
    ) -> list[NSEStock]:

        if (
            not force_refresh
            and self._cache_valid()
        ):
            return list(
                self._cached_stocks
            )

        with self._lock:

            if (
                not force_refresh
                and self._cache_valid()
            ):
                return list(
                    self._cached_stocks
                )

            try:
                (
                    stocks,
                    sector_map,
                ) = (
                    self._download_universe()
                )

                self._cached_stocks = (
                    stocks
                )

                self._cached_sector_map = (
                    sector_map
                )

                self._cache_timestamp = (
                    time.time()
                )

                logger.info(
                    (
                        "Loaded %s stocks "
                        "across %s NSE sectors."
                    ),
                    len(stocks),
                    len(
                        sector_map
                    ),
                )

                return list(
                    stocks
                )

            except Exception:

                logger.exception(
                    (
                        "Unable to refresh "
                        "NSE sector universe."
                    )
                )

                if self._cached_stocks:
                    return list(
                        self._cached_stocks
                    )

                raise

    # =========================================================
    # PUBLIC: SECTOR MAP
    # =========================================================

    def get_sector_map(
        self,
        *,
        force_refresh: bool = False,
    ) -> dict[
        str,
        list[NSEStock],
    ]:

        self.get_all_stocks(
            force_refresh=(
                force_refresh
            )
        )

        return {
            sector: list(
                stocks
            )
            for (
                sector,
                stocks
            )
            in self
            ._cached_sector_map
            .items()
        }

    # =========================================================
    # PUBLIC: SECTOR NAMES
    # =========================================================

    def get_sector_names(
        self,
        *,
        force_refresh: bool = False,
    ) -> list[str]:

        sector_map = (
            self.get_sector_map(
                force_refresh=(
                    force_refresh
                )
            )
        )

        return sorted(
            sector_map.keys()
        )

    # =========================================================
    # PUBLIC: STOCKS FOR ONE SECTOR
    # =========================================================

    def get_stocks_for_sector(
        self,
        sector: str,
        *,
        force_refresh: bool = False,
    ) -> list[NSEStock]:

        target = clean_text(
            sector
        )

        if not target:
            return []

        sector_map = (
            self.get_sector_map(
                force_refresh=(
                    force_refresh
                )
            )
        )

        return list(
            sector_map.get(
                target,
                [],
            )
        )

    # =========================================================
    # PUBLIC: FIND STOCK
    # =========================================================

    def find_stock(
        self,
        query: str,
    ) -> NSEStock | None:

        normalized_query = (
            clean_text(
                query
            )
            .casefold()
        )

        if not normalized_query:
            return None

        stocks = (
            self.get_all_stocks()
        )

        for stock in stocks:

            if (
                stock.symbol.casefold()
                == normalized_query
            ):
                return stock

        for stock in stocks:

            if (
                stock.company_name
                .casefold()
                == normalized_query
            ):
                return stock

        for stock in stocks:

            searchable = (
                f"{stock.symbol} "
                f"{stock.company_name} "
                f"{stock.sector}"
            ).casefold()

            if (
                normalized_query
                in searchable
            ):
                return stock

        return None

    # =========================================================
    # PUBLIC: SEARCH
    # =========================================================

    def search_stocks(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[
        dict[str, Any]
    ]:

        normalized_query = (
            clean_text(
                query
            )
            .casefold()
        )

        if not normalized_query:
            return []

        safe_limit = max(
            1,
            min(
                int(limit),
                50,
            ),
        )

        results: list[
            dict[str, Any]
        ] = []

        for stock in (
            self.get_all_stocks()
        ):

            searchable = (
                f"{stock.symbol} "
                f"{stock.company_name} "
                f"{stock.sector}"
            ).casefold()

            if (
                normalized_query
                not in searchable
            ):
                continue

            results.append(
                stock.to_dict()
            )

            if (
                len(results)
                >= safe_limit
            ):
                break

        return results

    # =========================================================
    # HEALTH
    # =========================================================

    def health(
        self,
    ) -> dict[str, Any]:

        try:
            stocks = (
                self.get_all_stocks()
            )

            sectors = (
                self.get_sector_map()
            )

            return {
                "service": (
                    "NSE Sector Universe"
                ),
                "status": (
                    "healthy"
                ),
                "is_healthy": True,
                "stock_count": (
                    len(stocks)
                ),
                "sector_count": (
                    len(sectors)
                ),
                "fixed_nifty500": False,
                "source": (
                    "NSE Indices sector constituents"
                ),
                "checked_at": (
                    utc_now()
                    .isoformat()
                ),
            }

        except Exception as exception:

            return {
                "service": (
                    "NSE Sector Universe"
                ),
                "status": (
                    "unhealthy"
                ),
                "is_healthy": False,
                "error": str(
                    exception
                ),
                "stock_count": 0,
                "sector_count": 0,
                "fixed_nifty500": False,
                "checked_at": (
                    utc_now()
                    .isoformat()
                ),
            }


# =============================================================
# GLOBAL INSTANCE
# =============================================================

_global_nse_sector_universe_service: (
    NSESectorUniverseService
    | None
) = None

_global_lock = (
    threading.Lock()
)


def get_nse_sector_universe_service(
) -> NSESectorUniverseService:

    global _global_nse_sector_universe_service
    

    if (
        _global_nse_sector_universe_service
        is not None
    ):
        return (
            _global_nse_sector_universe_service
        )

    with _global_lock:

        if (
            _global_nse_sector_universe_service
            is None
        ):
            _global_nse_sector_universe_service = (
                NSESectorUniverseService()
            )

    return (
        _global_nse_sector_universe_service
    )
