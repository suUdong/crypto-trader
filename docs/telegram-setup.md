# Telegram Notification Setup

crypto-trader sends real-time alerts via Telegram for trade fills, kill switch
triggers, drawdown warnings, order rejections, errors, daemon restarts, and
daily PnL summaries.

## 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts (pick a name and username).
3. BotFather replies with an **HTTP API token** like `123456789:ABCdefGHI...`.
   Copy it — this is your `bot_token`.

## 2. Get Your Chat ID

**For personal alerts (DM):**

1. Send any message to your new bot.
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Find `"chat":{"id": 123456789, ...}` — that number is your `chat_id`.

**For group alerts:**

1. Add the bot to the group.
2. Send a message in the group.
3. Call `getUpdates` as above — group chat IDs are negative (e.g. `-100123456789`).

## 3. Configure crypto-trader

Set environment variables (recommended — never commit real tokens):

```bash
export CT_TELEGRAM_BOT_TOKEN="123456789:ABCdefGHI..."
export CT_TELEGRAM_CHAT_ID="-100123456789"
```

Or edit `config/daemon.toml` directly (for local dev only):

```toml
[telegram]
bot_token = "123456789:ABCdefGHI..."
chat_id = "-100123456789"
```

When both values are set, `TelegramConfig.enabled` returns `True` and alerts
are sent. When either is empty, `NullNotifier` is used — no errors, no alerts.

## 4. Alert Types

| Alert | Trigger | Cooldown |
|---|---|---|
| Trade fill | Every buy/sell execution | None |
| Kill switch | Portfolio drawdown / daily loss / consecutive losses breach | None |
| Drawdown warning | 50% of limit (warn) or 75% (reduce) | Per-stage dedup |
| Order rejection | Risk manager blocks an order | 5 min |
| Error | Pipeline exception | 5 min |
| Daemon status | Crash / restart / degraded | 5 min |
| Daily PnL summary | Once per 24h, per-wallet breakdown | 24h + state file |

## 5. Verify

Quick test to confirm your bot works:

```bash
curl -s -X POST "https://api.telegram.org/bot${CT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"${CT_TELEGRAM_CHAT_ID}\", \"text\": \"crypto-trader test\"}"
```

You should receive "crypto-trader test" in Telegram. Then start the daemon:

```bash
python -m crypto_trader.cli
```

The first daily PnL summary will be sent after the first full trading cycle.

## 6. Troubleshooting

- **No alerts but no errors**: Check `TelegramConfig.enabled` — both `bot_token`
  and `chat_id` must be non-empty strings.
- **HTTP 401**: Bot token is invalid. Regenerate via BotFather `/token`.
- **HTTP 400 "chat not found"**: Bot hasn't received a message from that chat yet.
  Send a message first, then retry.
- **Duplicate alerts**: Cooldowns are in-memory. Daemon restarts reset them.
  Daily PnL uses a state file to prevent duplicates across restarts.
