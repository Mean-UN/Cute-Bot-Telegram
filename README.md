# Cute Companion Telegram Bot

A simple Telegram bot with a warm, affectionate response style using Gemini.

## 1) Create credentials
- Create a Telegram bot in BotFather and copy `BOT_TOKEN`.
- Create a Google AI API key and copy `GEMINI_API_KEY`.

## 2) Install dependencies
```powershell
python -m pip install -r requirements.txt
```

## 3) Set environment variables (PowerShell)
```powershell
$env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
$env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
# Optional model failover list:
$env:GEMINI_MODELS="gemini-2.0-flash,gemini-1.5-flash"
```

## 4) Run
```powershell
python bot.py
```

## Personalization
Edit the `BASE_PERSONALITY` string in `bot.py` to change tone, emoji frequency, and style.

## Commands
- `/start` or `/help`: show intro and usage.
- `/kh`: switch replies to Khmer.
- `/en`: switch replies to English.
- `/mode cute`: maximum affectionate style.
- `/mode sweet`: softer and more balanced affectionate style.
- `/reset`: clear chat memory.

## Notes
- Memory is in-process only (clears when bot restarts).
- For production, use persistent storage and webhook deployment.
