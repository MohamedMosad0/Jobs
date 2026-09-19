import hashlib
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = Path("data/seen_jobs.json")
MAX_AGE_DAYS = 21
MAX_MESSAGES_PER_RUN = 12

ANDROID_TERMS = (
    "android", "kotlin", "android sdk", "jetpack compose",
    "android developer", "android engineer",
)
JUNIOR_TERMS = (
    "junior", "entry level", "entry-level", "intern", "internship",
    "graduate", "fresh graduate", "trainee", "associate",
)
SENIOR_TERMS = (
    "senior", "lead", "principal", "staff", "manager", "director",
    "head of", "architect",
)
BLOCKED_LOCATION_TERMS = (
    "usa only", "us only", "united states only", "uk only", "canada only",
    "australia only", "germany only", "france only",
)

# Public feeds that explicitly permit feed consumption/redistribution with
# attribution. We link users back to the original job URL.
FEEDS = [
    ("RemoteOK", "https://remoteok.com/remote-android-jobs.rss"),
    ("We Work Remotely", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("Remotive", "https://remotive.com/feed"),
]


def normalize_text(value):
    value = html.unescape(value or "")
    return " ".join(value.lower().split())


def load_seen():
    try:
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return set()


def save_seen(seen):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def entry_text(entry):
    title = normalize_text(entry.get("title"))
    summary = normalize_text(entry.get("summary") or entry.get("description"))
    return title, summary, f"{title} {summary}"


def published_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def make_id(source, entry):
    raw = (
        entry.get("id")
        or entry.get("guid")
        or entry.get("link")
        or f"{entry.get('title', '')}|{entry.get('published', '')}"
    )
    return hashlib.sha256(f"{source}|{raw}".encode("utf-8")).hexdigest()


def is_relevant(entry):
    title, summary, text = entry_text(entry)

    if not any(term in text for term in ANDROID_TERMS):
        return False

    if any(term in title for term in SENIOR_TERMS):
        return False

    if any(term in text for term in BLOCKED_LOCATION_TERMS):
        return False

    # Keep junior/intern roles and unspecific Android roles. The latter are
    # allowed because many companies omit experience level from the title.
    return any(term in text for term in JUNIOR_TERMS) or "android" in title


def clean_url(entry):
    return (entry.get("link") or "").strip()


def build_message(source, entry):
    title = entry.get("title", "Android opportunity").strip()
    link = clean_url(entry)
    _, summary, _ = entry_text(entry)
    date = published_datetime(entry)

    level = "Junior / Entry / Internship" if any(
        term in f"{title.lower()} {summary}" for term in JUNIOR_TERMS
    ) else "Android role"

    date_text = date.strftime("%Y-%m-%d") if date else "recent"

    snippet = summary[:600]
    if len(summary) > 600:
        snippet += "…"

    return (
        f"🚀 *New Android Job*\n"
        f"*{title}*\n"
        f"🎯 {level}\n"
        f"📰 Source: {source}\n"
        f"📅 {date_text}\n\n"
        f"{snippet}\n\n"
        f"🔗 [Apply]({link})"
    )


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID repository secrets."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    response.raise_for_status()


def fetch_new_jobs(seen):
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    candidates = []
    discovered_ids = set()

    for source, feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            if getattr(feed, "bozo", False):
                print(f"Warning: feed parser reported an issue for {source}")

            for entry in feed.entries:
                job_id = make_id(source, entry)
                if job_id in seen or job_id in discovered_ids:
                    continue

                published = published_datetime(entry)
                if published and published < cutoff:
                    continue

                if not is_relevant(entry):
                    continue

                link = clean_url(entry)
                if not link:
                    continue

                discovered_ids.add(job_id)
                candidates.append((published or datetime.min.replace(tzinfo=timezone.utc),
                                   source, entry, job_id))
        except Exception as exc:
            print(f"Warning: failed to read {source}: {exc}")

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:MAX_MESSAGES_PER_RUN], discovered_ids


def main():
    seen = load_seen()
    candidates, discovered_ids = fetch_new_jobs(seen)

    sent_ids = set()
    for _, source, entry, job_id in candidates:
        try:
            send_telegram(build_message(source, entry))
            sent_ids.add(job_id)
        except Exception as exc:
            print(f"Warning: failed to send '{entry.get('title')}': {exc}")

    save_seen(seen | sent_ids)
    print(f"Sent {len(sent_ids)} new job(s).")


if __name__ == "__main__":
    main()
