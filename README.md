# Eagle Smart Scanner

Eagle Smart Scanner एक professional, responsive और multi-timeframe Nifty 500 research dashboard है।

यह dashboard verified live market data, technical filters, fundamental filters, sector strength और chart-pattern confirmation को combine करके केवल:

- BUY
- STRONG BUY

signals दिखाने के लिए बनाया गया है।

यह project OnePlus Pad Go, tablets, laptops और mobile devices के लिए responsive है।

---

## Main Features

- Nifty 500 stock universe
- FYERS login integration
- Live market indices
- Live stock prices
- Historical OHLCV candles
- Background stock scanning
- बिना page reload auto-refresh
- Stock search bar
- Complete stock-detail research
- Timeframe-based filters
- Verified BUY and STRONG BUY signals
- Entry price
- Stop-loss
- Target price
- Move-Up Probability
- Holding period
- Risk:Reward
- Sector-strength confirmation
- Top 10 technical filters
- Top 10 fundamental filters
- Top 10 chart patterns
- Missing और stale data rejection
- OnePlus Pad Go optimization
- Render deployment support

---

# Supported Timeframes

Eagle Smart Scanner निम्न holding periods support करता है:

| Timeframe | Use |
|---|---|
| 15–30 Days | Swing trading |
| 3 Months | Quarterly trading |
| 6 Months | Medium-term trading |
| 1 Year | Investment |
| 3 Years | Long-term investment |

हर timeframe के लिए technical, fundamental, pattern और sector filters का weight अलग रहता है।

---

# Main Dashboard Columns

Dashboard table में केवल ये columns दिखते हैं:

1. Stock Name
2. Sector
3. Current Price
4. Entry Price
5. Stop Loss
6. Target Price
7. Move-Up Probability
8. Holding Period
9. Signal
10. View Detail

`Rank` और `Symbol` columns main dashboard पर नहीं दिखाए जाते।

---

# Top 10 Technical Filters

Scanner निम्न technical filters का उपयोग करता है:

1. EMA 20
2. EMA 50
3. EMA 200
4. RSI
5. MACD
6. Supertrend
7. ADX
8. Volume Breakout
9. Support and Resistance Breakout
10. Relative Strength vs Nifty

---

# Top 10 Fundamental Filters

Scanner निम्न fundamental filters का उपयोग करता है:

1. Sales Growth
2. Profit Growth
3. EPS Growth
4. ROE
5. ROCE
6. Debt-to-Equity
7. Operating Cash Flow
8. Promoter Holding
9. Promoter Pledge
10. Valuation

Missing fundamental values को fake zero value में convert नहीं किया जाता।

---

# Top 10 Chart Patterns

Scanner निम्न commonly used bullish patterns को detect करता है:

1. Cup and Handle
2. Ascending Triangle
3. Symmetrical Triangle
4. Flag and Pole
5. Double Bottom
6. Inverse Head and Shoulders
7. Falling Wedge
8. Rectangle Breakout
9. Rounded Bottom
10. Consolidation Breakout

Pattern को confirmed तभी माना जाता है जब breakout और volume confirmation उपलब्ध हो।

---

# Live Indices

Dashboard निम्न main indices दिखाता है:

- NIFTY 50
- BANK NIFTY
- SENSEX
- FINNIFTY
- NIFTY NEXT 50
- NIFTY MIDCAP
- INDIA VIX

Index data FYERS API से लिया जाता है।

---

# Project Structure

```text
eagle-smart-scanner/
│
├── app.py
├── config.py
├── requirements.txt
├── Procfile
├── .python-version
├── .gitignore
├── README.md
│
├── data/
│   ├── __init__.py
│   ├── nifty500.py
│   └── sector_map.py
│
├── services/
│   ├── __init__.py
│   ├── cache_service.py
│   ├── fyers_service.py
│   ├── market_data_service.py
│   ├── index_service.py
│   └── fundamental_service.py
│
├── scanners/
│   ├── __init__.py
│   ├── technical_scanner.py
│   ├── fundamental_scanner.py
│   ├── pattern_scanner.py
│   ├── sector_scanner.py
│   ├── probability_engine.py
│   └── research_engine.py
│
├── utils/
│   ├── __init__.py
│   ├── helpers.py
│   ├── validators.py
│   └── logger.py
│
├── templates/
│   ├── login.html
│   ├── dashboard.html
│   ├── stock_detail.html
│   ├── error.html
│   └── privacy.html
│
└── static/
    ├── css/
    │   └── style.css
    │
    └── js/
        ├── dashboard.js
        ├── stock_search.js
        └── auto_refresh.js
