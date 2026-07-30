"""Streamlit dashboard for the scanner MVP.
Displays Live Index (via provider), search box, time-horizon selector, auto-refresh, and results table.
"""
import os
import time

import streamlit as st
import pandas as pd
import plotly.graph_objs as go

from src.scanner import scan_ticker
from src.data.fetcher import fetch_quote

DATA_PROVIDER = os.environ.get('DATA_PROVIDER', 'yfinance')
REFRESH_INTERVAL = int(os.environ.get('REFRESH_INTERVAL', 60))
SCORE_THRESHOLD = int(os.environ.get('SCORE_THRESHOLD', 70))

st.set_page_config(layout='wide', page_title='Eagle Smart Scanner - MVP')

st.title('Eagle Smart Scanner - MVP')

col1, col2 = st.columns([3,1])
with col1:
    st.header('NIFTY Index (Live)')
    # Placeholder for index data - implement real index fetch later
    try:
        idx = fetch_quote('^NSEI', provider=DATA_PROVIDER)
        st.metric('NIFTY (approx)', idx.get('price', 'n/a'), delta=None)
    except Exception as e:
        st.warning('Index fetch error: %s' % e)

with col2:
    st.header('Controls')
    horizon = st.selectbox('Time period', options=['swing','3m','6m','1y','3y'], index=0)
    auto_refresh = st.checkbox('Auto refresh', value=True)
    interval = st.number_input('Refresh seconds', min_value=10, max_value=3600, value=REFRESH_INTERVAL)

st.write('Only showing stocks with score >= %d and signal in [Buy, Strong Buy]' % SCORE_THRESHOLD)

search = st.text_input('Search ticker or name (e.g., RELIANCE.NS)')

if 'results' not in st.session_state:
    st.session_state.results = []

# Simple single-ticker search for MVP
if st.button('Run scan') and search:
    with st.spinner('Scanning %s...' % search):
        res = scan_ticker(search.strip(), provider=DATA_PROVIDER, horizon=horizon)
        st.session_state.results = [res]

if st.session_state.results:
    rows = []
    for r in st.session_state.results:
        if r.get('error'):
            st.error(f"{r.get('ticker')}: {r.get('error')}")
            continue
        rows.append(r)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df)
        # expand first row
        first = rows[0]
        st.subheader(f"Details: {first['ticker']}")
        st.write(first)
        # simple price chart using plotly (placeholder)
        try:
            import yfinance as yf
            data = yf.download(first['ticker'], period='1y', progress=False)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'], name='Close'))
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.info('Chart not available for this ticker in MVP')

# Auto-refresh loop (streamlit reruns on interval using experimental function)
if auto_refresh and search:
    st.write('Auto-refresh is enabled; the page will refresh every %d seconds' % interval)
    st.experimental_rerun()
