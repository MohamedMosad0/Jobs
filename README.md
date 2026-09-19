# Android Job Scout

Automated Android job discovery with Telegram notifications via GitHub Actions.

## Secrets

Add these repository secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Schedule

Runs twice daily and can also be started manually from GitHub Actions.

## Current source

- RemoteOK Android RSS

The repository is structured so additional sources and stronger Egypt/remote filtering can be added without changing the Telegram/Actions setup.
