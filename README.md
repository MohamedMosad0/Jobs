# Android Job Scout

A lightweight Telegram job scout running on GitHub Actions.

## What it watches

- RemoteOK Android RSS
- We Work Remotely programming RSS
- Remotive public RSS

The filter prioritizes Android/Kotlin roles, junior/entry-level/internship signals, and excludes explicit senior/lead roles and obvious country-restricted listings.

## Duplicate protection

Sent jobs are stored in `data/seen_jobs.json`. The GitHub Actions workflow commits this history back to the repository after each successful run.

## Telegram secrets

In **Settings → Secrets and variables → Actions**, add:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not put either value in source code.

## Run

The workflow runs twice daily and also supports **Run workflow** for manual testing.

## Notes

Feeds are used according to their public feed guidance, with attribution and direct links back to the original job listing. The feeds are a discovery layer; they do not guarantee that every listing is eligible for Egypt. Country-restricted listings that are explicit in the feed are filtered out.

