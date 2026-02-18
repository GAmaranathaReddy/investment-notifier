#!/usr/bin/env python3
"""
Investment Notifier - Scheduler
================================
Runs discovery at scheduled times and sends Telegram notifications.
Can be run as a daemon or via cron/launchd.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scheduler.log')
    ]
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from lib.alerts import send_telegram, load_state, save_state


def load_config():
    """Load configuration."""
    config_path = BASE_DIR / 'config.json'
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def load_recommendations():
    """Load current recommendations."""
    rec_path = BASE_DIR / 'recommended_symbols.json'
    if rec_path.exists():
        with open(rec_path) as f:
            return json.load(f)
    return {}


def run_discovery():
    """Run the discovery script."""
    import subprocess

    venv_python = BASE_DIR / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        venv_python = sys.executable

    script_path = BASE_DIR / 'discover_symbols.py'

    try:
        result = subprocess.run(
            [str(venv_python), str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=180
        )
        if result.returncode == 0:
            logger.info("Discovery completed successfully")
            return True, result.stdout
        else:
            logger.error(f"Discovery failed: {result.stderr}")
            return False, result.stderr
    except Exception as e:
        logger.error(f"Error running discovery: {e}")
        return False, str(e)


def format_telegram_message(recommendations: dict, prev_recommendations: dict = None) -> str:
    """Format recommendations as a Telegram message."""
    if not recommendations:
        return None

    symbols = recommendations.get('symbols', [])
    if not symbols:
        return None

    # Categorize by status
    momentum = [s for s in symbols if s.get('status') == 'momentum']
    watch = [s for s in symbols if s.get('status') == 'watch']
    available = [s for s in symbols if s.get('status') == 'available']
    below_ma = [s for s in symbols if 'below_ma' in s.get('reason', '').lower() or 'BELOW MA' in s.get('reason', '')]

    # Check for new symbols
    prev_symbols = set()
    if prev_recommendations and 'symbols' in prev_recommendations:
        prev_symbols = {s['symbol'] for s in prev_recommendations['symbols']}

    current_symbols = {s['symbol'] for s in symbols}
    new_symbols = current_symbols - prev_symbols

    # Build message
    lines = []
    lines.append("📊 *Investment Alert*")
    lines.append(f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append("")

    # New symbols alert
    if new_symbols:
        lines.append(f"🆕 *New Symbols Detected:* {', '.join(sorted(new_symbols))}")
        lines.append("")

    # Summary
    lines.append("*Summary:*")
    if momentum:
        lines.append(f"🟢 BUY NOW: {len(momentum)} symbols")
    if watch:
        lines.append(f"🟡 WATCH: {len(watch)} symbols")
    if available:
        lines.append(f"🔵 AVAILABLE: {len(available)} symbols")
    if below_ma:
        lines.append(f"⚪ BELOW MA: {len(below_ma)} symbols")

    lines.append("")

    # Top momentum picks (limit to top 5)
    if momentum:
        lines.append("*🚀 Top BUY Picks:*")
        for s in momentum[:5]:
            symbol = s['symbol']
            price = s.get('current_price', 0)
            rs = s.get('rs_score', 0)
            drawdown = s.get('drawdown_from_high', 0) * 100
            lines.append(f"• *{symbol}*: ${price:.2f} | RS: {rs:.1f} | DD: {drawdown:.1f}%")
        lines.append("")

    # Watch list (limit to top 5)
    if watch and not any('below_ma' in s.get('reason', '').lower() for s in watch[:5]):
        watch_clean = [s for s in watch if 'below_ma' not in s.get('reason', '').lower() and 'BELOW MA' not in s.get('reason', '')]
        if watch_clean:
            lines.append("*👀 Watch List:*")
            for s in watch_clean[:5]:
                symbol = s['symbol']
                price = s.get('current_price', 0)
                lines.append(f"• {symbol}: ${price:.2f}")
            lines.append("")

    # Below MA alerts (important for watchlist)
    if below_ma:
        lines.append("*⚪ Below 50 DMA (Watchlist):*")
        for s in below_ma[:5]:
            symbol = s['symbol']
            price = s.get('current_price', 0)
            dma_50 = s.get('dma_50', 0)
            gap = ((dma_50 - price) / price * 100) if price > 0 else 0
            lines.append(f"• {symbol}: ${price:.2f} ({gap:.1f}% below DMA)")
        lines.append("")

    lines.append("_View dashboard for full details_")

    return '\n'.join(lines)


def send_daily_alert():
    """Send daily investment alert via Telegram."""
    config = load_config()
    telegram_config = config.get('notifications', {}).get('telegram', {})

    if not telegram_config.get('enabled', False):
        logger.info("Telegram notifications disabled")
        return False

    # Load previous state to detect changes
    prev_state = load_state('last_notification.json')
    prev_recommendations = prev_state.get('recommendations', {})

    # Run discovery first
    success, output = run_discovery()
    if not success:
        send_telegram(f"⚠️ Discovery failed:\n{output[:500]}", parse_mode="Markdown")
        return False

    # Load fresh recommendations
    recommendations = load_recommendations()

    # Format and send message
    message = format_telegram_message(recommendations, prev_recommendations)

    if message:
        result = send_telegram(message, parse_mode="Markdown")
        if result:
            # Save state
            save_state({
                'recommendations': recommendations,
                'last_sent': datetime.now().isoformat()
            }, 'last_notification.json')
            logger.info("Telegram alert sent successfully")
            return True
        else:
            logger.error("Failed to send Telegram alert")
            return False
    else:
        logger.info("No recommendations to send")
        return False


def should_run_now(schedule_config: dict) -> bool:
    """Check if we should run based on schedule."""
    now = datetime.now()

    # Check day of week (0=Monday, 6=Sunday)
    run_days = schedule_config.get('days', [0, 1, 2, 3, 4])  # Default: weekdays
    if now.weekday() not in run_days:
        return False

    # Check time windows
    run_times = schedule_config.get('times', ['09:00', '16:00'])  # Default: market open/close
    current_time = now.strftime('%H:%M')

    for scheduled_time in run_times:
        # Allow 5-minute window
        scheduled = datetime.strptime(scheduled_time, '%H:%M')
        scheduled = scheduled.replace(year=now.year, month=now.month, day=now.day)

        diff = abs((now - scheduled).total_seconds())
        if diff < 300:  # Within 5 minutes
            return True

    return False


def run_daemon(check_interval: int = 60):
    """Run as a daemon, checking schedule periodically."""
    logger.info("Starting scheduler daemon...")

    config = load_config()
    schedule_config = config.get('scheduler', {})

    last_run_date = None

    while True:
        try:
            now = datetime.now()
            today = now.date()

            # Check if we should run
            if should_run_now(schedule_config) and last_run_date != today:
                logger.info("Scheduled run triggered")
                send_daily_alert()
                last_run_date = today

            time.sleep(check_interval)

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            time.sleep(check_interval)


def run_once():
    """Run discovery and send alert once."""
    logger.info("Running single discovery and alert...")
    return send_daily_alert()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Investment Notifier Scheduler')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--test', action='store_true', help='Test Telegram connection')
    parser.add_argument('--interval', type=int, default=60, help='Check interval in seconds (daemon mode)')

    args = parser.parse_args()

    if args.test:
        # Test Telegram connection
        result = send_telegram("🔔 Test message from Investment Notifier", parse_mode="Markdown")
        if result:
            print("✅ Telegram test successful!")
        else:
            print("❌ Telegram test failed. Check your credentials.")
        sys.exit(0 if result else 1)

    if args.daemon:
        run_daemon(args.interval)
    elif args.once:
        success = run_once()
        sys.exit(0 if success else 1)
    else:
        # Default: run once
        success = run_once()
        sys.exit(0 if success else 1)
