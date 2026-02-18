#!/usr/bin/env python3
"""
Investment Notifier - Streamlit Web UI
A Streamlit-based UI for viewing and editing symbol configurations.
Designed for deployment on Streamlit Cloud.
"""

import streamlit as st
import json
import os
import subprocess
import sys
import base64
import pandas as pd
from datetime import datetime
import requests

# =============================================================================
# Configuration
# =============================================================================

# Use environment variable for base directory (for Streamlit Cloud compatibility)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
STOCKS_FILE = os.path.join(BASE_DIR, 'stocks.json')
RECOMMENDED_FILE = os.path.join(BASE_DIR, 'recommended_symbols.json')

# Page configuration
st.set_page_config(
    page_title="Investment Notifier - Symbol Manager",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =============================================================================
# GitHub Integration for Cloud Persistence
# =============================================================================

def get_github_credentials():
    """Get GitHub credentials from st.secrets or environment."""
    try:
        token = st.secrets.get("GITHUB_TOKEN", os.environ.get("GITHUB_TOKEN"))
        repo = st.secrets.get("GITHUB_REPO", os.environ.get("GITHUB_REPO"))
        branch = st.secrets.get("GITHUB_BRANCH", os.environ.get("GITHUB_BRANCH", "main"))
    except:
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPO")
        branch = os.environ.get("GITHUB_BRANCH", "main")
    return token, repo, branch


def github_get_file(filepath: str) -> tuple:
    """Get file content and SHA from GitHub."""
    token, repo, branch = get_github_credentials()
    if not token or not repo:
        return None, None

    filename = os.path.basename(filepath)
    url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    params = {"ref": branch}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
        return None, None
    except Exception as e:
        return None, None


def github_update_file(filepath: str, content: dict, message: str = None) -> bool:
    """Update file in GitHub repository."""
    token, repo, branch = get_github_credentials()
    if not token or not repo:
        return False

    filename = os.path.basename(filepath)

    # Get current SHA
    _, sha = github_get_file(filepath)

    url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Encode content
    content_str = json.dumps(content, indent=2)
    content_b64 = base64.b64encode(content_str.encode()).decode()

    payload = {
        "message": message or f"Update {filename} via Streamlit UI",
        "content": content_b64,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        return False


def is_github_enabled() -> bool:
    """Check if GitHub integration is configured."""
    token, repo, _ = get_github_credentials()
    return bool(token and repo)


def sync_to_github(filepath: str, content: dict, message: str = None) -> bool:
    """Save locally and sync to GitHub if enabled."""
    # Always save locally first
    try:
        with open(filepath, 'w') as f:
            json.dump(content, f, indent=2)
    except Exception as e:
        st.error(f"Local save failed: {e}")
        return False

    # Sync to GitHub if configured
    if is_github_enabled():
        if github_update_file(filepath, content, message):
            return True
        else:
            st.warning("⚠️ Saved locally but GitHub sync failed")
            return True  # Local save succeeded
    return True


# =============================================================================
# Helper Functions
# =============================================================================

def load_json(filepath):
    """Load JSON file safely."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"Error loading {filepath}: {e}")
        return None


def save_json(filepath, data):
    """Save data to JSON file with pretty formatting."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving {filepath}: {e}")
        return False


def get_config():
    """Load main config file."""
    return load_json(CONFIG_FILE) or {}


def get_stocks():
    """Load stocks watchlist."""
    return load_json(STOCKS_FILE) or []


def save_stocks(stocks):
    """Save stocks watchlist and sync to GitHub."""
    return sync_to_github(STOCKS_FILE, stocks, "Update watchlist via UI")


def save_config(config):
    """Save config and sync to GitHub."""
    return sync_to_github(CONFIG_FILE, config, "Update config via UI")


def get_recommended():
    """Load recommended symbols from local file."""
    return load_json(RECOMMENDED_FILE) or {}


def get_python_executable():
    """Get the correct Python executable for the environment."""
    # Try venv first (local development)
    venv_python = os.path.join(BASE_DIR, '.venv', 'bin', 'python')
    if os.path.exists(venv_python):
        return venv_python
    # Fallback to current Python (Streamlit Cloud)
    return sys.executable


def get_telegram_credentials():
    """Get Telegram credentials from st.secrets or environment."""
    # Try st.secrets first (Streamlit Cloud)
    try:
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN"))
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID"))
    except:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return bot_token, chat_id


def run_discovery_script():
    """Run the discover_symbols.py script to refresh recommendations."""
    script_path = os.path.join(BASE_DIR, 'discover_symbols.py')
    if os.path.exists(script_path):
        try:
            python_exe = get_python_executable()

            result = subprocess.run(
                [python_exe, script_path],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                return True, "Data refreshed successfully!"
            else:
                return False, f"Error: {result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "Timeout: Script took too long to run"
        except Exception as e:
            return False, f"Error running script: {str(e)}"
    else:
        return False, "discover_symbols.py not found"


# =============================================================================
# Custom CSS
# =============================================================================

st.markdown("""
<style>
    .symbol-tag {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        margin: 2px;
        font-size: 14px;
        font-weight: 500;
    }

    /* Decision Dashboard Styles */
    .action-card {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
        border-radius: 20px;
        padding: 25px;
        margin: 10px 0;
        border-left: 5px solid;
        position: relative;
        overflow: hidden;
    }
    .action-card::before {
        content: '';
        position: absolute;
        top: 0;
        right: 0;
        width: 100px;
        height: 100px;
        opacity: 0.1;
        border-radius: 50%;
        transform: translate(30%, -30%);
    }
    .action-buy { border-color: #00d26a; }
    .action-buy::before { background: #00d26a; }
    .action-watch { border-color: #ffc107; }
    .action-watch::before { background: #ffc107; }
    .action-hold { border-color: #4cc9f0; }
    .action-hold::before { background: #4cc9f0; }

    .action-label {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .label-buy { color: #00d26a; }
    .label-watch { color: #ffc107; }
    .label-hold { color: #4cc9f0; }

    .symbol-big {
        font-size: 32px;
        font-weight: 800;
        color: #ffffff;
        margin: 5px 0;
    }
    .price-big {
        font-size: 24px;
        font-weight: 700;
        color: #00d26a;
    }
    .metrics-row {
        display: flex;
        gap: 15px;
        margin-top: 12px;
        flex-wrap: wrap;
    }
    .metric-box {
        background: rgba(255,255,255,0.05);
        padding: 8px 12px;
        border-radius: 8px;
        text-align: center;
    }
    .metric-value {
        font-size: 16px;
        font-weight: 700;
        color: #fff;
    }
    .metric-label {
        font-size: 10px;
        color: #888;
        text-transform: uppercase;
    }

    /* Signal Strength Bar */
    .signal-bar {
        height: 8px;
        background: rgba(255,255,255,0.1);
        border-radius: 4px;
        margin-top: 15px;
        overflow: hidden;
    }
    .signal-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.5s ease;
    }
    .signal-strong { background: linear-gradient(90deg, #00d26a, #00ff88); }
    .signal-medium { background: linear-gradient(90deg, #ffc107, #ffda44); }
    .signal-weak { background: linear-gradient(90deg, #4cc9f0, #88ddff); }

    /* Hero Number */
    .hero-section {
        text-align: center;
        padding: 30px 0;
    }
    .hero-number {
        font-size: 80px;
        font-weight: 900;
        background: linear-gradient(135deg, #00d26a 0%, #00ff88 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1;
    }
    .hero-label {
        font-size: 18px;
        color: #888;
        margin-top: 10px;
    }

    /* Quick Action Buttons */
    .quick-action {
        display: inline-block;
        padding: 8px 20px;
        border-radius: 25px;
        font-weight: 600;
        font-size: 13px;
        margin: 5px;
        cursor: pointer;
    }
    .qa-primary { background: #00d26a; color: white; }
    .qa-secondary { background: rgba(255,255,255,0.1); color: white; border: 1px solid #333; }

    /* Sector Pills */
    .sector-pill {
        display: inline-block;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        margin: 3px;
        background: rgba(255,255,255,0.08);
        color: #ccc;
    }
    .sector-hot {
        background: linear-gradient(135deg, #ff6b35 0%, #ff8c42 100%);
        color: white;
    }

    .basket-name { color: #1f77b4; font-weight: 600; }
    .stButton button { border-radius: 20px; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Sidebar Navigation
# =============================================================================

st.sidebar.title("📈 Investment Notifier")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["🏠 Dashboard", "📊 Watchlist", "📁 Categories", "⭐ Recommended", "⚙️ Settings"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# =============================================================================
# Dashboard Page
# =============================================================================

if page == "🏠 Dashboard":
    # Refresh button at the top
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.title("🏠 Investment Dashboard")
    with col_refresh:
        if st.button("🔄 Refresh Data", key="refresh_dashboard", use_container_width=True):
            with st.spinner("Running discovery script..."):
                success, message = run_discovery_script()
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    # Load data
    config = get_config()
    stocks = get_stocks()
    recommended = get_recommended()
    categories = config.get('categories', {})
    recommendations_list = recommended.get('recommendations', [])

    # Categorize by action
    buy_now = sorted([r for r in recommendations_list if r.get('status') == 'momentum'],
                     key=lambda x: x.get('score', 0), reverse=True)
    watch_list = sorted([r for r in recommendations_list if r.get('status') == 'watch'],
                        key=lambda x: x.get('score', 0), reverse=True)
    available_list = sorted([r for r in recommendations_list if r.get('status') == 'available'],
                            key=lambda x: x.get('score', 0), reverse=True)
    below_ma_list = sorted([r for r in recommendations_list if r.get('status') == 'below_ma'],
                           key=lambda x: x.get('score', 0), reverse=True)

    # Get top pick
    top_pick = buy_now[0] if buy_now else None

    # ==========================================================================
    # HERO: Today's Top Pick
    # ==========================================================================
    if top_pick:
        st.markdown("### 🎯 TODAY'S TOP PICK")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            symbol = top_pick.get('symbol', '')
            price = top_pick.get('price', 0)
            score = top_pick.get('score', 0)
            slope = top_pick.get('slope_pct', 0)
            rs = top_pick.get('relative_strength_pct', 0)
            drawdown = top_pick.get('drawdown_pct', 0)
            dma_50 = top_pick.get('dma_50', 0)
            dma_100 = top_pick.get('dma_100', 0)
            high_1d = top_pick.get('high_1d', 0)
            high_1w = top_pick.get('high_1w', 0)
            high_1m = top_pick.get('high_1m', 0)
            high_3m = top_pick.get('high_3m', 0)
            drop_1d = top_pick.get('drop_1d', 0)
            drop_1w = top_pick.get('drop_1w', 0)
            drop_1m = top_pick.get('drop_1m', 0)
            drop_3m = top_pick.get('drop_3m', 0)
            category = top_pick.get('category', '').replace('_', ' ').title()
            basket = top_pick.get('basket', '').replace('_', ' ').title() if top_pick.get('basket') else ''
            reason = top_pick.get('reason', '')
            signal_pct = int(min(score * 100, 100))

            # Use native Streamlit container
            with st.container(border=True):
                st.markdown(f"## 🚀 STRONG BUY: **{symbol}**")
                st.caption(f"{category}" + (f" • {basket}" if basket else ""))

                # Price prominent
                st.markdown(f"### 💰 ${price:.2f}")

                # Key metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Score", f"{score:.2f}")
                m2.metric("Slope", f"+{slope:.1f}%")
                m3.metric("Rel Strength", f"{rs:.1f}%")
                m4.metric("Drawdown", f"-{drawdown:.1f}%")

                # Moving averages
                st.markdown("**📊 Moving Averages**")
                ma1, ma2 = st.columns(2)
                ma1.metric("50 DMA", f"${dma_50:.2f}")
                ma2.metric("100 DMA", f"${dma_100:.2f}")

                # Recent highs with all timeframes
                st.markdown("**📈 Recent Highs & Drops**")
                h1, h2, h3, h4 = st.columns(4)
                h1.metric("1D High", f"${high_1d:.2f}", delta=f"-{drop_1d:.2f}%", delta_color="off")
                h2.metric("1W High", f"${high_1w:.2f}", delta=f"-{drop_1w:.2f}%", delta_color="off")
                h3.metric("1M High", f"${high_1m:.2f}", delta=f"-{drop_1m:.2f}%", delta_color="off")
                h4.metric("3M High", f"${high_3m:.2f}", delta=f"-{drop_3m:.2f}%", delta_color="off")

                # Signal strength bar using progress
                st.progress(signal_pct / 100, text=f"Signal Strength: {signal_pct}%")

                # Reason
                if reason:
                    st.info(f"💡 {reason}")

        st.markdown("")

    # ==========================================================================
    # BUY NOW Section (Momentum)
    # ==========================================================================
    remaining_buys = buy_now[1:5] if len(buy_now) > 1 else []
    if remaining_buys:
        st.markdown("### 🟢 BUY NOW")
        st.caption("Strong momentum - Consider entering positions")

        cols = st.columns(len(remaining_buys))
        for idx, rec in enumerate(remaining_buys):
            with cols[idx]:
                symbol = rec.get('symbol', '')
                price = rec.get('price', 0)
                score = rec.get('score', 0)
                slope = rec.get('slope_pct', 0)
                rs = rec.get('relative_strength_pct', 0)
                drawdown = rec.get('drawdown_pct', 0)
                dma_50 = rec.get('dma_50', 0)
                high_1w = rec.get('high_1w', 0)
                high_1m = rec.get('high_1m', 0)
                high_3m = rec.get('high_3m', 0)
                category = rec.get('category', '').replace('_', ' ').title()
                basket = rec.get('basket', '').replace('_', ' ').title() if rec.get('basket') else ''
                signal_pct = int(min(score * 100, 100))

                with st.container(border=True):
                    st.markdown(f"**🟢 {symbol}**")
                    st.caption(f"{category}" + (f" • {basket}" if basket else ""))

                    # Price and score
                    c1, c2 = st.columns(2)
                    c1.metric("Price", f"${price:.2f}")
                    c2.metric("Score", f"{score:.2f}", delta=f"+{slope:.1f}%")

                    # Compact info lines
                    st.caption(f"50 DMA: ${dma_50:.2f}")
                    st.caption(f"1W: ${high_1w:.2f} | 1M: ${high_1m:.2f} | 3M: ${high_3m:.2f}")
                    st.caption(f"RS: {rs:.1f}% | Drawdown: {drawdown:.1f}%")
                    st.progress(signal_pct / 100)

        st.markdown("")

    # ==========================================================================
    # WATCH Section
    # ==========================================================================
    watch_display = watch_list[:4] if watch_list else []
    if watch_display:
        st.markdown("### 🟡 WATCH")
        st.caption("Wait for better entry - Monitor closely")

        cols = st.columns(len(watch_display))
        for idx, rec in enumerate(watch_display):
            with cols[idx]:
                symbol = rec.get('symbol', '')
                price = rec.get('price', 0)
                score = rec.get('score', 0)
                slope = rec.get('slope_pct', 0)
                rs = rec.get('relative_strength_pct', 0)
                drawdown = rec.get('drawdown_pct', 0)
                dma_50 = rec.get('dma_50', 0)
                high_1w = rec.get('high_1w', 0)
                high_1m = rec.get('high_1m', 0)
                high_3m = rec.get('high_3m', 0)
                category = rec.get('category', '').replace('_', ' ').title()
                basket = rec.get('basket', '').replace('_', ' ').title() if rec.get('basket') else ''
                reason = rec.get('reason', '')
                signal_pct = int(min(score * 100, 100))

                with st.container(border=True):
                    st.markdown(f"**🟡 {symbol}**")
                    st.caption(f"{category}" + (f" • {basket}" if basket else ""))

                    # Price and score
                    c1, c2 = st.columns(2)
                    c1.metric("Price", f"${price:.2f}")
                    c2.metric("Score", f"{score:.2f}", delta=f"{slope:+.1f}%")

                    # Compact info lines
                    st.caption(f"50 DMA: ${dma_50:.2f}")
                    st.caption(f"1W: ${high_1w:.2f} | 1M: ${high_1m:.2f} | 3M: ${high_3m:.2f}")
                    st.caption(f"📉 Pullback: {drawdown:.1f}% | RS: {rs:.1f}%")
                    st.progress(signal_pct / 100)

                    if reason:
                        st.caption(f"💡 {reason}")

        st.markdown("")

    # ==========================================================================
    # AVAILABLE Section (Other recommendations)
    # ==========================================================================
    available_list = sorted([r for r in recommendations_list if r.get('status') == 'available'],
                            key=lambda x: x.get('score', 0), reverse=True)

    if available_list:
        st.markdown("### 🔵 AVAILABLE")
        st.caption("Meeting criteria - Ready for analysis")

        # Show in rows of 4
        for i in range(0, len(available_list), 4):
            row_items = available_list[i:i+4]
            cols = st.columns(len(row_items))
            for idx, rec in enumerate(row_items):
                with cols[idx]:
                    symbol = rec.get('symbol', '')
                    price = rec.get('price', 0)
                    score = rec.get('score', 0)
                    slope = rec.get('slope_pct', 0)
                    rs = rec.get('relative_strength_pct', 0)
                    drawdown = rec.get('drawdown_pct', 0)
                    dma_50 = rec.get('dma_50', 0)
                    high_1w = rec.get('high_1w', 0)
                    high_1m = rec.get('high_1m', 0)
                    high_3m = rec.get('high_3m', 0)
                    category = rec.get('category', '').replace('_', ' ').title()
                    basket = rec.get('basket', '').replace('_', ' ').title() if rec.get('basket') else ''
                    reason = rec.get('reason', '')
                    signal_pct = int(min(score * 100, 100))

                    with st.container(border=True):
                        st.markdown(f"**🔵 {symbol}**")
                        st.caption(f"{category}" + (f" • {basket}" if basket else ""))

                        # Price and score
                        c1, c2 = st.columns(2)
                        c1.metric("Price", f"${price:.2f}")
                        c2.metric("Score", f"{score:.2f}", delta=f"{slope:+.1f}%")

                        # Compact info lines
                        st.caption(f"50 DMA: ${dma_50:.2f}")
                        st.caption(f"1W: ${high_1w:.2f} | 1M: ${high_1m:.2f} | 3M: ${high_3m:.2f}")
                        st.caption(f"📉 Pullback: {drawdown:.1f}% | RS: {rs:.1f}%")
                        st.progress(signal_pct / 100)

                        if reason:
                            st.caption(f"💡 {reason}")

        st.markdown("")

    # ==========================================================================
    # BELOW MA Section (Watchlist symbols below moving average)
    # ==========================================================================
    if below_ma_list:
        st.markdown("### ⚪ BELOW MA (Watchlist)")
        st.caption("Your watchlist symbols currently below 50-day moving average")

        # Show in rows of 4
        for i in range(0, len(below_ma_list), 4):
            row_items = below_ma_list[i:i+4]
            cols = st.columns(len(row_items))
            for idx, rec in enumerate(row_items):
                with cols[idx]:
                    symbol = rec.get('symbol', '')
                    price = rec.get('price', 0)
                    score = rec.get('score', 0)
                    slope = rec.get('slope_pct', 0)
                    rs = rec.get('relative_strength_pct', 0)
                    drawdown = rec.get('drawdown_pct', 0)
                    dma_50 = rec.get('dma_50', 0)
                    high_1w = rec.get('high_1w', 0)
                    high_1m = rec.get('high_1m', 0)
                    high_3m = rec.get('high_3m', 0)
                    category = rec.get('category', '').replace('_', ' ').title()
                    reason = rec.get('reason', '')
                    signal_pct = int(min(score * 100, 100))

                    with st.container(border=True):
                        st.markdown(f"**⚪ {symbol}**")
                        st.caption(f"{category}")

                        # Price and score
                        c1, c2 = st.columns(2)
                        c1.metric("Price", f"${price:.2f}")
                        c2.metric("50 DMA", f"${dma_50:.2f}")

                        # Compact info lines
                        st.caption(f"1W: ${high_1w:.2f} | 1M: ${high_1m:.2f} | 3M: ${high_3m:.2f}")
                        st.caption(f"📉 Drawdown: {drawdown:.1f}% | RS: {rs:.1f}%")
                        st.progress(signal_pct / 100)

                        if reason:
                            st.caption(f"💡 {reason}")

        st.markdown("")

    # ==========================================================================
    # Hot Sectors Quick View
    # ==========================================================================
    by_category = recommended.get('by_category', {})
    if by_category:
        st.markdown("### 🔥 Hot Sectors")

        # Filter to only include categories with list values (strings)
        valid_cats = {k: v for k, v in by_category.items() if isinstance(v, list)}

        if valid_cats:
            # Sort categories by number of symbols
            sorted_cats = sorted(valid_cats.items(), key=lambda x: len(x[1]), reverse=True)

            # Use columns for sectors
            sector_cols = st.columns(len(sorted_cats))
            for idx, (cat_name, symbols) in enumerate(sorted_cats):
                with sector_cols[idx]:
                    sym_count = len(symbols)
                    cat_display = cat_name.replace("_", " ").title()
                    if sym_count >= 3:
                        st.success(f"🔥 {cat_display}: {sym_count}")
                    else:
                        st.info(f"{cat_display}: {sym_count}")
        st.markdown("")

    # ==========================================================================
    # Quick Stats Footer
    # ==========================================================================
    st.markdown("---")

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("🟢 Buy", len(buy_now))
    with col2:
        st.metric("🟡 Watch", len(watch_list))
    with col3:
        st.metric("🔵 Available", len(available_list))
    with col4:
        st.metric("⚪ Below MA", len(below_ma_list))
    with col5:
        st.metric("📊 Total", len(recommendations_list))
    with col6:
        date_str = recommended.get('generated_at', 'N/A')[:10] if recommended.get('generated_at') else 'N/A'
        st.metric("📅 Updated", date_str)


# =============================================================================
# Watchlist Page
# =============================================================================

elif page == "📊 Watchlist":
    # Header with refresh button
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.title("📊 Watchlist Management")
    with col_refresh:
        if st.button("🔄 Refresh Data", key="refresh_watchlist", use_container_width=True):
            with st.spinner("Running discovery script..."):
                success, message = run_discovery_script()
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    st.markdown("Manage symbols in your `stocks.json` watchlist.")

    stocks = get_stocks()

    # Add new symbol
    st.subheader("Add Symbol")
    col1, col2 = st.columns([3, 1])

    with col1:
        new_symbol = st.text_input(
            "Symbol",
            placeholder="Enter symbol (e.g., AAPL)",
            label_visibility="collapsed",
            key="watchlist_new_symbol"
        )

    with col2:
        if st.button("➕ Add", key="add_watchlist", use_container_width=True):
            if new_symbol:
                symbol = new_symbol.upper().strip()
                if symbol in stocks:
                    st.warning(f"{symbol} already exists in watchlist")
                else:
                    stocks.append(symbol)
                    stocks.sort()
                    if save_stocks(stocks):
                        msg = f"Added {symbol}"
                        if is_github_enabled():
                            msg += " (synced to GitHub)"
                        st.success(msg)
                        st.rerun()
            else:
                st.warning("Please enter a symbol")

    st.markdown("---")

    # Display current symbols
    st.subheader(f"Current Symbols ({len(stocks)})")

    if stocks:
        # Create a grid of symbols with delete buttons
        cols = st.columns(5)
        for idx, symbol in enumerate(sorted(stocks)):
            with cols[idx % 5]:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f'<span class="symbol-tag">{symbol}</span>', unsafe_allow_html=True)
                with col_b:
                    if st.button("🗑️", key=f"del_stock_{symbol}", help=f"Remove {symbol}"):
                        stocks.remove(symbol)
                        if save_stocks(stocks):
                            msg = f"Removed {symbol}"
                            if is_github_enabled():
                                msg += " (synced to GitHub)"
                            st.success(msg)
                            st.rerun()
    else:
        st.info("No symbols in watchlist. Add some above!")

    st.markdown("---")

    # Bulk operations
    st.subheader("Bulk Operations")

    col1, col2 = st.columns(2)

    with col1:
        bulk_add = st.text_area(
            "Add multiple symbols (comma or newline separated)",
            placeholder="AAPL, MSFT, GOOGL\nAMZN\nTSLA",
            height=100,
            key="bulk_add_watchlist"
        )
        if st.button("➕ Add All", key="bulk_add_btn"):
            if bulk_add:
                # Parse symbols
                symbols = [s.strip().upper() for s in bulk_add.replace('\n', ',').split(',') if s.strip()]
                added = []
                for symbol in symbols:
                    if symbol and symbol not in stocks:
                        stocks.append(symbol)
                        added.append(symbol)
                if added:
                    stocks.sort()
                    if save_stocks(stocks):
                        st.success(f"Added {len(added)} symbols: {', '.join(added)}")
                        st.rerun()
                else:
                    st.info("No new symbols to add")

    with col2:
        st.markdown("**Export/Import**")
        st.download_button(
            "📥 Download stocks.json",
            data=json.dumps(stocks, indent=2),
            file_name="stocks.json",
            mime="application/json"
        )


# =============================================================================
# Categories Page
# =============================================================================

elif page == "📁 Categories":
    # Header with refresh button
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.title("📁 Category Management")
    with col_refresh:
        if st.button("🔄 Refresh Data", key="refresh_categories", use_container_width=True):
            with st.spinner("Running discovery script..."):
                success, message = run_discovery_script()
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    st.markdown("Manage symbols in your `config.json` categories.")

    config = get_config()
    categories = config.get('categories', {})

    if not categories:
        st.warning("No categories found in config.json")
    else:
        # Category selector
        category_names = list(categories.keys())
        selected_category = st.selectbox(
            "Select Category",
            category_names,
            format_func=lambda x: f"{x} - {categories[x].get('description', '')[:50]}..."
        )

        if selected_category:
            cat_data = categories[selected_category]

            st.markdown("---")

            # Category description
            st.markdown(f"**Description:** {cat_data.get('description', 'No description')}")

            # Direct symbols
            if 'symbols' in cat_data:
                st.subheader(f"Direct Symbols ({len(cat_data['symbols'])})")

                # Add symbol
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_cat_symbol = st.text_input(
                        "Add symbol",
                        placeholder="Enter symbol",
                        label_visibility="collapsed",
                        key=f"new_symbol_{selected_category}"
                    )
                with col2:
                    if st.button("➕ Add", key=f"add_cat_{selected_category}"):
                        if new_cat_symbol:
                            symbol = new_cat_symbol.upper().strip()
                            if symbol in cat_data['symbols']:
                                st.warning(f"{symbol} already exists")
                            else:
                                cat_data['symbols'].append(symbol)
                                cat_data['symbols'].sort()
                                if save_config(config):
                                    st.success(f"Added {symbol}")
                                    st.rerun()

                # Display symbols
                if cat_data['symbols']:
                    cols = st.columns(6)
                    for idx, symbol in enumerate(sorted(cat_data['symbols'])):
                        with cols[idx % 6]:
                            col_a, col_b = st.columns([3, 1])
                            with col_a:
                                st.markdown(f'<span class="symbol-tag">{symbol}</span>', unsafe_allow_html=True)
                            with col_b:
                                if st.button("🗑️", key=f"del_cat_{selected_category}_{symbol}"):
                                    cat_data['symbols'].remove(symbol)
                                    if save_config(config):
                                        st.rerun()
                else:
                    st.info("No direct symbols")

            # Baskets
            if 'baskets' in cat_data and cat_data['baskets']:
                st.markdown("---")
                st.subheader("Baskets")

                for basket_name, basket_symbols in cat_data['baskets'].items():
                    with st.expander(f"🧺 {basket_name} ({len(basket_symbols)} symbols)", expanded=False):
                        # Add to basket
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            new_basket_symbol = st.text_input(
                                "Add symbol",
                                placeholder="Enter symbol",
                                label_visibility="collapsed",
                                key=f"new_basket_{selected_category}_{basket_name}"
                            )
                        with col2:
                            if st.button("➕ Add", key=f"add_basket_{selected_category}_{basket_name}"):
                                if new_basket_symbol:
                                    symbol = new_basket_symbol.upper().strip()
                                    if symbol in basket_symbols:
                                        st.warning(f"{symbol} already exists")
                                    else:
                                        basket_symbols.append(symbol)
                                        basket_symbols.sort()
                                        if save_config(config):
                                            st.success(f"Added {symbol}")
                                            st.rerun()

                        # Display basket symbols
                        if basket_symbols:
                            cols = st.columns(5)
                            for idx, symbol in enumerate(sorted(basket_symbols)):
                                with cols[idx % 5]:
                                    col_a, col_b = st.columns([3, 1])
                                    with col_a:
                                        st.markdown(f'<span class="symbol-tag">{symbol}</span>', unsafe_allow_html=True)
                                    with col_b:
                                        if st.button("🗑️", key=f"del_basket_{selected_category}_{basket_name}_{symbol}"):
                                            basket_symbols.remove(symbol)
                                            if save_config(config):
                                                st.rerun()
                        else:
                            st.info("No symbols in this basket")


# =============================================================================
# Recommended Page
# =============================================================================

elif page == "⭐ Recommended":
    # Header with refresh button
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.title("⭐ Recommended Symbols")
    with col_refresh:
        if st.button("🔄 Refresh Data", key="refresh_recommended", use_container_width=True):
            with st.spinner("Running discovery script..."):
                success, message = run_discovery_script()
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    st.markdown("View recommended symbols from `recommended_symbols.json`.")

    recommended = get_recommended()

    if not recommended:
        st.info("No recommended symbols found. Run the discovery script to generate recommendations.")
    else:
        # Display metadata
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Recommendations", recommended.get('total_count', 0))
        with col2:
            generated_at = recommended.get('generated_at', 'Unknown')
            if generated_at and generated_at != 'Unknown':
                st.metric("Generated At", generated_at[:10])
        with col3:
            categories_count = len(recommended.get('by_category', {}))
            st.metric("Categories", categories_count)

        st.markdown("---")

        # Summary by category
        st.subheader("📊 Summary by Category")
        by_category = recommended.get('by_category', {})
        if by_category:
            # Filter to only valid list categories
            valid_cats = {k: v for k, v in by_category.items() if isinstance(v, list)}
            if valid_cats:
                cols = st.columns(len(valid_cats))
                for idx, (cat_name, symbols) in enumerate(valid_cats.items()):
                    with cols[idx]:
                        st.markdown(f"**{cat_name.replace('_', ' ').title()}**")
                        # Ensure symbols are strings
                        str_symbols = [str(s) for s in symbols if isinstance(s, str)]
                        symbols_html = " ".join([f'<span class="symbol-tag">{s}</span>' for s in str_symbols])
                        st.markdown(symbols_html, unsafe_allow_html=True)

        st.markdown("---")

        # Detailed recommendations table
        st.subheader("📋 Detailed Recommendations")

        recommendations = recommended.get('recommendations', [])
        if recommendations:
            # Filter by category
            all_categories = list(set(rec.get('category', 'Unknown') for rec in recommendations))
            selected_cat = st.selectbox(
                "Filter by Category",
                ["All"] + sorted(all_categories),
                key="rec_category_filter"
            )

            # Filter by status
            all_statuses = list(set(rec.get('status', 'Unknown') for rec in recommendations))
            selected_status = st.selectbox(
                "Filter by Status",
                ["All"] + sorted(all_statuses),
                key="rec_status_filter"
            )

            # Filter recommendations
            filtered_recs = recommendations
            if selected_cat != "All":
                filtered_recs = [r for r in filtered_recs if r.get('category') == selected_cat]
            if selected_status != "All":
                filtered_recs = [r for r in filtered_recs if r.get('status') == selected_status]

            st.markdown(f"**Showing {len(filtered_recs)} of {len(recommendations)} recommendations**")

            # Display as expandable cards
            for rec in filtered_recs:
                symbol = rec.get('symbol', 'Unknown')
                category = rec.get('category', 'Unknown')
                status = rec.get('status', 'unknown')
                price = rec.get('price', 0)
                score = rec.get('score', 0)
                reason = rec.get('reason', '')

                # Status color
                status_colors = {
                    'watch': '🟡',
                    'momentum': '🟢',
                    'opportunity': '🔵',
                    'entry': '🟢',
                    'exit': '🔴'
                }
                status_icon = status_colors.get(status, '⚪')

                with st.expander(f"{status_icon} **{symbol}** | ${price:.2f} | Score: {score:.2f} | {status.upper()}", expanded=False):
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.markdown("**Basic Info**")
                        st.write(f"**Symbol:** {symbol}")
                        st.write(f"**Category:** {category.replace('_', ' ').title()}")
                        if 'basket' in rec:
                            st.write(f"**Basket:** {rec['basket'].replace('_', ' ').title()}")
                        st.write(f"**Status:** {status_icon} {status.upper()}")
                        st.write(f"**Reason:** {reason}")

                    with col2:
                        st.markdown("**Price Data**")
                        st.write(f"**Current Price:** ${price:.2f}")
                        if 'dma_50' in rec:
                            st.write(f"**50 DMA:** ${rec['dma_50']:.2f}")
                        if 'dma_100' in rec:
                            st.write(f"**100 DMA:** ${rec['dma_100']:.2f}")
                        if 'high_1d' in rec:
                            st.write(f"**High 1D:** ${rec['high_1d']:.2f}")
                        if 'high_1w' in rec:
                            st.write(f"**High 1W:** ${rec['high_1w']:.2f}")
                        if 'high_1m' in rec:
                            st.write(f"**High 1M:** ${rec['high_1m']:.2f}")
                        if 'high_3m' in rec:
                            st.write(f"**High 3M:** ${rec['high_3m']:.2f}")

                    with col3:
                        st.markdown("**Metrics**")
                        st.write(f"**Score:** {score:.4f}")
                        if 'drawdown_pct' in rec:
                            st.write(f"**Drawdown:** {rec['drawdown_pct']:.2f}%")
                        if 'slope_pct' in rec:
                            st.write(f"**Slope:** {rec['slope_pct']:.2f}%")
                        if 'relative_strength_pct' in rec:
                            st.write(f"**Rel. Strength:** {rec['relative_strength_pct']:.2f}%")
                        if 'drop_1d' in rec:
                            st.write(f"**Drop 1D:** {rec['drop_1d']:.2f}%")
                        if 'drop_1w' in rec:
                            st.write(f"**Drop 1W:** {rec['drop_1w']:.2f}%")
                        if 'drop_1m' in rec:
                            st.write(f"**Drop 1M:** {rec['drop_1m']:.2f}%")
                        if 'drop_3m' in rec:
                            st.write(f"**Drop 3M:** {rec['drop_3m']:.2f}%")

            st.markdown("---")

            # Summary table view
            st.subheader("📊 Table View")

            # Create DataFrame
            table_data = []
            for rec in filtered_recs:
                table_data.append({
                    'Symbol': rec.get('symbol', ''),
                    'Category': rec.get('category', '').replace('_', ' ').title(),
                    'Status': rec.get('status', '').upper(),
                    'Price': f"${rec.get('price', 0):.2f}",
                    'Score': f"{rec.get('score', 0):.2f}",
                    '50 DMA': f"${rec.get('dma_50', 0):.2f}",
                    '1W High': f"${rec.get('high_1w', 0):.2f}",
                    '1M High': f"${rec.get('high_1m', 0):.2f}",
                    '3M High': f"${rec.get('high_3m', 0):.2f}",
                    'Drawdown %': f"{rec.get('drawdown_pct', 0):.2f}%",
                    'Slope %': f"{rec.get('slope_pct', 0):.2f}%"
                })

            if table_data:
                df = pd.DataFrame(table_data)
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No detailed recommendations available")

        st.markdown("---")

        # Download option
        st.download_button(
            "📥 Download recommended_symbols.json",
            data=json.dumps(recommended, indent=2),
            file_name="recommended_symbols.json",
            mime="application/json"
        )


# =============================================================================
# Settings Page
# =============================================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("Configure GitHub sync, Telegram notifications and scheduler")

    config = load_config()

    # GitHub Integration Status
    st.header("🔗 GitHub Sync (Cloud Persistence)")

    github_token, github_repo, github_branch = get_github_credentials()

    if is_github_enabled():
        st.success(f"✅ GitHub sync enabled: `{github_repo}` ({github_branch})")
        st.caption("Changes to watchlist and config will be saved to your GitHub repo")
    else:
        st.warning("⚠️ GitHub sync not configured - changes will be lost on redeploy")
        with st.expander("📋 How to enable GitHub sync"):
            st.markdown("""
            **1. Create a GitHub Personal Access Token:**
            - Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
            - Generate new token with `repo` scope

            **2. Add secrets in Streamlit Cloud:**
            ```toml
            GITHUB_TOKEN = "ghp_your_token_here"
            GITHUB_REPO = "your-username/investment-notifier"
            GITHUB_BRANCH = "main"
            ```

            **For Local Development:**
            ```bash
            export GITHUB_TOKEN='ghp_your_token_here'
            export GITHUB_REPO='your-username/investment-notifier'
            export GITHUB_BRANCH='main'
            ```
            """)

    st.markdown("---")

    # Telegram Settings
    st.header("📱 Telegram Notifications")

    telegram_config = config.get('notifications', {}).get('telegram', {})

    col1, col2 = st.columns(2)

    with col1:
        telegram_enabled = st.toggle(
            "Enable Telegram Notifications",
            value=telegram_config.get('enabled', False),
            key="telegram_enabled"
        )

        st.markdown("#### Credentials")

        # Check credentials from secrets or env
        bot_token, chat_id = get_telegram_credentials()
        bot_token_set = bool(bot_token)
        chat_id_set = bool(chat_id)

        if bot_token_set and chat_id_set:
            st.success("✅ Telegram credentials configured")
        else:
            st.warning("⚠️ Telegram credentials not set")
            if not bot_token_set:
                st.caption("Missing: TELEGRAM_BOT_TOKEN")
            if not chat_id_set:
                st.caption("Missing: TELEGRAM_CHAT_ID")

        with st.expander("📋 How to configure"):
            st.markdown("""
            **For Streamlit Cloud:**
            1. Go to your app settings → Secrets
            2. Add:
            ```toml
            TELEGRAM_BOT_TOKEN = "your_bot_token"
            TELEGRAM_CHAT_ID = "your_chat_id"
            ```

            **For Local Development:**
            ```bash
            export TELEGRAM_BOT_TOKEN='your_bot_token'
            export TELEGRAM_CHAT_ID='your_chat_id'
            ```
            """)

    with col2:
        st.markdown("#### Notification Events")
        send_on = telegram_config.get('send_on', {})

        notify_exit_risk = st.checkbox("Exit Risk Alerts", value=send_on.get('exit_risk', True))
        notify_entry = st.checkbox("Entry Opportunities", value=send_on.get('entry_opportunity', True))
        notify_new_rec = st.checkbox("New Recommendations", value=send_on.get('new_recommendations', True))
        notify_weekly = st.checkbox("Weekly Summary", value=send_on.get('weekly_summary', True))

    # Test Telegram Button
    st.markdown("---")
    col_test, col_save = st.columns([1, 3])

    with col_test:
        if st.button("🔔 Test Telegram", type="secondary"):
            try:
                from lib.alerts import send_telegram
                result = send_telegram("🔔 Test message from Investment Notifier Dashboard!", parse_mode="Markdown")
                if result:
                    st.success("✅ Test message sent successfully!")
                else:
                    st.error("❌ Failed to send test message. Check credentials.")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    st.markdown("---")

    # Scheduler Settings
    st.header("⏰ Scheduler")

    scheduler_config = config.get('scheduler', {})

    col1, col2 = st.columns(2)

    with col1:
        scheduler_enabled = st.toggle(
            "Enable Scheduler",
            value=scheduler_config.get('enabled', False),
            key="scheduler_enabled"
        )

        st.markdown("#### Run Days")
        days_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
        current_days = scheduler_config.get('days', [0, 1, 2, 3, 4])

        selected_days = []
        cols = st.columns(7)
        for i, (day_num, day_name) in enumerate(days_map.items()):
            with cols[i]:
                if st.checkbox(day_name[:3], value=day_num in current_days, key=f"day_{day_num}"):
                    selected_days.append(day_num)

    with col2:
        st.markdown("#### Run Times")
        current_times = scheduler_config.get('times', ['09:30', '16:00'])

        time1 = st.time_input("Morning Run", value=datetime.strptime(current_times[0] if current_times else '09:30', '%H:%M').time(), key="time1")
        time2 = st.time_input("Evening Run", value=datetime.strptime(current_times[1] if len(current_times) > 1 else '16:00', '%H:%M').time(), key="time2")

    st.markdown("---")

    # Save Settings
    if st.button("💾 Save Settings", type="primary"):
        # Update config
        if 'notifications' not in config:
            config['notifications'] = {}
        if 'telegram' not in config['notifications']:
            config['notifications']['telegram'] = {}

        config['notifications']['telegram']['enabled'] = telegram_enabled
        config['notifications']['telegram']['send_on'] = {
            'exit_risk': notify_exit_risk,
            'entry_opportunity': notify_entry,
            'new_recommendations': notify_new_rec,
            'weekly_summary': notify_weekly
        }

        config['scheduler'] = {
            'enabled': scheduler_enabled,
            'days': selected_days,
            'times': [time1.strftime('%H:%M'), time2.strftime('%H:%M')],
            'timezone': scheduler_config.get('timezone', 'America/New_York')
        }

        if save_config(config):
            st.success("✅ Settings saved!")
            st.rerun()
        else:
            st.error("❌ Failed to save settings")

    st.markdown("---")

    # Manual Run Section
    st.header("🚀 Manual Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔄 Run Discovery Now", type="secondary"):
            with st.spinner("Running discovery..."):
                success, message = run_discovery_script()
                if success:
                    st.success(message)
                else:
                    st.error(message)

    with col2:
        if st.button("📨 Send Alert Now", type="secondary"):
            with st.spinner("Sending alert..."):
                try:
                    venv_python = os.path.join(BASE_DIR, '.venv', 'bin', 'python')
                    if not os.path.exists(venv_python):
                        import sys
                        venv_python = sys.executable

                    result = subprocess.run(
                        [venv_python, os.path.join(BASE_DIR, 'scheduler.py'), '--once'],
                        cwd=BASE_DIR,
                        capture_output=True,
                        text=True,
                        timeout=180
                    )
                    if result.returncode == 0:
                        st.success("✅ Alert sent!")
                    else:
                        st.error(f"❌ Error: {result.stderr}")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

    with col3:
        st.markdown("#### Scheduler Command")
        st.code("python scheduler.py --daemon", language="bash")
        st.caption("Run this in terminal for continuous scheduling")

    st.markdown("---")

    # How to Setup Telegram Bot
    with st.expander("📖 How to Setup Telegram Bot"):
        st.markdown("""
        ### Step 1: Create a Bot
        1. Open Telegram and search for **@BotFather**
        2. Send `/newbot` command
        3. Follow the prompts to name your bot
        4. Copy the **Bot Token** (looks like `123456:ABC-DEF...`)

        ### Step 2: Get Your Chat ID
        1. Start a chat with your new bot
        2. Send any message to the bot
        3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
        4. Find `"chat":{"id":` in the response - that's your Chat ID

        ### Step 3: Set Environment Variables
        ```bash
        # Add to your ~/.zshrc or ~/.bashrc
        export TELEGRAM_BOT_TOKEN='your_bot_token_here'
        export TELEGRAM_CHAT_ID='your_chat_id_here'
        ```

        ### Step 4: Test
        Click the **Test Telegram** button above to verify!
        """)


# =============================================================================
# Footer
# =============================================================================

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style='text-align: center; color: #666; font-size: 12px;'>
        Investment Notifier v1.0<br>
        Built with Streamlit
    </div>
    """,
    unsafe_allow_html=True
)
