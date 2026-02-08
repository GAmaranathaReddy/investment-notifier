"""
Config Module
=============
Configuration loading and parsing utilities.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = "config.json"


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to config.json

    Returns:
        Configuration dictionary
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return get_default_config()

    try:
        with open(path, "r") as f:
            config = json.load(f)
        logger.info(f"Loaded config from {config_path}")
        return config
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config: {e}")
        return get_default_config()


def get_default_config() -> dict:
    """Return default configuration."""
    return {
        "app": {
            "mode": {"monitor_enabled": True, "discovery_enabled": False},
            "data_source": {
                "provider": "yfinance",
                "interval": "1d",
                "history_period_monitor": "12mo",
                "history_period_discovery": "12mo",
                "batch_size": 25,
            },
            "outputs": {
                "recommended_symbols_file": "recommended_symbols.json",
                "monitor_symbols_file": "stocks.json",
                "state_dir": "state",
            },
        },
        "notifications": {
            "telegram": {
                "enabled": True,
                "anti_spam": {"dedupe_window_days": 3, "max_messages_per_run": 10},
            }
        },
        "global_filters": {"min_history_days": 120, "min_price": 5},
    }


# ==============================================================================
# CONFIG ACCESSORS
# ==============================================================================


def get_nested(config: dict, *keys, default: Any = None) -> Any:
    """Safely get nested config value."""
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def get_batch_size(config: dict) -> int:
    """Get batch size for API requests."""
    return get_nested(config, "app", "data_source", "batch_size", default=25)


def get_history_period(config: dict, mode: str = "monitor") -> str:
    """Get history period for data fetching."""
    key = f"history_period_{mode}"
    return get_nested(config, "app", "data_source", key, default="12mo")


def get_state_dir(config: dict) -> str:
    """Get state directory path."""
    return get_nested(config, "app", "outputs", "state_dir", default="state")


def get_monitor_symbols_file(config: dict) -> str:
    """Get monitor symbols file path."""
    return get_nested(config, "app", "outputs", "monitor_symbols_file", default="stocks.json")


def get_recommended_symbols_file(config: dict) -> str:
    """Get recommended symbols output file path."""
    return get_nested(config, "app", "outputs", "recommended_symbols_file", default="recommended_symbols.json")


def get_dedupe_window(config: dict) -> int:
    """Get alert dedupe window in days."""
    return get_nested(config, "notifications", "telegram", "anti_spam", "dedupe_window_days", default=3)


def is_telegram_enabled(config: dict) -> bool:
    """Check if Telegram notifications are enabled."""
    return get_nested(config, "notifications", "telegram", "enabled", default=True)


def is_monitor_enabled(config: dict) -> bool:
    """Check if monitoring mode is enabled."""
    return get_nested(config, "app", "mode", "monitor_enabled", default=True)


def is_discovery_enabled(config: dict) -> bool:
    """Check if discovery mode is enabled."""
    return get_nested(config, "app", "mode", "discovery_enabled", default=False)


# ==============================================================================
# CATEGORY ACCESSORS
# ==============================================================================


def get_category_config(config: dict, category: str) -> dict:
    """Get configuration for a specific category."""
    return get_nested(config, "categories", category, default={})


def get_category_symbols(config: dict, category: str) -> list[str]:
    """Get symbols for a category."""
    cat_config = get_category_config(config, category)
    return cat_config.get("symbols", [])


def get_category_rules(config: dict, category: str, rule_type: str) -> dict:
    """Get rules for a category (exit, entry, opportunity, etc.)."""
    cat_config = get_category_config(config, category)
    return get_nested(cat_config, "rules", rule_type, default={})


def get_emerging_baskets(config: dict) -> dict:
    """Get emerging rotation baskets."""
    return get_nested(config, "categories", "emerging_rotation", "baskets", default={})


def get_expand_config(config: dict) -> dict:
    """Get emerging rotation expansion configuration."""
    return get_nested(config, "categories", "emerging_rotation", "expand", default={})


def get_emerging_rotation_config(config: dict) -> dict:
    """Get full emerging rotation configuration including baskets and expansion rules."""
    cat_config = get_category_config(config, "emerging_rotation")
    entry_rules = get_category_rules(config, "emerging_rotation", "entry")
    trend = entry_rules.get("trend_filter", {})
    pullback = entry_rules.get("pullback", {})

    return {
        "baskets": cat_config.get("baskets", {}),
        "expand": cat_config.get("expand", {}),
        "expansion_rules": {
            "short_ma": trend.get("short_ma", 50),
            "long_ma": trend.get("long_ma", 100),
            "relative_strength_window": 21,
            "relative_strength_threshold": 0.02,
            "lookback_high_days": pullback.get("lookback_high_days", 21),
            "max_drawdown": pullback.get("max_pullback", 0.15),
            "min_slope": 0.005,
        },
    }


# ==============================================================================
# THRESHOLD EXTRACTION
# ==============================================================================


def get_exit_thresholds(config: dict, category: str) -> dict:
    """Extract exit rule thresholds for a category."""
    rules = get_category_rules(config, category, "exit")
    return {
        "enabled": rules.get("enabled", True),
        "use_ma_crossover": rules.get("use_ma_crossover", True),
        "short_ma": rules.get("short_ma", 50),
        "long_ma": rules.get("long_ma", 100),
        "drawdown_lookback_days": rules.get("drawdown_lookback_days", 63),
        "drawdown_exit_threshold": rules.get("drawdown_exit_threshold", 0.10),
        "price_below_long_ma_days": rules.get("price_below_long_ma_days", 3),
    }


def get_entry_thresholds(config: dict, category: str) -> dict:
    """Extract entry rule thresholds for a category."""
    rules = get_category_rules(config, category, "entry")
    trend = rules.get("trend_filter", {})
    pullback = rules.get("pullback", {})
    stability = rules.get("stability", {})
    overheat = rules.get("overheat_filter", {})

    return {
        "enabled": rules.get("enabled", True),
        "price_above_long_ma": trend.get("price_above_long_ma", True),
        "long_ma": trend.get("long_ma", 100),
        "short_ma": trend.get("short_ma", 50),
        "long_ma_slope_days": trend.get("long_ma_slope_days", 10),
        "lookback_high_days": pullback.get("lookback_high_days", 42),
        "min_pullback": pullback.get("min_pullback", 0.05),
        "max_pullback": pullback.get("max_pullback", 0.08),
        "stability_days": stability.get("check_last_n_days", 5),
        "max_single_day_drop": stability.get("max_single_day_drop", 0.07),
        "overheat_enabled": overheat.get("enabled", True),
        "overheat_multiple": overheat.get("max_close_over_short_ma_multiple", 1.12),
    }


def get_stress_opportunity_thresholds(config: dict) -> dict:
    """Extract stress opportunity thresholds."""
    rules = get_category_rules(config, "stress_opportunities", "opportunity")
    stress = rules.get("market_stress_signals", {})
    dip = rules.get("dip_buy_trigger", {})
    safety = rules.get("safety_filter", {})

    return {
        "enabled": rules.get("enabled", True),
        "requires_stress_confirmation": rules.get("requires_market_stress_confirmation", True),
        "stress_watch_symbols": stress.get("stress_watch_symbols", ["SPY", "VIXY", "KRE"]),
        "stress_vixy_trending_up": stress.get("stress_if_vixy_trending_up", True),
        "stress_kre_below_long_ma": stress.get("stress_if_kre_below_long_ma", True),
        "stress_spy_drawdown_threshold": stress.get("stress_if_spy_drawdown_threshold", 0.08),
        "dip_lookback_days": dip.get("lookback_high_days", 126),
        "min_drawdown": dip.get("min_drawdown", 0.15),
        "max_drawdown": dip.get("max_drawdown", 0.35),
        "prefer_above_long_ma": safety.get("prefer_price_above_long_ma", True),
        "long_ma": safety.get("long_ma", 200),
    }


def get_finance_confirmation_thresholds(config: dict) -> dict:
    """Extract finance confirmation thresholds."""
    rules = get_category_rules(config, "finance_confirmation", "alerts")
    underperform = rules.get("underperform_watch", {})

    return {
        "enabled": rules.get("enabled", True),
        "compare_to": underperform.get("compare_to", "SPY"),
        "window_days": underperform.get("window_days", 21),
        "relative_strength_threshold": underperform.get("alert_if_relative_strength_below", -0.03),
    }


def get_discovery_scoring_thresholds(config: dict) -> dict:
    """Get thresholds for discovery scoring."""
    # Use emerging rotation entry rules as base
    entry = get_entry_thresholds(config, "emerging_rotation")

    return {
        "min_pullback": entry.get("min_pullback", 0.05),
        "max_pullback": entry.get("max_pullback", 0.08),
        "drawdown_threshold": 0.10,  # Fixed for scoring
        "overheat_multiple": entry.get("overheat_multiple", 1.12),
        "max_single_day_drop": entry.get("max_single_day_drop", 0.07),
        "min_score": 0.5,  # Minimum score to be recommended
        "weights": {
            "above_ma": 0.25,
            "slope": 0.25,
            "drawdown": 0.25,
            "relative_strength": 0.25,
        },
    }


def get_global_filters(config: dict) -> dict:
    """Get global filter settings."""
    return get_nested(config, "global_filters", default={
        "min_history_days": 120,
        "min_price": 5,
        "exclude_otc": True,
        "exclude_leveraged_etfs": True,
        "max_universe_size": 200,
    })
