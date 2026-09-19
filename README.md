# Android Job Scout

A lightweight Telegram job scout running on GitHub Actions.

## Sources

- RemoteOK public JSON feed
- Remotive public jobs API
- Jobicy public remote-jobs API
- We Work Remotely programming RSS

The scout keeps direct source links and source attribution.

## Filtering

The filter looks for Android/Kotlin signals, keeps junior/entry/intern/graduate/trainee roles plus unspecific Android roles, excludes explicit senior/lead/principal/staff/manager/director roles, and filters obvious country-restricted listings.

When a source exposes candidate eligibility, global/Worldwide/Remote/Egypt/Africa/Middle East listings are kept while clearly local country-only listings are ignored.

## Duplicate protection

Sent jobs are stored in `data/seen_jobs.json`. The GitHub Actions workflow commits this history back to the repository after each successful run.

## Telegram secrets

In **Settings → Secrets and variables → Actions**, add:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not put either value in source code.

## Schedule

The workflow runs twice daily at **07:17 UTC** and **19:17 UTC** (09:17 and 21:17 Egypt time when Egypt is UTC+2), and supports **Run workflow** for manual testing.

It also has a code-change trigger for relevant workflow/source changes. History-only commits do not retrigger it.

## Reliability

Source failures are isolated: if one provider is unavailable, the remaining sources are still processed. Telegram messages use HTML formatting to avoid Markdown escaping failures.

The feeds/APIs are a discovery layer; they do not guarantee that every listing is eligible for Egypt. Always verify the employer's location/eligibility on the original listing before applying.

## Source guidance

RemoteOK documents public JSON/RSS feeds and asks aggregators to credit RemoteOK and link to the original job post.

Remotive documents public API/RSS access and asks applications to link back to the Remotive job URL and attribute Remotive.

Jobicy provides a public JSON endpoint without an API key and asks integrations to keep Jobicy attribution and canonical listing URLs.


## Egypt discovery feeds

The scout also checks Google News RSS queries that index public job pages from Bayt, WUZZUF, and LinkedIn. These are used as discovery feeds rather than scraping those job sites directly. The original listing remains the source to verify before applying.

This matters because Bayt currently shows a substantial Egypt Android-job result set, including junior listings, while WUZZUF maintains a large Egypt job index. The discovery layer is intentionally separate from the direct APIs/feeds so a blocked or unavailable source does not stop the scout.
