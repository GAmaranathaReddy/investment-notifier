# Long-Term Investor Alert System

A calm, disciplined alert system for long-term investors focused on capital protection and low-risk entry opportunities.

## Features

- **Exit Risk Alerts**: Notifies when positions show warning signs
  - Trend deterioration (50-DMA crosses below 100-DMA)
  - Significant drawdown (≥10% from 3-month high)

- **Entry Opportunity Alerts**: Identifies low-risk entry points
  - Price above 100-DMA (healthy uptrend)
  - 100-DMA slope flat or rising
  - 5-8% pullback from recent high
  - Stable recent price action

- **Telegram Integration**: Free instant alerts to your phone

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Telegram Bot

1. Create a bot via [@BotFather](https://t.me/botfather) on Telegram
2. Get your bot token
3. Start a chat with your bot
4. Get your chat ID (you can use [@userinfobot](https://t.me/userinfobot))

### 3. Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

### 4. Configure Symbols

Edit `stocks.json` to add your watchlist:

```json
[
    "AAPL",
    "MSFT",
    "GOOGL",
    "SPY"
]
```

### 5. Run Manually

```bash
python investor_alert.py
```

## GitHub Actions (Automated)

The system runs automatically via GitHub Actions:

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. The workflow runs daily at 9:00 PM UTC (after US market close)
5. You can also trigger it manually from the **Actions** tab

## Alert Examples

### Exit Risk Alert
```
🚨 EXIT RISK
Symbol: SI=F
Reason: Drawdown 10.4% from recent high
Price: 22.81
Date: 2026-01-31
```

### Entry Opportunity Alert
```
🟢 ENTRY OPPORTUNITY
Symbol: AAPL
Reason: Pullback 6.2% in healthy uptrend
Price: 188.30
Date: 2026-01-31
```

## Philosophy

This system is designed for:

- **Long-term investors** (weeks to months holding periods)
- **Capital protection** (exit risks have priority)
- **Disciplined entries** (avoid FOMO, wait for pullbacks)
- **Calm decision-making** (avoid noise and hype)

It intentionally avoids:

- Intraday trading signals
- Complex indicators (RSI, MACD, Bollinger Bands)
- Buy/sell price targets
- Paid APIs or services

## License

MIT
