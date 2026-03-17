#!/usr/bin/env python3
"""Fetch 6-month daily OHLCV data for all tracked tickers and save as JSON."""

import json
import os
from datetime import datetime

import yfinance as yf

# All tickers tracked by Shock Signal
TICKERS = [
    'XOM', 'CVX', 'DVN', 'NOG', 'HAL',
    'UAL', 'DAL', 'AAL', 'CCL', 'RCL',
    'NOC', 'RTX', 'LMT', 'LHX', 'KTOS',
    'NVDA', 'TSM', 'ASML', 'AVGO', 'ANET',
    'VRT', 'MU', 'CTSH', 'INFY',
    'IWM', 'FLR', 'AIT', 'ATI',
    'AAPL', 'WMT', 'NKE', 'TGT',
    'GLD', 'NEM', 'GOLD', 'TLT',
    'ARKK', 'MSTR',
    'NTR', 'MOS', 'CF', 'ADM', 'BG', 'DE',
    'KO', 'MDLZ', 'KHC', 'SBUX',
    'CCJ', 'URA', 'LEU', 'SMR', 'CEG', 'OKLO',
    'FSLR',
    'GS', 'JPM', 'ARES',
    'BX', 'BLK', 'OWL', 'MS',
    'MP', 'LAC', 'UUUU',
    'F', 'GM', 'GEV',
    'INVH', 'EQR', 'HD', 'LOW', 'RKT',
    'Z', 'RDFN', 'DHI', 'LEN'
]


def fetch_ticker_data(ticker: str) -> dict | None:
    """Fetch 6-month daily data for a single ticker."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="6mo", interval="1d")

        if df.empty or len(df) < 30:
            print(f"  {ticker}: insufficient data ({len(df)} bars)")
            return None

        data = {
            "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "opens": [round(v, 4) for v in df["Open"].tolist()],
            "highs": [round(v, 4) for v in df["High"].tolist()],
            "lows": [round(v, 4) for v in df["Low"].tolist()],
            "closes": [round(v, 4) for v in df["Close"].tolist()],
            "volumes": [int(v) for v in df["Volume"].tolist()],
        }
        print(f"  {ticker}: {len(df)} bars fetched")
        return data
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")
        return None


def main():
    print(f"Fetching stock data at {datetime.utcnow().isoformat()}Z")
    print(f"Tickers: {len(TICKERS)}")

    all_data = {}
    for ticker in TICKERS:
        result = fetch_ticker_data(ticker)
        if result:
            all_data[ticker] = result

    output = {
        "updated": datetime.utcnow().isoformat() + "Z",
        "ticker_count": len(all_data),
        "tickers": all_data,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/stocks.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"\nDone! {len(all_data)}/{len(TICKERS)} tickers saved to data/stocks.json")
    size_mb = os.path.getsize("data/stocks.json") / (1024 * 1024)
    print(f"File size: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
