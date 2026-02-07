#!/usr/bin/env python3
"""
Long-Term Investor Alert System
================================
A calm, disciplined alert system for long-term investors.
Focuses on capital protection and low-risk entry opportunities.

Usage:
    python investor_alert.py

Environment Variables:
    TELEGRAM_BOT_TOKEN - Your Telegram bot token
    TELEGRAM_CHAT_ID - Your Telegram chat ID
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# CONFIGURATION
# ==============================================================================

STOCKS_FILE = "stocks.json"
PERIOD = "6mo"
INTERVAL = "1d"

# Risk thresholds
DRAWDOWN_THRESHOLD = 0.10  # 10% drawdown triggers exit risk
DMA_SHORT = 50  # Short-term moving average
DMA_LONG = 100  # Long-term moving average

# Entry thresholds
PULLBACK_MIN = 0.05  # Minimum 5% pullback for entry
PULLBACK_MAX = 0.10  # Maximum 10% pullback (beyond this is drawdown risk)
STABILITY_DAYS = 5  # Number of days to check for stability


# ==============================================================================
# DATA FETCHING
# ==============================================================================


def load_symbols(filepath: str = STOCKS_FILE) -> list[str]:
    """Load stock symbols from JSON file."""
    try:
        with open(filepath, "r") as f:
            symbols = json.load(f)
        logger.info(f"Loaded {len(symbols)} symbols from {filepath}")
        return symbols
    except FileNotFoundError:
        logger.error(f"Symbols file not found: {filepath}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filepath}: {e}")
        return []


def fetch_all_price_data(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """
    Fetch daily price history for ALL symbols in ONE batch request.
    This is much more efficient and avoids rate limiting.
    """
    try:
        logger.info(f"Fetching data for {len(symbols)} symbols in one batch request...")

        # Download all symbols at once - single API call!
        df = yf.download(
            tickers=symbols,
            period=PERIOD,
            interval=INTERVAL,
            group_by="ticker",
            progress=False,
            threads=True,
        )

        if df.empty:
            logger.warning("No data returned from batch request")
            return {}

        # Parse the multi-level dataframe into individual symbol dataframes
        result = {}
        for symbol in symbols:
            try:
                if len(symbols) == 1:
                    # Single symbol returns flat dataframe
                    symbol_df = df.copy()
                else:
                    # Multiple symbols returns multi-level columns
                    symbol_df = df[symbol].copy()

                # Drop rows with all NaN values
                symbol_df = symbol_df.dropna(how="all")

                if not symbol_df.empty:
                    result[symbol] = symbol_df
                    logger.info(f"  {symbol}: {len(symbol_df)} days of data")
                else:
                    logger.warning(f"  {symbol}: No data available")
            except KeyError:
                logger.warning(f"  {symbol}: Not found in response")
            except Exception as e:
                logger.error(f"  {symbol}: Error parsing data - {e}")

        logger.info(f"Batch fetch complete: {len(result)}/{len(symbols)} symbols successful")
        return result

    except Exception as e:
        logger.error(f"Error in batch fetch: {e}")
        return {}


# ==============================================================================
# TECHNICAL CALCULATIONS
# ==============================================================================


def calculate_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate 50-DMA and 100-DMA."""
    df = df.copy()
    df["DMA_50"] = df["Close"].rolling(window=DMA_SHORT).mean()
    df["DMA_100"] = df["Close"].rolling(window=DMA_LONG).mean()
    return df


def calculate_dma_slope(df: pd.DataFrame, window: int = 10) -> float:
    """
    Calculate the slope of the 100-DMA over the last N days.
    Returns the average daily change as a percentage.
    """
    dma_100 = df["DMA_100"].dropna()
    if len(dma_100) < window:
        return 0.0

    recent_dma = dma_100.tail(window)
    slope = (recent_dma.iloc[-1] - recent_dma.iloc[0]) / recent_dma.iloc[0]
    return slope


def get_recent_high(df: pd.DataFrame, days: int = 63) -> float:
    """Get the highest close in the last N days (default ~3 months)."""
    recent_data = df.tail(days)
    return recent_data["Close"].max()


def get_multi_timeframe_highs(df: pd.DataFrame) -> dict:
    """Get highest prices for multiple timeframes."""
    return {
        "high_1d": df["High"].iloc[-1] if len(df) >= 1 else 0,  # Today's intraday high
        "high_1w": df["High"].tail(5).max() if len(df) >= 5 else 0,  # 1 week (5 trading days)
        "high_1m": df["High"].tail(21).max() if len(df) >= 21 else 0,  # 1 month (21 trading days)
        "high_3m": df["High"].tail(63).max() if len(df) >= 63 else 0,  # 3 months (63 trading days)
    }


