"""
Alerts Module
=============
Telegram notifications and alert state/dedupe management.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ==============================================================================
# TELEGRAM
# ==============================================================================


def send_telegram(
    text: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = None,
) -> bool:
    """
    Send a message via Telegram Bot API.

    Args:
        text: Message text
        bot_token: Bot token (reads from env if not provided)
        chat_id: Chat ID (reads from env if not provided)
        parse_mode: Message parse mode (None for plain text, "Markdown" or "HTML")

    Returns:
        True if successful, False otherwise
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat:
        logger.warning("Telegram credentials not configured. Skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram message sent successfully!")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


# ==============================================================================
# STATE MANAGEMENT
# ==============================================================================


def ensure_state_dir(state_dir: str = "state") -> Path:
    """Ensure state directory exists."""
    path = Path(state_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(state_file: str, state_dir: str = "state") -> dict:
    """Load state from JSON file."""
    path = ensure_state_dir(state_dir) / state_file
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading state file {path}: {e}")
    return {}


def save_state(state: dict, state_file: str, state_dir: str = "state") -> bool:
    """Save state to JSON file."""
    path = ensure_state_dir(state_dir) / state_file
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        return True
    except IOError as e:
        logger.error(f"Error saving state file {path}: {e}")
        return False


# ==============================================================================
# ALERT DEDUPE
# ==============================================================================


def get_alert_key(symbol: str, alert_type: str) -> str:
    """Generate a unique key for an alert."""
    return f"{symbol}:{alert_type}"


def should_send_alert(
    symbol: str,
    alert_type: str,
    state_dir: str = "state",
    dedupe_window_days: int = 3,
) -> bool:
    """
    Check if an alert should be sent (not a duplicate within window).

    Args:
        symbol: Stock symbol
        alert_type: Type of alert (EXIT_RISK, ENTRY_OPPORTUNITY, etc.)
        state_dir: Directory for state files
        dedupe_window_days: Days to suppress duplicate alerts

    Returns:
        True if alert should be sent, False if duplicate
    """
    alerts_state = load_state("alerts.json", state_dir)
    key = get_alert_key(symbol, alert_type)

    if key in alerts_state:
        last_sent_str = alerts_state[key]
        try:
            last_sent = datetime.fromisoformat(last_sent_str)
            window = timedelta(days=dedupe_window_days)
            if datetime.now() - last_sent < window:
                logger.debug(f"Suppressing duplicate alert: {key}")
                return False
        except ValueError:
            pass  # Invalid date, allow sending

    return True


def record_alert_sent(
    symbol: str,
    alert_type: str,
    state_dir: str = "state",
) -> None:
    """Record that an alert was sent."""
    alerts_state = load_state("alerts.json", state_dir)
    key = get_alert_key(symbol, alert_type)
    alerts_state[key] = datetime.now().isoformat()
    save_state(alerts_state, "alerts.json", state_dir)


def cleanup_old_alerts(state_dir: str = "state", max_age_days: int = 30) -> None:
    """Remove old alert records beyond max age."""
    alerts_state = load_state("alerts.json", state_dir)
    cutoff = datetime.now() - timedelta(days=max_age_days)

    cleaned = {}
    for key, date_str in alerts_state.items():
        try:
            sent_date = datetime.fromisoformat(date_str)
            if sent_date > cutoff:
                cleaned[key] = date_str
        except ValueError:
            pass

    if len(cleaned) < len(alerts_state):
        save_state(cleaned, "alerts.json", state_dir)
        logger.info(f"Cleaned up {len(alerts_state) - len(cleaned)} old alert records")


# ==============================================================================
# RECOMMENDATION STATE
# ==============================================================================


def load_last_recommendations(state_dir: str = "state") -> dict:
    """Load last recommended symbols."""
    return load_state("last_recommended.json", state_dir)


def save_last_recommendations(recommendations: dict, state_dir: str = "state") -> bool:
    """Save recommended symbols for next comparison."""
    return save_state(recommendations, "last_recommended.json", state_dir)


def get_new_recommendations(
    current: list[str],
    state_dir: str = "state",
) -> list[str]:
    """Get symbols that are new compared to last run."""
    last = load_last_recommendations(state_dir)
    last_symbols = set(last.get("symbols", []))
    return [s for s in current if s not in last_symbols]


# ==============================================================================
# MESSAGE FORMATTERS
# ==============================================================================


def format_exit_risk_alert(metrics: dict) -> str:
    """Format an exit risk alert message."""
    return (
        f"🚨 *EXIT RISK: {metrics['symbol']}*\n"
        f"Price: ${metrics['price']:.2f}\n"
        f"Reason: {metrics.get('reason', 'N/A')}\n"
        f"Drawdown: {metrics.get('drawdown_pct', 0):.1f}%\n"
        f"50-DMA: ${metrics.get('dma_50', 0):.2f}\n"
        f"100-DMA: ${metrics.get('dma_100', 0):.2f}"
    )


def format_entry_opportunity_alert(metrics: dict) -> str:
    """Format an entry opportunity alert message."""
    return (
        f"🟢 *ENTRY OPPORTUNITY: {metrics['symbol']}*\n"
        f"Price: ${metrics['price']:.2f}\n"
        f"Reason: {metrics.get('reason', 'N/A')}\n"
        f"Pullback: {metrics.get('drawdown_pct', 0):.1f}%\n"
        f"Above 100-DMA: ✅"
    )


def format_bank_opportunity_alert(metrics: dict) -> str:
    """Format a bank opportunity watch alert."""
    return (
        f"🏦 *BANK OPPORTUNITY WATCH: {metrics['symbol']}*\n"
        f"Price: ${metrics['price']:.2f}\n"
        f"Drawdown: {metrics.get('drawdown_pct', 0):.1f}%\n"
        f"Market Stress: Confirmed\n"
        f"Above 200-DMA: {'✅' if metrics.get('above_200dma', False) else '⚠️'}"
    )


def format_weekly_summary(
    all_metrics: list[dict],
    exit_risks: list[dict],
    entry_opps: list[dict],
    bank_opps: list[dict] = None,
) -> str:
    """Format the weekly summary message."""
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Sort by 3M drop descending
    sorted_metrics = sorted(all_metrics, key=lambda x: x.get("drop_3m", 0), reverse=True)

    lines = [
        f"📈 INVESTMENT ALERT",
        f"📅 {date_str}",
        f"📊 {len(entry_opps)} entry | {len(exit_risks)} exit",
    ]

    if bank_opps:
        lines.append(f"🏦 {len(bank_opps)} bank opportunities")

    lines.append("")

    # Each symbol
    for m in sorted_metrics:
        status_icon = {
            "🟢 ENTRY OPP": "🟢",
            "✅ HEALTHY": "✅",
            "👀 WATCH": "👀",
            "⏸️ WAIT": "⏸️",
            "🚨 EXIT RISK": "🚨",
            "🏦 BANK OPP": "🏦",
        }.get(m.get("status", ""), "❓")

        lines.append(f"{status_icon} {m['symbol']} - ${m['price']:.2f}")
        lines.append(
            f"   Drop: 1D={m.get('drop_1d', 0):.1f}% | "
            f"1W={m.get('drop_1w', 0):.1f}% | "
            f"1M={m.get('drop_1m', 0):.1f}% | "
            f"3M={m.get('drop_3m', 0):.1f}%"
        )
        lines.append(
            f"   High: 1D=${m.get('high_1d', 0):.0f} | "
            f"1W=${m.get('high_1w', 0):.0f} | "
            f"1M=${m.get('high_1m', 0):.0f} | "
            f"3M=${m.get('high_3m', 0):.0f}"
        )
        lines.append("")

    lines.append("🟢Entry 🚨Exit ✅Hold ⏸️Wait 👀Watch 🏦Bank")

    return "\n".join(lines)


def format_recommendations_summary(
    recommendations: list[dict],
    new_symbols: list[str],
) -> list[str]:
    """Format discovery summary as separate messages per category (plain text for Telegram).

    Returns:
        List of messages, one per category
    """
    new_set = set(new_symbols)

    # Group by category
    by_category = {}
    for rec in recommendations:
        cat = rec.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(rec)

    category_info = {
        "core_trend": ("📈", "CORE TREND"),
        "emerging_rotation": ("🚀", "EMERGING ROTATION"),
        "stress_opportunities": ("🏦", "STRESS OPPORTUNITIES"),
        "defensive_protection": ("🛡️", "DEFENSIVE PROTECTION"),
    }

    # Define category order
    category_order = ["core_trend", "emerging_rotation", "stress_opportunities", "defensive_protection"]

    messages = []

    # Header message with date
    date_str = datetime.now().strftime("%Y-%m-%d")
    messages.append(f"🔍 DISCOVERY SUMMARY\n📅 {date_str}")

    # One message per category
    for category in category_order:
        if category not in by_category:
            continue

        recs = by_category[category]
        icon, title = category_info.get(category, ("📌", category.upper()))

        # Sort by 3M drop descending
        sorted_recs = sorted(recs, key=lambda x: x.get("drop_3m", 0), reverse=True)

        lines = [f"{icon} {title} ({len(sorted_recs)})", ""]

        for rec in sorted_recs:
            symbol = rec["symbol"]
            price = rec.get("price", 0)
            new_marker = "🆕" if symbol in new_set else ""

            # Status icon based on category/status
            status = rec.get("status", "")
            if "MOMENTUM" in status:
                status_icon = "🚀"
            elif "OPPORTUNITY" in status or "ENTRY" in status:
                status_icon = "🟢"
            elif "DEFENSIVE" in status:
                status_icon = "🛡️"
            else:
                status_icon = "👀"

            lines.append(f"{status_icon} {new_marker}{symbol} - ${price:.2f}")
            lines.append(
                f"   Drop: 1D={rec.get('drop_1d', 0):.1f}% | "
                f"1W={rec.get('drop_1w', 0):.1f}% | "
                f"1M={rec.get('drop_1m', 0):.1f}% | "
                f"3M={rec.get('drop_3m', 0):.1f}%"
            )
            lines.append(
                f"   High: 1D=${rec.get('high_1d', 0):.0f} | "
                f"1W=${rec.get('high_1w', 0):.0f} | "
                f"1M=${rec.get('high_1m', 0):.0f} | "
                f"3M=${rec.get('high_3m', 0):.0f}"
            )
            lines.append("")

        messages.append("\n".join(lines))

    # Footer message with legend
    messages.append("🟢Opportunity 🚀Momentum 🛡️Defensive 👀Watch 🆕New")

    return messages
