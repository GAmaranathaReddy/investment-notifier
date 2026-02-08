#!/usr/bin/env python3
"""
Long-Term Investor Alert System (Config-Driven)
================================================
A calm, disciplined alert system for long-term investors.
Focuses on capital protection and low-risk entry opportunities.

Supports multiple categories from config.json:
- Core Trend: Broad market + major trend leaders
- Emerging Rotation: Rotation-aware baskets (commodities, AI, etc.)
- Stress Opportunities: High-quality banks to buy during panic
- Defensive Protection: Capital protection instruments
- Finance Confirmation: Macro health signals

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
from pathlib import Path
from typing import Optional

import pandas as pd

from lib.config import (
    load_config,
    get_batch_size,
    get_history_period,
    get_state_dir,
    get_monitor_symbols_file,
    get_dedupe_window,
    is_telegram_enabled,
    get_category_symbols,
    get_exit_thresholds,
    get_entry_thresholds,
    get_stress_opportunity_thresholds,
    get_finance_confirmation_thresholds,
    get_global_filters,
)
from lib.market_data import batch_download, get_close_series, get_high_series, has_minimum_history
from lib.signals import (
    get_ma_value,
    compute_ma_slope,
    compute_drawdown,
    get_period_high,
    get_multi_timeframe_highs,
    check_stability,
    is_above_ma,
    is_ma_crossover_bearish,
    is_ma_slope_rising,
    is_overheated,
    days_below_ma,
    compute_relative_strength,
)
from lib.alerts import (
    send_telegram,
    should_send_alert,
    record_alert_sent,
    cleanup_old_alerts,
    format_weekly_summary,
    ensure_state_dir,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# SYMBOL LOADING
# ==============================================================================


def load_monitor_symbols(filepath: str) -> list[str]:
    """Load stock symbols from JSON file (existing stocks.json format)."""
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


def collect_all_symbols(config: dict, monitor_symbols: list[str]) -> list[str]:
    """Collect all unique symbols needed for analysis."""
    all_symbols = set(monitor_symbols)

    # Add category symbols
    for category in ["core_trend", "stress_opportunities", "defensive_protection", "finance_confirmation"]:
        all_symbols.update(get_category_symbols(config, category))

    # Add stress watch symbols
    stress_thresholds = get_stress_opportunity_thresholds(config)
    all_symbols.update(stress_thresholds.get("stress_watch_symbols", []))

    # Add finance confirmation compare symbol
    finance_thresholds = get_finance_confirmation_thresholds(config)
    all_symbols.add(finance_thresholds.get("compare_to", "SPY"))

    return list(all_symbols)


# ==============================================================================
# EXIT RISK DETECTION
# ==============================================================================


def check_exit_risk(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    thresholds: dict,
) -> Optional[dict]:
    """
    Check for exit risk conditions based on config thresholds.

    Returns alert dict if risk detected, None otherwise.
    """
    if not thresholds.get("enabled", True):
        return None

    current_price = float(close_series.iloc[-1])
    short_ma = get_ma_value(close_series, thresholds["short_ma"])
    long_ma = get_ma_value(close_series, thresholds["long_ma"])

    if short_ma is None or long_ma is None:
        return None

    # Check MA crossover (50-DMA < 100-DMA)
    if thresholds.get("use_ma_crossover", True) and is_ma_crossover_bearish(short_ma, long_ma):
        return {
            "symbol": symbol,
            "type": "EXIT_RISK",
            "reason": f"Trend weakening ({thresholds['short_ma']}-DMA < {thresholds['long_ma']}-DMA)",
            "price": current_price,
            "dma_50": short_ma,
            "dma_100": long_ma,
        }

    # Check drawdown
    lookback = thresholds.get("drawdown_lookback_days", 63)
    threshold = thresholds.get("drawdown_exit_threshold", 0.10)
    recent_high = get_period_high(high_series, lookback)
    drawdown = compute_drawdown(current_price, recent_high)

    if drawdown >= threshold:
        return {
            "symbol": symbol,
            "type": "EXIT_RISK",
            "reason": f"Drawdown {drawdown*100:.1f}% from {lookback}-day high",
            "price": current_price,
            "dma_50": short_ma,
            "dma_100": long_ma,
            "drawdown_pct": drawdown * 100,
        }

    # Check days below long MA
    below_days = thresholds.get("price_below_long_ma_days", 3)
    if below_days > 0:
        below_count = days_below_ma(close_series, thresholds["long_ma"], below_days)
        if below_count >= below_days:
            return {
                "symbol": symbol,
                "type": "EXIT_RISK",
                "reason": f"Price below {thresholds['long_ma']}-DMA for {below_count} days",
                "price": current_price,
                "dma_50": short_ma,
                "dma_100": long_ma,
            }

    return None


# ==============================================================================
# ENTRY OPPORTUNITY DETECTION
# ==============================================================================


def check_entry_opportunity(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    thresholds: dict,
) -> Optional[dict]:
    """
    Check for entry opportunity conditions based on config thresholds.

    Returns alert dict if opportunity detected, None otherwise.
    """
    if not thresholds.get("enabled", True):
        return None

    current_price = float(close_series.iloc[-1])
    long_ma = get_ma_value(close_series, thresholds["long_ma"])
    short_ma = get_ma_value(close_series, thresholds.get("short_ma", 50))

    if long_ma is None:
        return None

    # Trend filter: price must be above long MA
    if thresholds.get("price_above_long_ma", True) and not is_above_ma(current_price, long_ma):
        return None

    # Check MA slope
    slope_days = thresholds.get("long_ma_slope_days", 10)
    slope = compute_ma_slope(close_series, thresholds["long_ma"], slope_days)
    if not is_ma_slope_rising(slope):
        return None

    # Check pullback
    lookback = thresholds.get("lookback_high_days", 42)
    min_pullback = thresholds.get("min_pullback", 0.05)
    max_pullback = thresholds.get("max_pullback", 0.08)

    recent_high = get_period_high(high_series, lookback)
    pullback = compute_drawdown(current_price, recent_high)

    if pullback < min_pullback or pullback >= max_pullback:
        return None

    # Check overheat
    if thresholds.get("overheat_enabled", True) and short_ma:
        overheat_mult = thresholds.get("overheat_multiple", 1.12)
        if is_overheated(current_price, short_ma, overheat_mult):
            return None

    # Check stability
    stability_days = thresholds.get("stability_days", 5)
    max_drop = thresholds.get("max_single_day_drop", 0.07)
    if not check_stability(close_series, stability_days, max_drop):
        return None

    return {
        "symbol": symbol,
        "type": "ENTRY_OPPORTUNITY",
        "reason": f"Pullback {pullback*100:.1f}% in healthy uptrend",
        "price": current_price,
        "dma_50": short_ma,
        "dma_100": long_ma,
        "drawdown_pct": pullback * 100,
    }


# ==============================================================================
# STRESS OPPORTUNITIES (BANKS)
# ==============================================================================


def check_market_stress(
    all_data: dict[str, pd.DataFrame],
    thresholds: dict,
) -> bool:
    """Check if market stress conditions are met."""
    watch_symbols = thresholds.get("stress_watch_symbols", ["SPY", "VIXY", "KRE"])

    stress_signals = 0

    # Check SPY drawdown
    if "SPY" in all_data:
        spy_close = get_close_series(all_data["SPY"])
        spy_high = get_high_series(all_data["SPY"])
        if len(spy_close) > 0:
            spy_recent_high = get_period_high(spy_high, 63)
            spy_drawdown = compute_drawdown(float(spy_close.iloc[-1]), spy_recent_high)
            if spy_drawdown >= thresholds.get("stress_spy_drawdown_threshold", 0.08):
                stress_signals += 1
                logger.info(f"Stress signal: SPY drawdown {spy_drawdown*100:.1f}%")

    # Check VIXY trending up (simple: above 10-day MA)
    if thresholds.get("stress_vixy_trending_up", True) and "VIXY" in all_data:
        vixy_close = get_close_series(all_data["VIXY"])
        if len(vixy_close) >= 10:
            vixy_ma = get_ma_value(vixy_close, 10)
            if vixy_ma and float(vixy_close.iloc[-1]) > vixy_ma:
                stress_signals += 1
                logger.info("Stress signal: VIXY trending up")

    # Check KRE below long MA
    if thresholds.get("stress_kre_below_long_ma", True) and "KRE" in all_data:
        kre_close = get_close_series(all_data["KRE"])
        if len(kre_close) >= 100:
            kre_ma = get_ma_value(kre_close, 100)
            if kre_ma and float(kre_close.iloc[-1]) < kre_ma:
                stress_signals += 1
                logger.info("Stress signal: KRE below 100-DMA")

    # Need at least 2 stress signals
    is_stressed = stress_signals >= 2
    if is_stressed:
        logger.warning(f"MARKET STRESS CONFIRMED: {stress_signals} signals")

    return is_stressed


def check_bank_opportunity(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    thresholds: dict,
    market_stressed: bool,
) -> Optional[dict]:
    """
    Check for bank opportunity during market stress.
    Only emits BANK OPPORTUNITY WATCH, no exit alerts.
    """
    if not thresholds.get("enabled", True):
        return None

    # Requires market stress confirmation
    if thresholds.get("requires_stress_confirmation", True) and not market_stressed:
        return None

    current_price = float(close_series.iloc[-1])

    # Check drawdown range (15-35%)
    lookback = thresholds.get("dip_lookback_days", 126)
    min_drawdown = thresholds.get("min_drawdown", 0.15)
    max_drawdown = thresholds.get("max_drawdown", 0.35)

    recent_high = get_period_high(high_series, lookback)
    drawdown = compute_drawdown(current_price, recent_high)

    if drawdown < min_drawdown or drawdown > max_drawdown:
        return None

    # Safety filter: prefer above 200-DMA
    long_ma = thresholds.get("long_ma", 200)
    ma_200 = get_ma_value(close_series, long_ma)
    above_200dma = ma_200 is not None and current_price > ma_200

    return {
        "symbol": symbol,
        "type": "BANK_OPPORTUNITY_WATCH",
        "reason": f"Drawdown {drawdown*100:.1f}% during market stress",
        "price": current_price,
        "drawdown_pct": drawdown * 100,
        "above_200dma": above_200dma,
        "dma_200": ma_200,
    }


# ==============================================================================
# FINANCE CONFIRMATION
# ==============================================================================


def check_finance_confirmation(
    symbol: str,
    close_series: pd.Series,
    benchmark_series: pd.Series,
    thresholds: dict,
) -> Optional[dict]:
    """
    Check for finance sector confirmation signals.
    Emits alert when sector underperforms benchmark.
    """
    if not thresholds.get("enabled", True):
        return None

    window = thresholds.get("window_days", 21)
    threshold = thresholds.get("relative_strength_threshold", -0.03)

    rel_strength = compute_relative_strength(close_series, benchmark_series, window)

    if rel_strength < threshold:
        return {
            "symbol": symbol,
            "type": "FINANCE_CONFIRMATION",
            "reason": f"Underperforming {thresholds.get('compare_to', 'SPY')} by {rel_strength*100:.1f}% over {window} days",
            "relative_strength": rel_strength * 100,
        }

    return None


# ==============================================================================
# METRICS CALCULATION
# ==============================================================================


def get_symbol_metrics(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    exit_thresholds: dict,
    entry_thresholds: dict,
) -> Optional[dict]:
    """Get all metrics for a symbol regardless of alert status."""
    if len(close_series) < 100:
        return None

    current_price = float(close_series.iloc[-1])
    dma_50 = get_ma_value(close_series, 50)
    dma_100 = get_ma_value(close_series, 100)

    if dma_50 is None or dma_100 is None:
        return None

    dma_slope = compute_ma_slope(close_series, 100, 10)
    highs = get_multi_timeframe_highs(high_series)

    # Drawdown from 1-day high
    drawdown = compute_drawdown(current_price, highs["high_1d"])
    drawdown_threshold = exit_thresholds.get("drawdown_exit_threshold", 0.10)
    min_pullback = entry_thresholds.get("min_pullback", 0.05)
    max_pullback = entry_thresholds.get("max_pullback", 0.08)

    # Determine status
    if dma_50 < dma_100:
        status = "🚨 EXIT RISK"
        status_reason = "50-DMA < 100-DMA"
    elif drawdown >= drawdown_threshold:
        status = "🚨 EXIT RISK"
        status_reason = f"Drawdown {drawdown*100:.1f}%"
    elif current_price > dma_100 and min_pullback <= drawdown < max_pullback and dma_slope >= -0.01:
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

    # Calculate drops
    drop_1d = compute_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = compute_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = compute_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = compute_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "price": current_price,
        "dma_50": dma_50,
        "dma_100": dma_100,
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


# ==============================================================================
# MAIN ANALYSIS
# ==============================================================================


def analyze_monitored_symbols(
    monitor_symbols: list[str],
    all_data: dict[str, pd.DataFrame],
    config: dict,
    state_dir: str,
    dedupe_window: int,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Analyze monitored symbols for alerts.
    Returns (exit_risks, entry_opps, bank_opps, all_metrics).
    """
    exit_risks = []
    entry_opps = []
    bank_opps = []
    all_metrics = []

    # Get thresholds (use core_trend as default for monitor symbols)
    exit_thresholds = get_exit_thresholds(config, "core_trend")
    entry_thresholds = get_entry_thresholds(config, "core_trend")
    stress_thresholds = get_stress_opportunity_thresholds(config)
    stress_symbols = set(get_category_symbols(config, "stress_opportunities"))

    # Check market stress for bank opportunities
    market_stressed = check_market_stress(all_data, stress_thresholds)

    for symbol in monitor_symbols:
        df = all_data.get(symbol)
        if df is None or len(df) < 100:
            logger.warning(f"{symbol}: Insufficient data, skipping")
            continue

        close = get_close_series(df)
        high = get_high_series(df)

        # Get metrics
        metrics = get_symbol_metrics(symbol, close, high, exit_thresholds, entry_thresholds)
        if metrics:
            all_metrics.append(metrics)

        # Check for stress opportunity (banks) - no exit alerts
        if symbol in stress_symbols:
            bank_alert = check_bank_opportunity(symbol, close, high, stress_thresholds, market_stressed)
            if bank_alert:
                bank_opps.append(bank_alert)
                logger.warning(f"{symbol}: BANK OPPORTUNITY WATCH - {bank_alert['reason']}")
            continue  # Skip regular exit/entry for stress symbols

        # Check exit risk
        exit_alert = check_exit_risk(symbol, close, high, exit_thresholds)
        if exit_alert:
            exit_risks.append(exit_alert)
            logger.warning(f"{symbol}: EXIT RISK - {exit_alert['reason']}")
            continue  # Don't check entry if exit risk

        # Check entry opportunity
        entry_alert = check_entry_opportunity(symbol, close, high, entry_thresholds)
        if entry_alert:
            entry_opps.append(entry_alert)
            logger.info(f"{symbol}: ENTRY OPPORTUNITY - {entry_alert['reason']}")

    return exit_risks, entry_opps, bank_opps, all_metrics


