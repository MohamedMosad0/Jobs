import hashlib
import html
import json
import os
import re
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = Path("data/seen_jobs.json")
MAX_AGE_DAYS = 21
MAX_MESSAGES_PER_RUN = 12
REQUEST_TIMEOUT = 25

ANDROID_TITLE_TERMS = (
    "android", "kotlin", "android developer", "android engineer",
    "android sdk", "jetpack compose",
)
ANDROID_STACK_TERMS = (
    "android", "kotlin", "android sdk", "jetpack", "compose",
    "android studio", "gradle", "room", "retrofit", "hilt",
    "coroutines", "android developer", "android engineer",
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
OPEN_LOCATION_TERMS = (
    "worldwide", "anywhere", "global", "remote", "egypt",
    "africa", "middle east",
)

HEADERS = {
    "User-Agent": "AndroidJobScout/1.0 (+https://github.com/MohamedMosad0/Jobs)",
    "Accept": "application/json, application/rss+xml, application/xml, text/xml",
}

def google_news_url(query):
    return (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query)}&hl=en-EG&gl=EG&ceid=EG:en"
    )


SOURCES = (
    ("RemoteOK", "remoteok_json", "https://remoteok.com/api"),
    ("Remotive", "remotive_json", "https://remotive.com/api/remote-jobs"),
    ("Jobicy", "jobicy_json", "https://jobicy.com/api/v2/remote-jobs?count=200"),
    ("We Work Remotely", "rss", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    # Discovery feeds only: Google News indexes public job pages without us
    # scraping Bayt/WUZZUF directly. The Telegram message links to the indexed
    # result, which can lead to the original posting.
    ("Bayt via Google News", "rss", google_news_url(
        'site:bayt.com/en/egypt/jobs/ ("Android Developer" OR "Android Engineer" OR Kotlin)'
    )),
    ("WUZZUF via Google News", "rss", google_news_url(
        'site:wuzzuf.net/jobs/ ("Android Developer" OR "Android Engineer" OR Kotlin)'
    )),
    ("LinkedIn via Google News", "rss", google_news_url(
        'site:linkedin.com/jobs/view/ ("Android Developer" OR "Android Engineer" OR Kotlin) Egypt'
    )),
)


def normalize_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
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


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def make_id(source, raw_id, title, link):
    raw = raw_id or link or f"{title}|unknown"
    return hashlib.sha256(f"{source}|{raw}".encode("utf-8")).hexdigest()


def normalize_job(source, title, description, link, published=None, level="", location=""):
    return {
        "source": source,
        "title": str(title or "Android opportunity").strip(),
        "description": normalize_text(description),
        "link": str(link or "").strip(),
        "published": parse_date(published),
        "level": normalize_text(level),
        "location": normalize_text(location),
    }


def remoteok_jobs(data):
    jobs = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("position"):
            jobs.append(
                normalize_job(
                    "RemoteOK",
                    item.get("position"),
                    f"{item.get('description', '')} {' '.join(item.get('tags') or [])}",
                    item.get("url"),
                    item.get("date"),
                    item.get("position"),
                    item.get("location"),
                )
            )
    return jobs


def remotive_jobs(data):
    return [
        normalize_job(
            "Remotive", item.get("title"), item.get("description"), item.get("url"),
            item.get("publication_date"), item.get("job_type"),
            item.get("candidate_required_location"),
        )
        for item in (data or {}).get("jobs", [])
    ]


def jobicy_jobs(data):
    return [
        normalize_job(
            "Jobicy", item.get("jobTitle"),
            item.get("jobDescription") or item.get("jobExcerpt"),
            item.get("url"), item.get("pubDate"), item.get("jobLevel"),
            item.get("jobGeo"),
        )
        for item in (data or {}).get("jobs", [])
    ]


def rss_jobs(content, source):
    feed = feedparser.parse(content)
    if getattr(feed, "bozo", False):
        print(f"Warning: RSS parser reported an issue for {source}")

    jobs = []
    for entry in feed.entries:
        published = None
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published = datetime(*parsed[:6], tzinfo=timezone.utc)

        jobs.append(
            normalize_job(
                source,
                entry.get("title"),
                entry.get("summary") or entry.get("description"),
                entry.get("link"),
                published,
                entry.get("title"),
                "",
            )
        )
    return jobs


def fetch_source(source, kind, url):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    if kind == "rss":
        return rss_jobs(response.content, source)

    data = response.json()
    if kind == "remoteok_json":
        return remoteok_jobs(data)
    if kind == "remotive_json":
        return remotive_jobs(data)
    if kind == "jobicy_json":
        return jobicy_jobs(data)
    raise ValueError(f"Unsupported source type: {kind}")


def is_relevant(job):
    title = normalize_text(job["title"])
    description = job["description"]
    text = f"{title} {description}"
    level = job["level"]
    location = job["location"]

    title_match = any(term in title for term in ANDROID_TITLE_TERMS)
    stack_hits = sum(term in description for term in ANDROID_STACK_TERMS)

    # Avoid unrelated jobs that merely mention Android once in their description.
    if not title_match and stack_hits < 2:
        return False

    if any(term in f"{title} {level}" for term in SENIOR_TERMS):
        return False

    if any(term in f"{location} {text}" for term in BLOCKED_LOCATION_TERMS):
        return False

    if location and not any(term in location for term in OPEN_LOCATION_TERMS):
        return False

    return any(term in text for term in JUNIOR_TERMS) or title_match


def build_message(job):
    title = html.escape(job["title"])
    source = html.escape(job["source"])
    link = html.escape(job["link"], quote=True)
    level = (
        "Junior / Entry / Internship"
        if any(term in f"{job['title'].lower()} {job['description']}" for term in JUNIOR_TERMS)
        else "Android role"
    )
    date_text = job["published"].strftime("%Y-%m-%d") if job["published"] else "recent"

    snippet = job["description"][:600]
    if len(job["description"]) > 600:
        snippet += "…"

    return (
        "🚀 <b>New Android Job</b>\n"
        f"<b>{title}</b>\n"
        f"🎯 {html.escape(level)}\n"
        f"📰 Source: {source}\n"
        f"📅 {date_text}\n\n"
        f"{html.escape(snippet)}\n\n"
        f'<a href="{link}">🔗 Apply</a>'
    )


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID repository secrets.")

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        try:
            detail = response.json().get("description", "Unknown Telegram API error")
        except ValueError:
            detail = response.text[:300]
        raise RuntimeError(f"Telegram API {response.status_code}: {detail}")


def fetch_new_jobs(seen):
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    candidates = []
    discovered_ids = set()

    for source, kind, url in SOURCES:
        try:
            jobs = fetch_source(source, kind, url)
            accepted = 0

            for job in jobs:
                job_id = make_id(source, "", job["title"], job["link"])
                if job_id in seen or job_id in discovered_ids:
                    continue

                if job["published"] and job["published"] < cutoff:
                    continue
                if not job["link"] or not is_relevant(job):
                    continue

                discovered_ids.add(job_id)
                candidates.append((
                    job["published"] or datetime.min.replace(tzinfo=timezone.utc),
                    job, job_id,
                ))
                accepted += 1

            print(f"{source}: {accepted} new matching job(s) found.")
        except Exception as exc:
            print(f"Warning: failed to read {source}: {exc}")

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:MAX_MESSAGES_PER_RUN]


def test_telegram():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": "✅ Android Job Scout Telegram test: connection OK."},
        timeout=TIMEOUT,
    )
    if not response.ok:
        try:
            details = response.json().get("description", response.text)
        except ValueError:
            details = response.text
        raise RuntimeError(f"Telegram API {response.status_code}: {details}")
    print("Telegram test message sent successfully.")


def main():
    seen = load_seen()
    candidates = fetch_new_jobs(seen)
    sent_ids = set()

    for _, job, job_id in candidates:
        try:
            send_telegram(build_message(job))
            sent_ids.add(job_id)
        except Exception as exc:
            print(f"Warning: failed to send '{job['title']}': {exc}")

    save_seen(seen | sent_ids)
    print(f"Sent {len(sent_ids)} new job(s).")


if __name__ == "__main__":
    main()
