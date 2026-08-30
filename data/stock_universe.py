from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

from data.sector_map import ACTIVE_SECTORS, SECTOR_BY_KEY


@dataclass(frozen=True, slots=True)
class StockDefinition:
    symbol: str
    name: str
    sector_key: str
    fyers_symbol: str

    def as_dict(self) -> dict[str, str]:
        sector = SECTOR_BY_KEY[self.sector_key]
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector_key": self.sector_key,
            "sector_name": sector.display_name,
            "fyers_symbol": self.fyers_symbol,
        }


def _stock(symbol: str, name: str, sector_key: str) -> StockDefinition:
    clean = symbol.strip().upper()
    return StockDefinition(
        symbol=clean,
        name=name.strip(),
        sector_key=sector_key,
        fyers_symbol=f"NSE:{clean}-EQ",
    )


# ============================================================
# FROZEN 20 x 10 SEARCH / SCAN UNIVERSE
# ============================================================
# This is the candidate universe only.
# Ranking order is NEVER hard-coded here.
# Sector scanner + technical engine rank these stocks dynamically
# from real FYERS/NSE data for Intraday / BTST / Swing.
# ============================================================

STOCKS_BY_SECTOR: Final[dict[str, tuple[StockDefinition, ...]]] = {
    "bank": (
        _stock("HDFCBANK", "HDFC Bank", "bank"),
        _stock("ICICIBANK", "ICICI Bank", "bank"),
        _stock("SBIN", "State Bank of India", "bank"),
        _stock("AXISBANK", "Axis Bank", "bank"),
        _stock("KOTAKBANK", "Kotak Mahindra Bank", "bank"),
        _stock("INDUSINDBK", "IndusInd Bank", "bank"),
        _stock("BANKBARODA", "Bank of Baroda", "bank"),
        _stock("PNB", "Punjab National Bank", "bank"),
        _stock("CANBK", "Canara Bank", "bank"),
        _stock("FEDERALBNK", "Federal Bank", "bank"),
    ),

    "financial_services": (
        _stock("BAJFINANCE", "Bajaj Finance", "financial_services"),
        _stock("BAJAJFINSV", "Bajaj Finserv", "financial_services"),
        _stock("JIOFIN", "Jio Financial Services", "financial_services"),
        _stock("SBILIFE", "SBI Life Insurance", "financial_services"),
        _stock("HDFCLIFE", "HDFC Life Insurance", "financial_services"),
        _stock("ICICIGI", "ICICI Lombard General Insurance", "financial_services"),
        _stock("ICICIPRULI", "ICICI Prudential Life Insurance", "financial_services"),
        _stock("CHOLAFIN", "Cholamandalam Investment and Finance", "financial_services"),
        _stock("SHRIRAMFIN", "Shriram Finance", "financial_services"),
        _stock("MUTHOOTFIN", "Muthoot Finance", "financial_services"),
    ),

    "information_technology": (
        _stock("TCS", "Tata Consultancy Services", "information_technology"),
        _stock("INFY", "Infosys", "information_technology"),
        _stock("HCLTECH", "HCL Technologies", "information_technology"),
        _stock("WIPRO", "Wipro", "information_technology"),
        _stock("TECHM", "Tech Mahindra", "information_technology"),
        _stock("LTIM", "LTIMindtree", "information_technology"),
        _stock("PERSISTENT", "Persistent Systems", "information_technology"),
        _stock("COFORGE", "Coforge", "information_technology"),
        _stock("MPHASIS", "Mphasis", "information_technology"),
        _stock("OFSS", "Oracle Financial Services Software", "information_technology"),
    ),

    "auto": (
        _stock("MARUTI", "Maruti Suzuki India", "auto"),
        _stock("M&M", "Mahindra & Mahindra", "auto"),
        _stock("TATAMOTORS", "Tata Motors", "auto"),
        _stock("BAJAJ-AUTO", "Bajaj Auto", "auto"),
        _stock("EICHERMOT", "Eicher Motors", "auto"),
        _stock("HEROMOTOCO", "Hero MotoCorp", "auto"),
        _stock("TVSMOTOR", "TVS Motor Company", "auto"),
        _stock("ASHOKLEY", "Ashok Leyland", "auto"),
        _stock("BOSCHLTD", "Bosch", "auto"),
        _stock("MOTHERSON", "Samvardhana Motherson International", "auto"),
    ),

    "fmcg": (
        _stock("HINDUNILVR", "Hindustan Unilever", "fmcg"),
        _stock("ITC", "ITC", "fmcg"),
        _stock("NESTLEIND", "Nestle India", "fmcg"),
        _stock("BRITANNIA", "Britannia Industries", "fmcg"),
        _stock("DABUR", "Dabur India", "fmcg"),
        _stock("MARICO", "Marico", "fmcg"),
        _stock("GODREJCP", "Godrej Consumer Products", "fmcg"),
        _stock("COLPAL", "Colgate-Palmolive India", "fmcg"),
        _stock("TATACONSUM", "Tata Consumer Products", "fmcg"),
        _stock("UNITDSPR", "United Spirits", "fmcg"),
    ),

    "pharma": (
        _stock("SUNPHARMA", "Sun Pharmaceutical Industries", "pharma"),
        _stock("DRREDDY", "Dr. Reddy's Laboratories", "pharma"),
        _stock("CIPLA", "Cipla", "pharma"),
        _stock("DIVISLAB", "Divi's Laboratories", "pharma"),
        _stock("LUPIN", "Lupin", "pharma"),
        _stock("AUROPHARMA", "Aurobindo Pharma", "pharma"),
        _stock("TORNTPHARM", "Torrent Pharmaceuticals", "pharma"),
        _stock("ALKEM", "Alkem Laboratories", "pharma"),
        _stock("ZYDUSLIFE", "Zydus Lifesciences", "pharma"),
        _stock("GLENMARK", "Glenmark Pharmaceuticals", "pharma"),
    ),

    "healthcare": (
        _stock("APOLLOHOSP", "Apollo Hospitals Enterprise", "healthcare"),
        _stock("MAXHEALTH", "Max Healthcare Institute", "healthcare"),
        _stock("FORTIS", "Fortis Healthcare", "healthcare"),
        _stock("LALPATHLAB", "Dr. Lal PathLabs", "healthcare"),
        _stock("METROPOLIS", "Metropolis Healthcare", "healthcare"),
        _stock("MEDANTA", "Global Health", "healthcare"),
        _stock("NH", "Narayana Hrudayalaya", "healthcare"),
        _stock("KIMS", "Krishna Institute of Medical Sciences", "healthcare"),
        _stock("ASTERDM", "Aster DM Healthcare", "healthcare"),
        _stock("RAINBOW", "Rainbow Children's Medicare", "healthcare"),
    ),

    "metal": (
        _stock("TATASTEEL", "Tata Steel", "metal"),
        _stock("HINDALCO", "Hindalco Industries", "metal"),
        _stock("JSWSTEEL", "JSW Steel", "metal"),
        _stock("VEDL", "Vedanta", "metal"),
        _stock("NMDC", "NMDC", "metal"),
        _stock("SAIL", "Steel Authority of India", "metal"),
        _stock("NATIONALUM", "National Aluminium Company", "metal"),
        _stock("HINDZINC", "Hindustan Zinc", "metal"),
        _stock("JINDALSTEL", "Jindal Steel & Power", "metal"),
        _stock("APLAPOLLO", "APL Apollo Tubes", "metal"),
    ),

    "realty": (
        _stock("DLF", "DLF", "realty"),
        _stock("GODREJPROP", "Godrej Properties", "realty"),
        _stock("OBEROIRLTY", "Oberoi Realty", "realty"),
        _stock("PRESTIGE", "Prestige Estates Projects", "realty"),
        _stock("PHOENIXLTD", "The Phoenix Mills", "realty"),
        _stock("BRIGADE", "Brigade Enterprises", "realty"),
        _stock("SOBHA", "Sobha", "realty"),
        _stock("LODHA", "Macrotech Developers", "realty"),
        _stock("SUNTECK", "Sunteck Realty", "realty"),
        _stock("ANANTRAJ", "Anant Raj", "realty"),
    ),

    "media": (
        _stock("ZEEL", "Zee Entertainment Enterprises", "media"),
        _stock("SUNTV", "Sun TV Network", "media"),
        _stock("PVRINOX", "PVR INOX", "media"),
        _stock("SAREGAMA", "Saregama India", "media"),
        _stock("TIPSINDLTD", "Tips Music", "media"),
        _stock("NAZARA", "Nazara Technologies", "media"),
        _stock("NETWORK18", "Network18 Media & Investments", "media"),
        _stock("TV18BRDCST", "TV18 Broadcast", "media"),
        _stock("DBCORP", "D.B. Corp", "media"),
        _stock("JAGRAN", "Jagran Prakashan", "media"),
    ),

    "psu_bank": (
        _stock("UNIONBANK", "Union Bank of India", "psu_bank"),
        _stock("INDIANB", "Indian Bank", "psu_bank"),
        _stock("BANKINDIA", "Bank of India", "psu_bank"),
        _stock("UCOBANK", "UCO Bank", "psu_bank"),
        _stock("CENTRALBK", "Central Bank of India", "psu_bank"),
        _stock("MAHABANK", "Bank of Maharashtra", "psu_bank"),
        _stock("PSB", "Punjab & Sind Bank", "psu_bank"),
        _stock("IOB", "Indian Overseas Bank", "psu_bank"),
        _stock("IDBI", "IDBI Bank", "psu_bank"),
        _stock("IREDA", "Indian Renewable Energy Development Agency", "psu_bank"),
    ),

    "private_bank": (
        _stock("IDFCFIRSTB", "IDFC First Bank", "private_bank"),
        _stock("BANDHANBNK", "Bandhan Bank", "private_bank"),
        _stock("YESBANK", "Yes Bank", "private_bank"),
        _stock("RBLBANK", "RBL Bank", "private_bank"),
        _stock("KARURVYSYA", "Karur Vysya Bank", "private_bank"),
        _stock("CUB", "City Union Bank", "private_bank"),
        _stock("DCBBANK", "DCB Bank", "private_bank"),
        _stock("J&KBANK", "Jammu & Kashmir Bank", "private_bank"),
        _stock("SOUTHBANK", "South Indian Bank", "private_bank"),
        _stock("CSBBANK", "CSB Bank", "private_bank"),
    ),

    "energy": (
        _stock("NTPC", "NTPC", "energy"),
        _stock("POWERGRID", "Power Grid Corporation of India", "energy"),
        _stock("TATAPOWER", "Tata Power Company", "energy"),
        _stock("ADANIGREEN", "Adani Green Energy", "energy"),
        _stock("ADANIPOWER", "Adani Power", "energy"),
        _stock("NHPC", "NHPC", "energy"),
        _stock("SJVN", "SJVN", "energy"),
        _stock("JSWENERGY", "JSW Energy", "energy"),
        _stock("TORNTPOWER", "Torrent Power", "energy"),
        _stock("CESC", "CESC", "energy"),
    ),

    "oil_gas": (
        _stock("RELIANCE", "Reliance Industries", "oil_gas"),
        _stock("ONGC", "Oil and Natural Gas Corporation", "oil_gas"),
        _stock("IOC", "Indian Oil Corporation", "oil_gas"),
        _stock("BPCL", "Bharat Petroleum Corporation", "oil_gas"),
        _stock("HINDPETRO", "Hindustan Petroleum Corporation", "oil_gas"),
        _stock("GAIL", "GAIL India", "oil_gas"),
        _stock("OIL", "Oil India", "oil_gas"),
        _stock("PETRONET", "Petronet LNG", "oil_gas"),
        _stock("IGL", "Indraprastha Gas", "oil_gas"),
        _stock("MGL", "Mahanagar Gas", "oil_gas"),
    ),

    "consumer_durables": (
        _stock("TITAN", "Titan Company", "consumer_durables"),
        _stock("HAVELLS", "Havells India", "consumer_durables"),
        _stock("DIXON", "Dixon Technologies", "consumer_durables"),
        _stock("VOLTAS", "Voltas", "consumer_durables"),
        _stock("BLUESTARCO", "Blue Star", "consumer_durables"),
        _stock("CROMPTON", "Crompton Greaves Consumer Electricals", "consumer_durables"),
        _stock("WHIRLPOOL", "Whirlpool of India", "consumer_durables"),
        _stock("KAJARIACER", "Kajaria Ceramics", "consumer_durables"),
        _stock("BATAINDIA", "Bata India", "consumer_durables"),
        _stock("RAJESHEXPO", "Rajesh Exports", "consumer_durables"),
    ),

    "commodities": (
        _stock("ULTRACEMCO", "UltraTech Cement", "commodities"),
        _stock("GRASIM", "Grasim Industries", "commodities"),
        _stock("AMBUJACEM", "Ambuja Cements", "commodities"),
        _stock("ACC", "ACC", "commodities"),
        _stock("SHREECEM", "Shree Cement", "commodities"),
        _stock("RAMCOCEM", "The Ramco Cements", "commodities"),
        _stock("DALBHARAT", "Dalmia Bharat", "commodities"),
        _stock("JKCEMENT", "JK Cement", "commodities"),
        _stock("DEEPAKNTR", "Deepak Nitrite", "commodities"),
        _stock("COROMANDEL", "Coromandel International", "commodities"),
    ),

    "consumption": (
        _stock("TRENT", "Trent", "consumption"),
        _stock("DMART", "Avenue Supermarts", "consumption"),
        _stock("NYKAA", "FSN E-Commerce Ventures", "consumption"),
        _stock("INDHOTEL", "Indian Hotels Company", "consumption"),
        _stock("JUBLFOOD", "Jubilant FoodWorks", "consumption"),
        _stock("DEVYANI", "Devyani International", "consumption"),
        _stock("ABFRL", "Aditya Birla Fashion and Retail", "consumption"),
        _stock("PAGEIND", "Page Industries", "consumption"),
        _stock("VBL", "Varun Beverages", "consumption"),
        _stock("UBL", "United Breweries", "consumption"),
    ),

    "infrastructure": (
        _stock("LT", "Larsen & Toubro", "infrastructure"),
        _stock("ADANIPORTS", "Adani Ports and Special Economic Zone", "infrastructure"),
        _stock("IRB", "IRB Infrastructure Developers", "infrastructure"),
        _stock("NBCC", "NBCC India", "infrastructure"),
        _stock("NCC", "NCC", "infrastructure"),
        _stock("RVNL", "Rail Vikas Nigam", "infrastructure"),
        _stock("IRCON", "Ircon International", "infrastructure"),
        _stock("KEC", "KEC International", "infrastructure"),
        _stock("KNRCON", "KNR Constructions", "infrastructure"),
        _stock("GRINFRA", "G R Infraprojects", "infrastructure"),
    ),

    "chemicals": (
        _stock("PIDILITIND", "Pidilite Industries", "chemicals"),
        _stock("SRF", "SRF", "chemicals"),
        _stock("FLUOROCHEM", "Gujarat Fluorochemicals", "chemicals"),
        _stock("ATUL", "Atul", "chemicals"),
        _stock("AARTIIND", "Aarti Industries", "chemicals"),
        _stock("NAVINFLUOR", "Navin Fluorine International", "chemicals"),
        _stock("TATACHEM", "Tata Chemicals", "chemicals"),
        _stock("GNFC", "Gujarat Narmada Valley Fertilizers & Chemicals", "chemicals"),
        _stock("GSFC", "Gujarat State Fertilizers & Chemicals", "chemicals"),
        _stock("ALKYLAMINE", "Alkyl Amines Chemicals", "chemicals"),
    ),

    "capital_markets": (
        _stock("BSE", "BSE", "capital_markets"),
        _stock("CDSL", "Central Depository Services India", "capital_markets"),
        _stock("MCX", "Multi Commodity Exchange of India", "capital_markets"),
        _stock("CAMS", "Computer Age Management Services", "capital_markets"),
        _stock("KFINTECH", "KFin Technologies", "capital_markets"),
        _stock("ANGELONE", "Angel One", "capital_markets"),
        _stock("NUVAMA", "Nuvama Wealth Management", "capital_markets"),
        _stock("IIFL", "IIFL Finance", "capital_markets"),
        _stock("MOTILALOFS", "Motilal Oswal Financial Services", "capital_markets"),
        _stock("360ONE", "360 ONE WAM", "capital_markets"),
    ),
}


