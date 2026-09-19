import hashlib
import html
import json
import os
import re
from urllib.parse import quote_plus, urljoin
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

HISTORY_FILE = Path("data/seen_jobs.json")
MAX_AGE_DAYS = 30
GOOGLE_NEWS_MAX_AGE_DAYS = 60
MAX_MESSAGES_PER_RUN = 12
REQUEST_TIMEOUT = 25

ANDROID_TITLE_TERMS = (
    "android", "android developer", "android engineer",
    "android sdk", "jetpack compose", "android mobile",
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
    "senior", "sr.", "sr ", "lead", "principal", "staff", "manager",
    "director", "head of", "architect",
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
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, text/html",
}


def google_news_url(query):
    return (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query + ' when:' + str(GOOGLE_NEWS_MAX_AGE_DAYS) + 'd')}"
        "&hl=en-EG&gl=EG&ceid=EG:en"
    )


SOURCES = (
    ("RemoteOK", "remoteok_json", "https://remoteok.com/api"),
    ("Remotive", "remotive_json", "https://remotive.com/api/remote-jobs"),
    ("Jobicy", "jobicy_json", "https://jobicy.com/api/v2/remote-jobs?count=200"),
    ("RemoteJobs.org", "remotejobs_json", "https://remotejobs.org/api/v1/jobs?category=programming&limit=50"),
    ("We Work Remotely", "rss", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),

    # Broad indexed discovery complements board-specific feeds.
    ("Egypt Android Jobs via Google News", "rss", google_news_url(
        '"Android Developer" Egypt jobs'
    )),
    ("Egypt Kotlin Android Jobs via Google News", "rss", google_news_url(
        'Kotlin Android Egypt jobs'
    )),

    ("Bayt Android via Google News", "rss", google_news_url(
        'site:bayt.com/en/egypt/jobs/ "Junior Android Developer"'
    )),
    ("Bayt Kotlin via Google News", "rss", google_news_url(
        'site:bayt.com/en/egypt/jobs/ "Android Engineer" Kotlin Egypt'
    )),
    ("WUZZUF Android via Google News", "rss", google_news_url(
        'site:wuzzuf.net/jobs/ "Junior Android Developer" Egypt'
    )),
    ("WUZZUF Kotlin via Google News", "rss", google_news_url(
        'site:wuzzuf.net/jobs/ "Android Developer" Kotlin Egypt'
    )),
    ("LinkedIn Android via Google News", "rss", google_news_url(
        'site:linkedin.com/jobs/view/ "Junior Android Developer" Egypt'
    )),
    ("LinkedIn Kotlin via Google News", "rss", google_news_url(
        'site:linkedin.com/jobs/view/ "Android Developer" Kotlin Egypt'
    )),
    ("Indeed Android via Google News", "rss", google_news_url(
        'site:indeed.com/viewjob "Android Developer" Egypt'
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
    # Same apply URL should be one job even when discovered from multiple feeds.
    raw = link or raw_id or f"{title}|unknown"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
            jobs.append(normalize_job(
                "RemoteOK", item.get("position"),
                f"{item.get('description', '')} {' '.join(item.get('tags') or [])}",
                item.get("url"), item.get("date"), item.get("position"), item.get("location"),
            ))
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


def remotejobs_jobs(data):
    jobs = []
    for item in (data or {}).get("data", []):
        company = (item.get("company") or {}).get("name", "")
        jobs.append(normalize_job(
            "RemoteJobs.org", item.get("title"),
            f"{item.get('description', '')} {company}",
            item.get("apply_url") or item.get("url"),
            item.get("posted_at"), item.get("type"), item.get("location"),
        ))
    return jobs


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

        summary = entry.get("summary") or entry.get("description") or ""
        jobs.append(normalize_job(
            source, entry.get("title"), summary, entry.get("link"),
            published, entry.get("title"), "",
        ))
    return jobs


def parse_relative_age(value, now=None):
    text = normalize_text(value)
    now = now or datetime.now(timezone.utc)

    if text in {"just now", "today"}:
        return now
    if text == "yesterday":
        return now - timedelta(days=1)

    match = re.search(
        r"(\\d+)\\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months)\\s+ago",
        text,
    )
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("minute"):
            return now - timedelta(minutes=amount)
        if unit.startswith("hour"):
            return now - timedelta(hours=amount)
        if unit.startswith("day"):
            return now - timedelta(days=amount)
        if unit.startswith("week"):
            return now - timedelta(weeks=amount)
        return now - timedelta(days=30 * amount)

    if "30+ days ago" in text:
        return now - timedelta(days=31)

    return None


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
    if kind == "remotejobs_json":
        return remotejobs_jobs(data)
    raise ValueError(f"Unsupported source type: {kind}")


def has_android_match(title, description):
    title_match = any(term in title for term in ANDROID_TITLE_TERMS)
    stack_hits = sum(term in description for term in ANDROID_STACK_TERMS)
    return title_match, stack_hits


def has_experience_over_limit(text):
    # Reject explicit requirements above the user's junior/entry target.
    patterns = (
        r"\b(?:4|5|6|7|8|9|10|[1-9]\d)\s*\+\s*(?:years?|yrs?)\b",
        r"\b(?:minimum|min\.?|at least)\s+(?:4|5|6|7|8|9|10|[1-9]\d)\s*(?:years?|yrs?)\b",
        r"\b(?:more than|over)\s+(?:4|5|6|7|8|9|10|[1-9]\d)\s*(?:years?|yrs?)\b",
        r"\b(?:4|5|6|7|8|9|10|[1-9]\d)\s*[-–]\s*(?:5|6|7|8|9|10|[1-9]\d)\s*(?:years?|yrs?)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def relevance_reason(job):
    title = normalize_text(job["title"])
    description = job["description"]
    text = f"{title} {description}"
    level = job["level"]
    location = job["location"]

    title_match, stack_hits = has_android_match(title, description)

    if not title_match and stack_hits < 2:
        return "android_match"

    if any(term in f"{title} {level}" for term in SENIOR_TERMS):
        return "seniority"

    if has_experience_over_limit(text):
        return "experience"

    if any(term in f"{location} {text}" for term in BLOCKED_LOCATION_TERMS):
        return "blocked_location"

    if location and not any(term in location for term in OPEN_LOCATION_TERMS):
        return "location"

    if not any(term in text for term in JUNIOR_TERMS) and not title_match:
        return "seniority_signal"

    return None


def build_message(job):
    title = html.escape(job["title"])
    source = html.escape(job["source"])
    link = html.escape(job["link"], quote=True)
    text = f"{job['title']} {job['description']}"
    level = (
        "Junior / Entry / Internship"
        if any(term in text.lower() for term in JUNIOR_TERMS)
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
        + ("Powered by RemoteJobs.org\n" if job["source"] == "RemoteJobs.org" else "")
        + f"📅 {date_text}\n\n"
        f"{html.escape(snippet)}\n\n"
        f'<a href="{link}">🔗 Apply</a>'
    )


def telegram_request(method, payload=None):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN repository secret.")

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=payload or {},
        timeout=REQUEST_TIMEOUT,
    )
    try:
        data = response.json()
    except ValueError:
        data = {"ok": False, "description": response.text[:300]}

    if not response.ok or not data.get("ok"):
        raise RuntimeError(
            f"Telegram API {response.status_code}: "
            f"{data.get('description', 'Unknown Telegram API error')}"
        )
    return data["result"]


def discover_chat_id():
    bot = telegram_request("getMe")
    updates = telegram_request("getUpdates", {"limit": 100, "timeout": 0})
    candidates = []

    print(f"Telegram bot detected: @{bot.get('username', 'unknown')}")

    for update in updates:
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("my_chat_member")
            or update.get("chat_member")
        )
        chat = (message or {}).get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None and chat.get("type") == "private":
            candidates.append((update.get("update_id", 0), chat_id))

    print(f"Telegram updates received: {len(updates)}")
    print(f"Private chat candidates: {len(candidates)}")

    if not candidates:
        raise RuntimeError(
            "No private chat update found. Make sure you opened THIS bot shown above "
            "and pressed Start/sent /start, then run the test again."
        )

    return str(max(candidates)[1])


def send_telegram(message):
    telegram_request("sendMessage", {
        "chat_id": discover_chat_id(),
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    })


def fetch_new_jobs(seen):
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    google_news_cutoff = datetime.now(timezone.utc) - timedelta(days=GOOGLE_NEWS_MAX_AGE_DAYS)
    candidates = []
    discovered_ids = set()

    for source, kind, url in SOURCES:
        try:
            jobs = fetch_source(source, kind, url)
            accepted = 0
            skipped_seen = skipped_old = skipped_no_link = 0
            reasons = {}

            print(f"{source}: {len(jobs)} raw job(s).")
            for sample in jobs[:5]:
                published = sample["published"].strftime("%Y-%m-%d") if sample["published"] else "unknown"
                print(f"  sample: {sample['title']!r} | published={published} | location={sample['location']!r}")

            for job in jobs:
                job_id = make_id(source, "", job["title"], job["link"])
                if job_id in seen or job_id in discovered_ids:
                    skipped_seen += 1
                    continue
                job_cutoff = (
                    google_news_cutoff
                    if "via Google News" in source
                    else cutoff
                )
                if job["published"] and job["published"] < job_cutoff:
                    skipped_old += 1
                    continue
                if not job["link"]:
                    skipped_no_link += 1
                    continue

                reason = relevance_reason(job)
                if reason:
                    reasons[reason] = reasons.get(reason, 0) + 1
                    continue

                discovered_ids.add(job_id)
                candidates.append((
                    job["published"] or datetime.min.replace(tzinfo=timezone.utc),
                    job, job_id,
                ))
                accepted += 1

            reason_text = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
            print(
                f"{source}: {accepted} new matching job(s); "
                f"seen={skipped_seen}, old={skipped_old}, no_link={skipped_no_link}; "
                f"rejected: {reason_text}"
            )
        except Exception as exc:
            print(f"Warning: failed to read {source}: {exc}")

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:MAX_MESSAGES_PER_RUN]


def test_telegram():
    chat_id = discover_chat_id()
    telegram_request("sendMessage", {
        "chat_id": chat_id,
        "text": "✅ Android Job Scout Telegram test: connection OK.",
    })
    print("Telegram test message sent successfully.")
    print(f"Discovered private chat ID: {chat_id}")


def main():
    if os.getenv("TEST_TELEGRAM", "").strip().lower() == "true":
        test_telegram()
        return

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