def calculate_drawdown(current_price: float, recent_high: float) -> float:
    """Calculate drawdown from recent high."""
    if recent_high <= 0:
        return 0.0
    return (recent_high - current_price) / recent_high


def check_price_stability(df: pd.DataFrame, days: int = STABILITY_DAYS) -> bool:
    """
    Check if recent closes are stable (no wild swings).
    Returns True if daily changes are within reasonable bounds.
    """
    recent_closes = df["Close"].tail(days)
    if len(recent_closes) < days:
        return False

    # Calculate daily percentage changes
    daily_changes = recent_closes.pct_change().dropna().abs()

    # Stable if no single day moved more than 3%
    max_daily_change = daily_changes.max()
    return max_daily_change < 0.03


# ==============================================================================
# EXIT RISK DETECTION
# ==============================================================================


def check_exit_risk(df: pd.DataFrame, symbol: str) -> Optional[dict]:
    """
    Check for exit risk conditions:
    1. Trend risk: 50-DMA < 100-DMA (death cross territory)
    2. Drawdown risk: price dropped ≥10% from 3-month high

    Returns alert dict if risk detected, None otherwise.
    """
    df = calculate_moving_averages(df)

    # Get latest values
    latest = df.iloc[-1]
    current_price = latest["Close"]
    dma_50 = latest["DMA_50"]
    dma_100 = latest["DMA_100"]

    # Skip if we don't have enough data for moving averages
    if pd.isna(dma_50) or pd.isna(dma_100):
        logger.warning(f"{symbol}: Insufficient data for moving averages")
        return None

    # Calculate common metrics
    recent_high = get_recent_high(df)
    drawdown = calculate_drawdown(current_price, recent_high)
    dma_slope = calculate_dma_slope(df)

    # Base metrics for all alerts
    base_metrics = {
        "symbol": symbol,
        "price": current_price,
        "dma_50": dma_50,
        "dma_100": dma_100,
        "recent_high": recent_high,
        "drawdown_pct": drawdown * 100,
        "dma_slope_pct": dma_slope * 100,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # Check trend risk: 50-DMA below 100-DMA
    if dma_50 < dma_100:
        return {
            **base_metrics,
            "type": "EXIT_RISK",
            "reason": "Trend weakening (50-DMA < 100-DMA)",
        }

    # Check drawdown risk
    if drawdown >= DRAWDOWN_THRESHOLD:
        return {
            **base_metrics,
            "type": "EXIT_RISK",
            "reason": f"Drawdown {drawdown*100:.1f}% from recent high",
        }

    return None


# ==============================================================================
# ENTRY OPPORTUNITY DETECTION
# ==============================================================================


def check_entry_opportunity(df: pd.DataFrame, symbol: str) -> Optional[dict]:
    """
    Check for entry opportunity conditions:
    1. No exit risk active
    2. Price > 100-DMA (healthy trend)
    3. 100-DMA slope flat or rising
    4. Pullback 5-8% from recent high (but not >10%)
    5. Last 3-5 closes are stable

    Returns alert dict if opportunity detected, None otherwise.
    """
    df = calculate_moving_averages(df)

    # Get latest values
    latest = df.iloc[-1]
    current_price = latest["Close"]
    dma_50 = latest["DMA_50"]
    dma_100 = latest["DMA_100"]

    # Skip if we don't have enough data
    if pd.isna(dma_100):
        return None

    # Trend filter: price must be above 100-DMA
    if current_price <= dma_100:
        logger.debug(f"{symbol}: Price below 100-DMA, skipping entry check")
        return None

    # Check 100-DMA slope (should be flat or rising)
    dma_slope = calculate_dma_slope(df)
    if dma_slope < -0.01:  # More than 1% decline over 10 days
        logger.debug(f"{symbol}: 100-DMA declining, skipping entry check")
        return None

    # Check pullback condition
    recent_high = get_recent_high(df, days=42)  # ~2 months for entry timing
    drawdown = calculate_drawdown(current_price, recent_high)

    # Pullback should be between 5% and 10%
    if drawdown < PULLBACK_MIN or drawdown >= PULLBACK_MAX:
        logger.debug(f"{symbol}: Pullback {drawdown*100:.1f}% outside 5-10% range")
        return None

    # Check stability
    if not check_price_stability(df):
        logger.debug(f"{symbol}: Recent prices not stable")
        return None

    # All conditions met!
    return {
        "type": "ENTRY_OPPORTUNITY",
        "symbol": symbol,
        "reason": f"Pullback {drawdown*100:.1f}% in healthy uptrend",
        "price": current_price,
        "dma_50": dma_50,
        "dma_100": dma_100,
        "recent_high": recent_high,
        "drawdown_pct": drawdown * 100,
        "dma_slope_pct": dma_slope * 100,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


# ==============================================================================
# TELEGRAM ALERTS
# ==============================================================================


def send_telegram_summary(all_metrics: list[dict], exit_risks: list[dict], entry_opps: list[dict]) -> bool:
    """
    Send ONE combined summary message via Telegram Bot API in table format.
    Returns True if successful, False otherwise.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not configured. Skipping alert.")
        return False

    # Build the message in table format
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Sort metrics by 3M drop descending (highest drop first)
    sorted_metrics = sorted(all_metrics, key=lambda x: x["drop_3m"], reverse=True)

    lines = [
        f"📈 *INVESTMENT ALERT*",
        f"📅 {date_str}",
        f"📊 {len(entry_opps)} entry | {len(exit_risks)} exit",
        "",
    ]

    # Send each stock as a formatted block for better readability
    for m in sorted_metrics:
        status_icon = {
            "🟢 ENTRY OPP": "🟢",
            "✅ HEALTHY": "✅",
            "👀 WATCH": "👀",
            "⏸️ WAIT": "⏸️",
            "🚨 EXIT RISK": "🚨",
        }.get(m["status"], "?")

        lines.append(f"{status_icon} *{m['symbol']}* - ${m['price']:.2f}")
        lines.append(f"   Drop: 1D={m['drop_1d']:.1f}% | 1W={m['drop_1w']:.1f}% | 1M={m['drop_1m']:.1f}% | 3M={m['drop_3m']:.1f}%")
        lines.append(f"   High: 1D=${m['high_1d']:.0f} | 1W=${m['high_1w']:.0f} | 1M=${m['high_1m']:.0f} | 3M=${m['high_3m']:.0f}")
        lines.append("")

    lines.append("_🟢Entry 🚨Exit ✅Hold ⏸️Wait 👀Watch_")

    message = "\n".join(lines)

    # Send via Telegram API
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram summary sent successfully!")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


# ==============================================================================
# MAIN ANALYSIS
# ==============================================================================


def get_symbol_metrics(df: pd.DataFrame, symbol: str) -> Optional[dict]:
    """
    Get all metrics for a symbol regardless of alert status.
    Returns a dict with all key metrics.
    """
    df = calculate_moving_averages(df)

    latest = df.iloc[-1]
    current_price = latest["Close"]
    dma_50 = latest["DMA_50"]
    dma_100 = latest["DMA_100"]

    if pd.isna(dma_50) or pd.isna(dma_100):
        return None

    dma_slope = calculate_dma_slope(df)

    # Get multi-timeframe highs
    highs = get_multi_timeframe_highs(df)

    # Calculate drawdown from 1-day high (intraday high)
    drawdown = calculate_drawdown(current_price, highs["high_1d"])

    # Determine status
    if dma_50 < dma_100:
        status = "🚨 EXIT RISK"
        status_reason = "50-DMA < 100-DMA"
    elif drawdown >= DRAWDOWN_THRESHOLD:
        status = "🚨 EXIT RISK"
        status_reason = f"Drawdown {drawdown*100:.1f}%"
    elif current_price > dma_100 and PULLBACK_MIN <= drawdown < PULLBACK_MAX and dma_slope >= -0.01:
        status = "🟢 ENTRY OPP"
        status_reason = f"Pullback {drawdown*100:.1f}%"
    elif current_price > dma_100 and dma_50 > dma_100:
        status = "✅ HEALTHY"
        status_reason = "Strong uptrend"
    elif current_price > dma_100:
        status = "👀 WATCH"
        status_reason = "Above 100-DMA"
    else:
        status = "⏸️ WAIT"
        status_reason = "Below 100-DMA"

    # Calculate drop from each timeframe high
    drop_1d = calculate_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = calculate_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = calculate_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = calculate_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "price": current_price,
        "dma_50": dma_50,
        "dma_100": dma_100,
        "recent_high": highs["high_1d"],
        "high_1d": highs["high_1d"],
        "high_1w": highs["high_1w"],
        "high_1m": highs["high_1m"],
        "high_3m": highs["high_3m"],
        "drop_1d": drop_1d,
        "drop_1w": drop_1w,
        "drop_1m": drop_1m,
        "drop_3m": drop_3m,
        "drawdown_pct": drawdown * 100,
        "dma_slope_pct": dma_slope * 100,
        "status": status,
        "status_reason": status_reason,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


def analyze_symbol(symbol: str, df: pd.DataFrame) -> tuple[Optional[dict], Optional[dict]]:
    """
    Analyze a single symbol for exit risk or entry opportunity.
    Returns (alert, metrics) tuple.
    Only one alert per symbol per run to avoid spam.
    """
    if df is None or len(df) < DMA_LONG:
        logger.warning(f"{symbol}: Insufficient data for analysis")
        return None, None

    # Get metrics for all symbols display
    metrics = get_symbol_metrics(df, symbol)

    # Priority 1: Check for exit risk
    exit_alert = check_exit_risk(df, symbol)
    if exit_alert:
        logger.warning(f"{symbol}: EXIT RISK detected - {exit_alert['reason']}")
        return exit_alert, metrics

    # Priority 2: Check for entry opportunity (only if no exit risk)
    entry_alert = check_entry_opportunity(df, symbol)
    if entry_alert:
        logger.info(f"{symbol}: ENTRY OPPORTUNITY detected - {entry_alert['reason']}")
        return entry_alert, metrics

    logger.info(f"{symbol}: No alerts triggered")
    return None, metrics


def main():
    """Main entry point for the investor alert system."""
    logger.info("=" * 60)
    logger.info("Long-Term Investor Alert System")
    logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Load symbols
    symbols = load_symbols()
    if not symbols:
        logger.error("No symbols to analyze. Exiting.")
        return

    # Fetch ALL data in ONE batch request (efficient & rate-limit safe)
    all_data = fetch_all_price_data(symbols)

    if not all_data:
        logger.error("Failed to fetch any data. Exiting.")
        return

    # Analyze each symbol using the pre-fetched data
    alerts = []
    all_metrics = []
    for symbol in symbols:
        try:
            df = all_data.get(symbol)
            if df is None:
                logger.warning(f"{symbol}: No data available, skipping")
                continue
            alert, metrics = analyze_symbol(symbol, df)
            if alert:
                alerts.append(alert)
            if metrics:
                all_metrics.append(metrics)
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            continue

    # Summary
    logger.info("=" * 60)
    logger.info(f"Analysis complete. {len(alerts)} alerts generated.")

    # Send alerts via Telegram
    exit_risks = [a for a in alerts if a["type"] == "EXIT_RISK"]
    entry_opps = [a for a in alerts if a["type"] == "ENTRY_OPPORTUNITY"]

    logger.info(f"Exit Risks: {len(exit_risks)}")
    logger.info(f"Entry Opportunities: {len(entry_opps)}")

    # Print ALL SYMBOLS summary table
    if all_metrics:
        logger.info("")
        logger.info("=" * 160)
        logger.info("📈 ALL SYMBOLS OVERVIEW")
        logger.info("=" * 160)
        logger.info(f"{'Symbol':<8} {'Status':<14} {'Price':>10} {'1D Drop':>9} {'1W Drop':>9} {'1M Drop':>9} {'3M Drop':>9} {'1D High':>10} {'1W High':>10} {'1M High':>10} {'3M High':>10}")
        logger.info("-" * 160)

        # Sort by 3M drop descending (highest drop first)
        sorted_metrics = sorted(all_metrics, key=lambda x: x["drop_3m"], reverse=True)

        for m in sorted_metrics:
            logger.info(
                f"{m['symbol']:<8} {m['status']:<14} "
                f"${m['price']:>9.2f} {m['drop_1d']:>8.1f}% {m['drop_1w']:>8.1f}% {m['drop_1m']:>8.1f}% {m['drop_3m']:>8.1f}% "
                f"${m['high_1d']:>9.2f} ${m['high_1w']:>9.2f} ${m['high_1m']:>9.2f} ${m['high_3m']:>9.2f}"
            )

        logger.info("-" * 160)
        logger.info("")
        logger.info("📖 STATUS GUIDE:")
        logger.info("   🟢 ENTRY OPP  = Good pullback (5-8%) in healthy uptrend → Consider buying")
        logger.info("   ✅ HEALTHY    = Strong uptrend, 50-DMA > 100-DMA → Hold or wait for pullback")
        logger.info("   👀 WATCH      = Above 100-DMA but not ideal → Monitor closely")
        logger.info("   ⏸️ WAIT       = Below 100-DMA → Not ready for entry yet")
        logger.info("   🚨 EXIT RISK  = Trend breaking down → Consider reducing position")
        logger.info("")
        logger.info("📊 COLUMN GUIDE:")
        logger.info("   Price   = Current stock price (close)")
        logger.info("   1D Drop = Drop from today's intraday high")
        logger.info("   1W Drop = Drop from 1-week high")
        logger.info("   1M Drop = Drop from 1-month high")
        logger.info("   3M Drop = Drop from 3-month high")
        logger.info("   1D/1W/1M/3M High = Highest price in that timeframe")
        logger.info("")

    # Send ONE combined Telegram message
    send_telegram_summary(all_metrics, exit_risks, entry_opps)

    logger.info("=" * 60)
    logger.info("Done.")


if __name__ == "__main__":
    main()