ALL_STOCKS: Final[tuple[StockDefinition, ...]] = tuple(
    stock
    for sector in ACTIVE_SECTORS
    for stock in STOCKS_BY_SECTOR[sector.key]
)

STOCK_BY_SYMBOL: Final[dict[str, StockDefinition]] = {
    stock.symbol: stock for stock in ALL_STOCKS
}

STOCK_BY_FYERS_SYMBOL: Final[dict[str, StockDefinition]] = {
    stock.fyers_symbol: stock for stock in ALL_STOCKS
}


def normalize_stock_symbol(value: str | None) -> str:
    text = str(value or "").strip().upper()

    if text.startswith("NSE:"):
        text = text[4:]

    if text.endswith("-EQ"):
        text = text[:-3]

    return text


def get_stock(symbol: str) -> StockDefinition:
    normalized = normalize_stock_symbol(symbol)
    try:
        return STOCK_BY_SYMBOL[normalized]
    except KeyError as exc:
        raise KeyError(
            f"Stock {symbol!r} is not in the Eagle 200-stock universe."
        ) from exc


def sector_stocks(sector_key: str) -> tuple[StockDefinition, ...]:
    key = str(sector_key or "").strip().lower()
    try:
        return STOCKS_BY_SECTOR[key]
    except KeyError as exc:
        raise KeyError(f"Unknown sector key: {sector_key}") from exc


