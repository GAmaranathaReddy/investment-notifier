#!/usr/bin/env python3
"""
Symbol Discovery Pipeline
=========================
Scans universe of symbols to find promising candidates based on config rules.
Generates recommended_symbols.json for monitoring.

Supports:
- Core Trend: Stable uptrend leaders with low drawdown
- Emerging Rotation: Sector rotation plays (commodities, AI, clean energy, etc.)
- Stress Opportunities: High-quality banks to watch during panic
- Defensive Protection: Capital protection instruments

Usage:
    python discover_symbols.py

Environment Variables:
    TELEGRAM_BOT_TOKEN - Your Telegram bot token (optional)
    TELEGRAM_CHAT_ID - Your Telegram chat ID (optional)
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
    get_dedupe_window,
    is_telegram_enabled,
    get_category_symbols,
    get_entry_thresholds,
    get_stress_opportunity_thresholds,
    get_emerging_rotation_config,
    get_discovery_scoring_thresholds,
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
    is_overheated,
    compute_relative_strength,
    compute_discovery_score,
)
from lib.alerts import (
    send_telegram,
    should_send_alert,
    record_alert_sent,
    ensure_state_dir,
    format_recommendations_summary,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# UNIVERSE LOADING
# ==============================================================================


def load_universe(config: dict) -> dict[str, list[str]]:
    """Load discovery universe from config categories."""
    universe = {
        "core_trend": get_category_symbols(config, "core_trend"),
        "stress_opportunities": get_category_symbols(config, "stress_opportunities"),
        "defensive_protection": get_category_symbols(config, "defensive_protection"),
    }

    # Load emerging rotation baskets
    emerging_config = get_emerging_rotation_config(config)
    baskets = emerging_config.get("baskets", {})

    for basket_name, basket_symbols in baskets.items():
        universe[f"emerging_{basket_name}"] = basket_symbols

    return universe


def get_all_universe_symbols(universe: dict[str, list[str]]) -> list[str]:
    """Get all unique symbols from universe."""
    all_symbols = set()
    for symbols in universe.values():
        all_symbols.update(symbols)
    return list(all_symbols)


# ==============================================================================
# DISCOVERY FILTERS
# ==============================================================================


def passes_global_filters(
    symbol: str,
    close_series: pd.Series,
    global_filters: dict,
) -> bool:
    """Check if symbol passes global filters."""
    min_history = global_filters.get("min_history_days", 126)
    if len(close_series) < min_history:
        return False

    min_price = global_filters.get("min_price", 5.0)
    if float(close_series.iloc[-1]) < min_price:
        return False

    return True


def evaluate_core_trend_candidate(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    thresholds: dict,
    scoring: dict,
) -> Optional[dict]:
    """
    Evaluate a symbol for Core Trend category.
    Returns candidate dict if it passes, None otherwise.
    """
    current_price = float(close_series.iloc[-1])

    # Basic trend filter: price above 100-DMA with rising slope
    long_ma = get_ma_value(close_series, thresholds["long_ma"])
    short_ma = get_ma_value(close_series, thresholds.get("short_ma", 50))

    if long_ma is None:
        return None

    if not is_above_ma(current_price, long_ma):
        return None

    slope = compute_ma_slope(close_series, thresholds["long_ma"], thresholds.get("long_ma_slope_days", 10))
    if slope < -0.01:  # Reject if trend is declining
        return None

    # Drawdown filter
    lookback = thresholds.get("lookback_high_days", 42)
    recent_high = get_period_high(high_series, lookback)
    drawdown = compute_drawdown(current_price, recent_high)

    min_pullback = thresholds.get("min_pullback", 0.05)
    max_pullback = thresholds.get("max_pullback", 0.08)

    # Calculate score
    score = compute_discovery_score(
        drawdown=drawdown,
        slope=slope,
        is_above_ma=True,
        relative_strength=0,  # Not used for core trend
        weights=scoring.get("weights", {}),
    )

    # Score threshold
    min_score = scoring.get("min_score", 0.5)
    if score < min_score:
        return None

    status = "pullback_zone" if min_pullback <= drawdown < max_pullback else "watch"

    # Get multi-timeframe highs
    highs = get_multi_timeframe_highs(high_series)
    drop_1d = compute_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = compute_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = compute_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = compute_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "category": "core_trend",
        "price": current_price,
        "dma_100": long_ma,
        "dma_50": short_ma,
        "high_1d": highs["high_1d"],
        "high_1w": highs["high_1w"],
        "high_1m": highs["high_1m"],
        "high_3m": highs["high_3m"],
        "drop_1d": drop_1d,
        "drop_1w": drop_1w,
        "drop_1m": drop_1m,
        "drop_3m": drop_3m,
        "drawdown_pct": drawdown * 100,
        "slope_pct": slope * 100,
        "score": score,
        "status": status,
        "reason": f"Score {score:.2f}, Pullback {drawdown*100:.1f}%, Slope {slope*100:.2f}%",
    }


def evaluate_emerging_rotation_candidate(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    benchmark_series: pd.Series,
    basket_name: str,
    emerging_config: dict,
    scoring: dict,
) -> Optional[dict]:
    """
    Evaluate a symbol for Emerging Rotation category.
    Returns candidate dict if it passes, None otherwise.
    """
    expansion_rules = emerging_config.get("expansion_rules", {})

    current_price = float(close_series.iloc[-1])

    # MA filter
    short_ma_period = expansion_rules.get("short_ma", 50)
    long_ma_period = expansion_rules.get("long_ma", 100)
    short_ma = get_ma_value(close_series, short_ma_period)
    long_ma = get_ma_value(close_series, long_ma_period)

    if short_ma is None or long_ma is None:
        return None

    # Must be above short MA
    if not is_above_ma(current_price, short_ma):
        return None

    # Relative strength vs benchmark
    window = expansion_rules.get("relative_strength_window", 21)
    rs_threshold = expansion_rules.get("relative_strength_threshold", 0.02)
    rel_strength = compute_relative_strength(close_series, benchmark_series, window)

    if rel_strength < rs_threshold:
        return None

    # Drawdown filter
    lookback = expansion_rules.get("lookback_high_days", 21)
    recent_high = get_period_high(high_series, lookback)
    drawdown = compute_drawdown(current_price, recent_high)

    max_drawdown = expansion_rules.get("max_drawdown", 0.15)
    if drawdown > max_drawdown:
        return None

    # Slope filter
    slope = compute_ma_slope(close_series, short_ma_period, 10)
    min_slope = expansion_rules.get("min_slope", 0.005)
    if slope < min_slope:
        return None

    # Calculate score
    score = compute_discovery_score(
        drawdown=drawdown,
        slope=slope,
        is_above_ma=True,
        relative_strength=rel_strength,
        weights=scoring.get("weights", {}),
    )

    min_score = scoring.get("min_score", 0.5)
    if score < min_score:
        return None

    # Get multi-timeframe highs
    highs = get_multi_timeframe_highs(high_series)
    drop_1d = compute_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = compute_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = compute_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = compute_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "category": "emerging_rotation",
        "basket": basket_name,
        "price": current_price,
        "dma_50": short_ma,
        "dma_100": long_ma,
        "high_1d": highs["high_1d"],
        "high_1w": highs["high_1w"],
        "high_1m": highs["high_1m"],
        "high_3m": highs["high_3m"],
        "drop_1d": drop_1d,
        "drop_1w": drop_1w,
        "drop_1m": drop_1m,
        "drop_3m": drop_3m,
        "relative_strength_pct": rel_strength * 100,
        "drawdown_pct": drawdown * 100,
        "slope_pct": slope * 100,
        "score": score,
        "status": "momentum",
        "reason": f"Score {score:.2f}, RS +{rel_strength*100:.1f}%, Slope {slope*100:.2f}%",
    }


def evaluate_stress_opportunity_candidate(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
    thresholds: dict,
) -> Optional[dict]:
    """
    Evaluate a symbol for Stress Opportunities (bank watch list).
    These are always included but flagged for stress monitoring.
    """
    current_price = float(close_series.iloc[-1])

    # Calculate current metrics for watchlist
    long_ma = get_ma_value(close_series, thresholds.get("long_ma", 200))

    lookback = thresholds.get("dip_lookback_days", 126)
    recent_high = get_period_high(high_series, lookback)
    drawdown = compute_drawdown(current_price, recent_high)

    above_200dma = long_ma is not None and current_price > long_ma

    # Always include banks in watchlist
    min_dd = thresholds.get("min_drawdown", 0.15)
    max_dd = thresholds.get("max_drawdown", 0.35)

    if min_dd <= drawdown <= max_dd:
        status = "opportunity_zone"
    else:
        status = "watch"

    # Get multi-timeframe highs
    highs = get_multi_timeframe_highs(high_series)
    drop_1d = compute_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = compute_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = compute_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = compute_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "category": "stress_opportunities",
        "price": current_price,
        "dma_200": long_ma,
        "high_1d": highs["high_1d"],
        "high_1w": highs["high_1w"],
        "high_1m": highs["high_1m"],
        "high_3m": highs["high_3m"],
        "drop_1d": drop_1d,
        "drop_1w": drop_1w,
        "drop_1m": drop_1m,
        "drop_3m": drop_3m,
        "drawdown_pct": drawdown * 100,
        "above_200dma": above_200dma,
        "status": status,
        "reason": f"Drawdown {drawdown*100:.1f}%, {'Above' if above_200dma else 'Below'} 200-DMA",
    }


def evaluate_defensive_candidate(
    symbol: str,
    close_series: pd.Series,
    high_series: pd.Series,
) -> Optional[dict]:
    """
    Evaluate a defensive protection symbol.
    These are always included in recommendations for hedging.
    """
    current_price = float(close_series.iloc[-1])

    dma_50 = get_ma_value(close_series, 50)
    dma_200 = get_ma_value(close_series, 200)

    # Get multi-timeframe highs
    highs = get_multi_timeframe_highs(high_series)
    drop_1d = compute_drawdown(current_price, highs["high_1d"]) * 100
    drop_1w = compute_drawdown(current_price, highs["high_1w"]) * 100
    drop_1m = compute_drawdown(current_price, highs["high_1m"]) * 100
    drop_3m = compute_drawdown(current_price, highs["high_3m"]) * 100

    return {
        "symbol": symbol,
        "category": "defensive_protection",
        "price": current_price,
        "dma_50": dma_50,
        "dma_200": dma_200,
        "high_1d": highs["high_1d"],
        "high_1w": highs["high_1w"],
        "high_1m": highs["high_1m"],
        "high_3m": highs["high_3m"],
        "drop_1d": drop_1d,
        "drop_1w": drop_1w,
        "drop_1m": drop_1m,
        "drop_3m": drop_3m,
        "status": "available",
        "reason": "Defensive hedge instrument",
    }


# ==============================================================================
# DISCOVERY PIPELINE
# ==============================================================================


def run_discovery(
    all_data: dict[str, pd.DataFrame],
    universe: dict[str, list[str]],
    config: dict,
) -> list[dict]:
    """
    Run discovery pipeline across all universe categories.
    Returns list of recommended candidates.
    """
    recommendations = []

    global_filters = get_global_filters(config)
    scoring = get_discovery_scoring_thresholds(config)
    entry_thresholds = get_entry_thresholds(config, "core_trend")
    stress_thresholds = get_stress_opportunity_thresholds(config)
    emerging_config = get_emerging_rotation_config(config)

    # Get benchmark data for relative strength
    benchmark_symbol = "SPY"
    benchmark_data = all_data.get(benchmark_symbol)
    benchmark_series = get_close_series(benchmark_data) if benchmark_data is not None else None

    # Process core trend
    logger.info("Evaluating Core Trend candidates...")
    for symbol in universe.get("core_trend", []):
        df = all_data.get(symbol)
        if df is None:
            continue

        close = get_close_series(df)
        high = get_high_series(df)

        if not passes_global_filters(symbol, close, global_filters):
            continue

        candidate = evaluate_core_trend_candidate(symbol, close, high, entry_thresholds, scoring)
        if candidate:
            recommendations.append(candidate)
            logger.info(f"  ✓ {symbol}: {candidate['reason']}")

    # Process emerging rotation baskets
    logger.info("Evaluating Emerging Rotation candidates...")
    for key, symbols in universe.items():
        if not key.startswith("emerging_"):
            continue

        basket_name = key.replace("emerging_", "")

        for symbol in symbols:
            df = all_data.get(symbol)
            if df is None or benchmark_series is None:
                continue

            close = get_close_series(df)
            high = get_high_series(df)

            if not passes_global_filters(symbol, close, global_filters):
                continue

            candidate = evaluate_emerging_rotation_candidate(
                symbol, close, high, benchmark_series, basket_name, emerging_config, scoring
            )
            if candidate:
                recommendations.append(candidate)
                logger.info(f"  ✓ {symbol} ({basket_name}): {candidate['reason']}")

    # Process stress opportunities (banks)
    logger.info("Evaluating Stress Opportunities (banks)...")
    for symbol in universe.get("stress_opportunities", []):
        df = all_data.get(symbol)
        if df is None:
            continue

        close = get_close_series(df)
        high = get_high_series(df)

        if not passes_global_filters(symbol, close, global_filters):
            continue

        candidate = evaluate_stress_opportunity_candidate(symbol, close, high, stress_thresholds)
        if candidate:
            recommendations.append(candidate)
            logger.info(f"  ✓ {symbol}: {candidate['reason']}")

    # Process defensive protection
    logger.info("Evaluating Defensive Protection...")
    for symbol in universe.get("defensive_protection", []):
        df = all_data.get(symbol)
        if df is None:
            continue

        close = get_close_series(df)
        high = get_high_series(df)

        if not passes_global_filters(symbol, close, global_filters):
            continue

        candidate = evaluate_defensive_candidate(symbol, close, high)
        if candidate:
            recommendations.append(candidate)
            logger.info(f"  ✓ {symbol}: {candidate['reason']}")

    return recommendations


# ==============================================================================
# OUTPUT GENERATION
# ==============================================================================


def save_recommendations(recommendations: list[dict], output_file: str) -> None:
    """Save recommendations to JSON file."""
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_count": len(recommendations),
        "by_category": {},
        "recommendations": recommendations,
    }

    # Group by category
    for rec in recommendations:
        cat = rec["category"]
        if cat not in output["by_category"]:
            output["by_category"][cat] = []
        output["by_category"][cat].append(rec["symbol"])

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Saved {len(recommendations)} recommendations to {output_file}")


def print_discovery_summary(recommendations: list[dict]) -> None:
    """Print discovery summary to console matching monitor format."""
    logger.info("")
    logger.info("=" * 160)
    logger.info("🔍 DISCOVERY SUMMARY")
    logger.info("=" * 160)

    # Group by category
    by_category = {}
    for rec in recommendations:
        cat = rec["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(rec)

    for category, recs in by_category.items():
        logger.info("")
        logger.info(f"📊 {category.upper().replace('_', ' ')} ({len(recs)} candidates)")
        logger.info("-" * 160)

        # Print header (same as monitor format)
        logger.info(
            f"{'Symbol':<8} {'Status':<14} {'Price':>10} "
            f"{'1D Drop':>9} {'1W Drop':>9} {'1M Drop':>9} {'3M Drop':>9} "
            f"{'1D High':>10} {'1W High':>10} {'1M High':>10} {'3M High':>10}"
        )
        logger.info("-" * 160)

        # Sort by 3M drop (descending) like monitor format
        sorted_recs = sorted(recs, key=lambda x: x.get("drop_3m", 0), reverse=True)

        for rec in sorted_recs[:15]:  # Top 15 per category
            # Determine status emoji
            status = rec.get("status", "watch")
            if status in ["pullback_zone", "opportunity_zone"]:
                status_display = "🟢 OPPORTUNITY"
            elif status == "momentum":
                status_display = "🚀 MOMENTUM"
            elif status == "available":
                status_display = "🛡️ DEFENSIVE"
            else:
                status_display = "👀 WATCH"

            logger.info(
                f"{rec['symbol']:<8} {status_display:<14} "
                f"${rec['price']:>9.2f} "
                f"{rec.get('drop_1d', 0):>8.1f}% {rec.get('drop_1w', 0):>8.1f}% "
                f"{rec.get('drop_1m', 0):>8.1f}% {rec.get('drop_3m', 0):>8.1f}% "
                f"${rec.get('high_1d', 0):>9.2f} ${rec.get('high_1w', 0):>9.2f} "
                f"${rec.get('high_1m', 0):>9.2f} ${rec.get('high_3m', 0):>9.2f}"
            )

    logger.info("-" * 160)
    logger.info("")
    logger.info("📖 STATUS GUIDE:")
    logger.info("   🟢 OPPORTUNITY = In pullback zone / stress opportunity zone → Consider entry")
    logger.info("   🚀 MOMENTUM    = Strong relative strength, rising trend → Watch for pullback")
    logger.info("   🛡️ DEFENSIVE   = Capital protection hedge instrument → For risk-off positioning")
    logger.info("   👀 WATCH       = Monitoring, not yet in ideal entry zone")
    logger.info("")


# ==============================================================================
# MAIN
# ==============================================================================


def main():
    """Main entry point for discovery pipeline."""
    logger.info("=" * 60)
    logger.info("Symbol Discovery Pipeline")
    logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Load config
    config = load_config()

    # Get settings
    state_dir = get_state_dir(config)
    dedupe_window = get_dedupe_window(config)
    batch_size = get_batch_size(config)
    period = get_history_period(config, "discovery")

    ensure_state_dir(state_dir)

    # Load universe from config
    universe = load_universe(config)
    all_symbols = get_all_universe_symbols(universe)

    # Add SPY for benchmark
    if "SPY" not in all_symbols:
        all_symbols.append("SPY")

    logger.info(f"Universe contains {len(all_symbols)} unique symbols across {len(universe)} categories")

    # Fetch data
    all_data = batch_download(all_symbols, period=period, batch_size=batch_size)
    if not all_data:
        logger.error("Failed to fetch data. Exiting.")
        return

    # Run discovery
    recommendations = run_discovery(all_data, universe, config)

    # Save recommendations
    output_file = "recommended_symbols.json"
    save_recommendations(recommendations, output_file)

    # Print summary
    print_discovery_summary(recommendations)

    # Send Telegram notification if enabled
    if is_telegram_enabled(config) and recommendations:
        # Always send (no dedupe)
        new_symbols = [r["symbol"] for r in recommendations]
        messages = format_recommendations_summary(recommendations, new_symbols)
        for msg in messages:
            send_telegram(msg)
        logger.info(f"Sent {len(messages)} discovery messages to Telegram")

    logger.info("=" * 60)
    logger.info("Discovery complete.")


if __name__ == "__main__":
    main()
