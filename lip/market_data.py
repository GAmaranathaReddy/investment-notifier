"""
Market Data Module
==================
Batch download and data extraction utilities using yfinance.
"""

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def batch_download(
    symbols: list[str],
    period: str = "12mo",
    interval: str = "1d",
    batch_size: int = 25,
) -> dict[str, pd.DataFrame]:
    """
    Fetch daily price history for symbols in batches.

    Args:
        symbols: List of ticker symbols
        period: History period (e.g., "6mo", "12mo")
        interval: Data interval (must be "1d" for this system)
        batch_size: Number of symbols per batch request

    Returns:
        Dictionary mapping symbol to its DataFrame
    """
    if not symbols:
        return {}

    result = {}

    # Process in batches
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        logger.info(f"Fetching batch {i // batch_size + 1}: {len(batch)} symbols...")

        try:
            df = yf.download(
                tickers=batch,
                period=period,
                interval=interval,
                group_by="ticker",
                progress=False,
                threads=True,
            )

            if df.empty:
                logger.warning(f"No data returned for batch starting at {i}")
                continue

            # Parse the multi-level dataframe
            for symbol in batch:
                try:
                    if len(batch) == 1:
                        symbol_df = df.copy()
                    else:
                        symbol_df = df[symbol].copy()

                    symbol_df = symbol_df.dropna(how="all")

                    if not symbol_df.empty:
                        result[symbol] = symbol_df
                        logger.debug(f"  {symbol}: {len(symbol_df)} days")
                    else:
                        logger.warning(f"  {symbol}: No data available")
                except KeyError:
                    logger.warning(f"  {symbol}: Not found in response")
                except Exception as e:
                    logger.error(f"  {symbol}: Error parsing - {e}")

        except Exception as e:
            logger.error(f"Batch fetch error: {e}")

    logger.info(f"Fetch complete: {len(result)}/{len(symbols)} symbols successful")
    return result


def get_close_series(df: pd.DataFrame) -> pd.Series:
    """Extract close price series from DataFrame."""
    if df is None or df.empty:
        return pd.Series()
    return df["Close"].dropna()


def get_high_series(df: pd.DataFrame) -> pd.Series:
    """Extract high price series from DataFrame."""
    if df is None or df.empty:
        return pd.Series()
    return df["High"].dropna()


def get_latest_price(df: pd.DataFrame) -> Optional[float]:
    """Get the latest closing price."""
    if df is None or df.empty:
        return None
    close = df["Close"].dropna()
    return float(close.iloc[-1]) if len(close) > 0 else None


def get_latest_high(df: pd.DataFrame) -> Optional[float]:
    """Get the latest intraday high."""
    if df is None or df.empty:
        return None
    high = df["High"].dropna()
    return float(high.iloc[-1]) if len(high) > 0 else None


def has_minimum_history(df: pd.DataFrame, min_days: int) -> bool:
    """Check if DataFrame has minimum required history."""
    if df is None or df.empty:
        return False
    return len(df) >= min_days