def all_symbols() -> list[str]:
    return [stock.symbol for stock in ALL_STOCKS]


def all_fyers_symbols() -> list[str]:
    return [stock.fyers_symbol for stock in ALL_STOCKS]


def search_stocks(query: str, limit: int = 20) -> list[dict[str, str]]:
    """
    Search only inside the frozen Eagle 200-stock universe.
    Prefix matches are ranked ahead of contains matches.
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return []

    limit = max(1, min(int(limit or 20), 50))

    prefix: list[StockDefinition] = []
    contains: list[StockDefinition] = []

    for stock in ALL_STOCKS:
        symbol = stock.symbol.lower()
        name = stock.name.lower()
        sector_name = SECTOR_BY_KEY[stock.sector_key].display_name.lower()

        if (
            symbol.startswith(needle)
            or name.startswith(needle)
        ):
            prefix.append(stock)
        elif (
            needle in symbol
            or needle in name
            or needle in sector_name
        ):
            contains.append(stock)

    ordered = prefix + contains
    return [stock.as_dict() for stock in ordered[:limit]]


def serialize_stocks(
    stocks: Iterable[StockDefinition],
) -> list[dict[str, str]]:
    return [stock.as_dict() for stock in stocks]


def public_universe() -> dict[str, object]:
    return {
        "sector_count": len(STOCKS_BY_SECTOR),
        "stocks_per_sector": 10,
        "stock_count": len(ALL_STOCKS),
        "sectors": {
            sector.key: {
                "sector_name": sector.display_name,
                "stocks": serialize_stocks(STOCKS_BY_SECTOR[sector.key]),
            }
            for sector in ACTIVE_SECTORS
        },
    }


# ============================================================
# FAIL-FAST INTEGRITY CHECKS
# ============================================================

_expected_sector_keys = {sector.key for sector in ACTIVE_SECTORS}
_actual_sector_keys = set(STOCKS_BY_SECTOR)

if _actual_sector_keys != _expected_sector_keys:
    missing = sorted(_expected_sector_keys - _actual_sector_keys)
    extra = sorted(_actual_sector_keys - _expected_sector_keys)
    raise RuntimeError(
        f"Stock universe sector mismatch. Missing={missing}, extra={extra}"
    )

for _sector in ACTIVE_SECTORS:
    _members = STOCKS_BY_SECTOR[_sector.key]

    if len(_members) != 10:
        raise RuntimeError(
            f"{_sector.key} must contain exactly 10 stocks; "
            f"found {len(_members)}."
        )

    for _member in _members:
        if _member.sector_key != _sector.key:
            raise RuntimeError(
                f"{_member.symbol} has wrong sector_key "
                f"{_member.sector_key}; expected {_sector.key}."
            )

        if not _member.fyers_symbol.startswith("NSE:"):
            raise RuntimeError(
                f"Invalid FYERS NSE symbol: {_member.fyers_symbol}"
            )

        if not _member.fyers_symbol.endswith("-EQ"):
            raise RuntimeError(
                f"Equity symbol must end in -EQ: {_member.fyers_symbol}"
            )

if len(ALL_STOCKS) != 200:
    raise RuntimeError(
        f"Eagle universe must contain exactly 200 entries; "
        f"found {len(ALL_STOCKS)}."
    )

_all_symbols = [stock.symbol for stock in ALL_STOCKS]
if len(_all_symbols) != len(set(_all_symbols)):
    duplicates = sorted(
        symbol
        for symbol in set(_all_symbols)
        if _all_symbols.count(symbol) > 1
    )
    raise RuntimeError(
        f"Duplicate stock symbols found in 200-stock universe: {duplicates}"
    )

_all_fyers_symbols = [stock.fyers_symbol for stock in ALL_STOCKS]
if len(_all_fyers_symbols) != len(set(_all_fyers_symbols)):
    raise RuntimeError("Duplicate FYERS stock symbols found.")
