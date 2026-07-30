# Eagle Smart Scanner - MVP

This branch contains a starter Streamlit MVP for the Eagle Smart Scanner. It supports:

- Data provider adapters (Fyers placeholder + yfinance fallback)
- Basic technical indicators (SMA, RSI, MACD, ATR)
- A simple scoring engine and scanner that returns Buy/Strong Buy signals
- A Streamlit dashboard (single-ticker scan) to demo the flow

IMPORTANT: Do NOT commit API keys. Use the config/.env.template as a guide and set your FYERS_ACCESS_TOKEN locally or as GitHub secrets.

To run locally:

1. Create and activate a python virtualenv

   python -m venv .venv
   source .venv/bin/activate   # on Windows use .venv\Scripts\activate

2. Install requirements

   pip install -r requirements.txt

3. Copy config/.env.template to a .env file and fill FYERS_ACCESS_TOKEN (or set DATA_PROVIDER=yfinance)

4. Run Streamlit app

   streamlit run app/dashboard.py

Notes:
- Fyers integration in src/data/fetcher.py is a minimal REST-based adapter. For production/live streaming, integrate Fyers websocket SDK and REST auth flow.
- This MVP focuses on the architecture and a working local demo. We'll extend universe scanning, sector mapping, and probability/backtest notebooks next.
