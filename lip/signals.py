"""
Signals Module
==============
Technical indicator calculations for monitoring and discovery.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ==============================================================================
# MOVING AVERAGES
# ==============================================================================


def compute_ma(series: pd.Series, window: int) -> pd.Series:
    """Compute simple moving average."""
    return series.rolling(window=window).mean()


def compute_ma_slope(series: pd.Series, ma_window: int, slope_window: int = 10) -> float:
    """
    Compute the slope of a moving average over recent days.
    Returns percentage change.
    """
    ma = compute_ma(series, ma_window).dropna()
    if len(ma) < slope_window:
        return 0.0

    recent_ma = ma.tail(slope_window)
    if recent_ma.iloc[0] == 0:
        return 0.0

    slope = (recent_ma.iloc[-1] - recent_ma.iloc[0]) / recent_ma.iloc[0]
    return float(slope)


def get_ma_value(series: pd.Series, window: int) -> Optional[float]:
    """Get the latest MA value."""
    ma = compute_ma(series, window).dropna()
    return float(ma.iloc[-1]) if len(ma) > 0 else None


# ==============================================================================
# DRAWDOWN & PULLBACK
# ==============================================================================


def compute_drawdown(current_price: float, high_price: float) -> float:
    """Calculate drawdown from a high price."""
    if high_price <= 0:
        return 0.0
    return (high_price - current_price) / high_price


def get_period_high(series: pd.Series, days: int) -> float:
    """Get highest value in the last N days."""
    if len(series) < 1:
        return 0.0
    recent = series.tail(days)
    return float(recent.max()) if len(recent) > 0 else 0.0


def get_multi_timeframe_highs(high_series: pd.Series) -> dict:
    """Get highest prices for multiple timeframes using High prices."""
    return {
        "high_1d": float(high_series.iloc[-1]) if len(high_series) >= 1 else 0,
        "high_1w": get_period_high(high_series, 5),
        "high_1m": get_period_high(high_series, 21),
        "high_3m": get_period_high(high_series, 63),
        "high_6m": get_period_high(high_series, 126),
    }


def compute_pullback(current_price: float, recent_high: float) -> float:
    """Calculate pullback percentage from recent high."""
    return compute_drawdown(current_price, recent_high)


# ==============================================================================
# STABILITY & VOLATILITY
# ==============================================================================


def check_stability(series: pd.Series, days: int, max_single_day_drop: float) -> bool:
    """
    Check if recent closes are stable (no extreme drops).
    Returns True if no single day dropped more than threshold.
    """
    if len(series) < days:
        return False

    recent = series.tail(days)
    daily_changes = recent.pct_change().dropna()

    if len(daily_changes) == 0:
        return True

    # Check for any extreme down day
    min_change = daily_changes.min()
    return min_change > -max_single_day_drop


def is_overheated(current_price: float, short_ma: float, max_multiple: float = 1.12) -> bool:
    """Check if price is overheated (too far above short MA)."""
    if short_ma <= 0:
        return False
    return current_price > (short_ma * max_multiple)


# ==============================================================================
# TREND FILTERS
# ==============================================================================


def is_above_ma(current_price: float, ma_value: float) -> bool:
    """Check if current price is above a moving average."""
    if ma_value is None or ma_value <= 0:
        return False
    return current_price > ma_value


def is_ma_crossover_bearish(short_ma: float, long_ma: float) -> bool:
    """Check if short MA is below long MA (bearish crossover)."""
    if short_ma is None or long_ma is None:
        return False
    return short_ma < long_ma


def is_ma_slope_rising(slope: float, threshold: float = -0.01) -> bool:
    """Check if MA slope is flat or rising."""
    return slope >= threshold


def days_below_ma(close_series: pd.Series, ma_window: int, check_days: int) -> int:
    """Count how many of the last N days price was below MA."""
    if len(close_series) < ma_window:
        return 0

    ma = compute_ma(close_series, ma_window)
    recent_close = close_series.tail(check_days)
    recent_ma = ma.tail(check_days)

    if len(recent_close) != len(recent_ma):
        return 0

    below_count = (recent_close < recent_ma).sum()
    return int(below_count)


# ==============================================================================
# RELATIVE STRENGTH
# ==============================================================================


def compute_relative_strength(
    symbol_series: pd.Series,
    benchmark_series: pd.Series,
    window: int = 21
) -> float:
    """
    Compute relative strength vs benchmark over a window.
    Returns percentage outperformance.
    """
    if len(symbol_series) < window or len(benchmark_series) < window:
        return 0.0

    symbol_recent = symbol_series.tail(window)
    benchmark_recent = benchmark_series.tail(window)

    if symbol_recent.iloc[0] == 0 or benchmark_recent.iloc[0] == 0:
        return 0.0

    symbol_return = (symbol_recent.iloc[-1] / symbol_recent.iloc[0]) - 1
    benchmark_return = (benchmark_recent.iloc[-1] / benchmark_recent.iloc[0]) - 1

    return float(symbol_return - benchmark_return)


# ==============================================================================
# SCORING (for Discovery)
# ==============================================================================


def compute_discovery_score(
    drawdown: float = 0,
    slope: float = 0,
    is_above_ma: bool = False,
    relative_strength: float = 0,
    weights: dict = None,
) -> float:
    """
    Compute discovery score for a symbol using weighted factors.
    Returns a score between 0 and 1.

    Args:
        drawdown: Current drawdown (0-1)
        slope: MA slope (percentage)
        is_above_ma: Whether price is above long MA
        relative_strength: RS vs benchmark (percentage)
        weights: Optional custom weights

    Returns:
        Score between 0 and 1
    """
    if weights is None:
        weights = {
            "above_ma": 0.25,
            "slope": 0.25,
            "drawdown": 0.25,
            "relative_strength": 0.25,
        }

    score = 0.0

    # Above MA component (binary)
    if is_above_ma:
        score += weights.get("above_ma", 0.25)

    # Slope component (higher slope = better, cap at 5%)
    if slope > 0:
        slope_score = min(slope / 0.05, 1.0) * weights.get("slope", 0.25)
        score += slope_score

    # Drawdown component (lower drawdown = better)
    # Ideal: 0-5% pullback, acceptable up to 10%
    if drawdown < 0.10:
        drawdown_score = (1 - drawdown / 0.10) * weights.get("drawdown", 0.25)
        score += drawdown_score

    # Relative strength component
    if relative_strength > 0:
        rs_score = min(relative_strength / 0.05, 1.0) * weights.get("relative_strength", 0.25)
        score += rs_score

    return min(score, 1.0)


def compute_detailed_discovery_score(
    current_price: float,
    close_series: pd.Series,
    high_series: pd.Series,
    config_thresholds: dict,
) -> tuple[int, list[str]]:
    """
    Compute detailed discovery score for a symbol.
    Returns (score, list of reasons).

    This is the original detailed scoring with reasons.
    """
    score = 0
    reasons = []

    # Get MAs
    ma_50 = get_ma_value(close_series, 50)
    ma_100 = get_ma_value(close_series, 100)

    if ma_50 is None or ma_100 is None:
        return 0, ["Insufficient data"]

    # +2 if close > 100DMA
    if current_price > ma_100:
        score += 2
        reasons.append("Price > 100DMA (+2)")

    # +2 if 50DMA > 100DMA
    if ma_50 > ma_100:
        score += 2
        reasons.append("50DMA > 100DMA (+2)")

    # +1 if 100DMA slope rising
    slope = compute_ma_slope(close_series, 100, 10)
    if slope > 0:
        score += 1
        reasons.append("100DMA rising (+1)")

    # Pullback in healthy trend
    recent_high = get_period_high(high_series, 42)
    pullback = compute_pullback(current_price, recent_high)
    min_pullback = config_thresholds.get("min_pullback", 0.05)
    max_pullback = config_thresholds.get("max_pullback", 0.08)

    if current_price > ma_100 and min_pullback <= pullback <= max_pullback:
        score += 1
        reasons.append(f"Healthy pullback {pullback*100:.1f}% (+1)")

    # Penalties
    # -2 if drawdown >= 10%
    drawdown_high = get_period_high(high_series, 63)
    drawdown = compute_drawdown(current_price, drawdown_high)
    drawdown_threshold = config_thresholds.get("drawdown_threshold", 0.10)

    if drawdown >= drawdown_threshold:
        score -= 2
        reasons.append(f"High drawdown {drawdown*100:.1f}% (-2)")

    # -1 if overheated
    overheat_multiple = config_thresholds.get("overheat_multiple", 1.12)
    if is_overheated(current_price, ma_50, overheat_multiple):
        score -= 1
        reasons.append("Overheated (-1)")

    # -1 if sharp down day in last 5
    max_drop = config_thresholds.get("max_single_day_drop", 0.07)
    if not check_stability(close_series, 5, max_drop):
        score -= 1
        reasons.append("Recent crash day (-1)")

    return score, reasons
