import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HISTORY_FILE = Path("data/seen_jobs.json")

KEYWORDS = ("android", "kotlin", "android sdk")
JUNIOR_KEYWORDS = ("junior", "entry level", "entry-level", "intern", "internship", "graduate", "fresh graduate", "trainee", "associate")
REMOTE_KEYWORDS = ("remote", "work from home", "remote-first", "distributed", "anywhere")

SENIOR_KEYWORDS = ("senior", "lead", "principal", "staff", "manager", "director", "head of")

FEEDS = [
    ("RemoteOK", "https://remoteok.com/remote-android-jobs.rss"),
]

def load_seen():
    try:
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen(seen):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_text(value):
    return " ".join((value or "").lower().split())

def make_id(entry):
    raw = entry.get("id") or entry.get("link") or f"{entry.get('title','')}|{entry.get('published','')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def is_relevant(entry):
    title = normalize_text(entry.get("title"))
    summary = normalize_text(entry.get("summary"))
    text = f"{title} {summary}"

    if not any(k in text for k in KEYWORDS):
        return False

    if any(k in title for k in SENIOR_KEYWORDS):
        return False

    # Prefer junior/entry/intern signals, but allow unspecific Android roles
    # when they are not explicitly senior/lead.
    return any(k in text for k in JUNIOR_KEYWORDS) or "android" in title

def build_message(source, entry):
    title = entry.get("title", "Android opportunity")
    link = entry.get("link", "")
    summary = normalize_text(entry.get("summary"))
    remote = "Remote" if any(k in summary for k in REMOTE_KEYWORDS) or "remote" in normalize_text(title) else "Remote source"
    snippet = (summary[:500] + "…") if len(summary) > 500 else summary

    return (
        f"🚀 *New Android Job*\n"
        f"*{title}*\n"
        f"🏢 Source: {source}\n"
        f"📍 {remote}\n"
        f"\n{snippet}\n"
        f"\n🔗 [Apply]({link})"
    )

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
        timeout=20,
    )
    response.raise_for_status()

def fetch_new_jobs(seen):
    new_ids = set()
    messages = []

    for source, feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            job_id = make_id(entry)
            if job_id in seen:
                continue
            if not is_relevant(entry):
                continue
            new_ids.add(job_id)
            messages.append(build_message(source, entry))

    return new_ids, messages

def main():
    seen = load_seen()
    new_ids, messages = fetch_new_jobs(seen)

    for message in messages:
        send_telegram(message)

    save_seen(seen | new_ids)
    print(f"Processed {len(messages)} new job(s).")

if __name__ == "__main__":
    main()