def print_summary_table(all_metrics: list[dict]) -> None:
    """Print the summary table to console."""
    if not all_metrics:
        return

    logger.info("")
    logger.info("=" * 160)
    logger.info("📈 ALL SYMBOLS OVERVIEW")
    logger.info("=" * 160)
    logger.info(f"{'Symbol':<8} {'Status':<14} {'Price':>10} {'1D Drop':>9} {'1W Drop':>9} {'1M Drop':>9} {'3M Drop':>9} {'1D High':>10} {'1W High':>10} {'1M High':>10} {'3M High':>10}")
    logger.info("-" * 160)

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
    logger.info("   🏦 BANK OPP   = Bank opportunity during market stress")
    logger.info("")


def main():
    """Main entry point for the investor alert system."""
    logger.info("=" * 60)
    logger.info("Long-Term Investor Alert System (Config-Driven)")
    logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Load config
    config = load_config()

    # Get settings from config
    state_dir = get_state_dir(config)
    dedupe_window = get_dedupe_window(config)
    batch_size = get_batch_size(config)
    period = get_history_period(config, "monitor")
    monitor_file = get_monitor_symbols_file(config)
    global_filters = get_global_filters(config)

    # Ensure state directory exists
    ensure_state_dir(state_dir)

    # Cleanup old alerts
    cleanup_old_alerts(state_dir)

    # Load monitor symbols (existing stocks.json)
    monitor_symbols = load_monitor_symbols(monitor_file)
    if not monitor_symbols:
        logger.error("No symbols to analyze. Exiting.")
        return

    # Collect all symbols needed
    all_symbols = collect_all_symbols(config, monitor_symbols)
    logger.info(f"Total unique symbols to fetch: {len(all_symbols)}")

    # Fetch all data
    all_data = batch_download(all_symbols, period=period, batch_size=batch_size)
    if not all_data:
        logger.error("Failed to fetch any data. Exiting.")
        return

    # Analyze monitored symbols
    exit_risks, entry_opps, bank_opps, all_metrics = analyze_monitored_symbols(
        monitor_symbols, all_data, config, state_dir, dedupe_window
    )

    # Summary
    logger.info("=" * 60)
    logger.info(f"Analysis complete.")
    logger.info(f"Exit Risks: {len(exit_risks)}")
    logger.info(f"Entry Opportunities: {len(entry_opps)}")
    logger.info(f"Bank Opportunities: {len(bank_opps)}")

    # Print summary table
    print_summary_table(all_metrics)

    # Send Telegram summary
    if is_telegram_enabled(config) and all_metrics:
        message = format_weekly_summary(all_metrics, exit_risks, entry_opps, bank_opps)
        send_telegram(message)

    logger.info("=" * 60)
    logger.info("Done.")


if __name__ == "__main__":
    main()
