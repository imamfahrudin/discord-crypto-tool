"""
Bitcoinist RSS fetch, article selection, and Pollinations summarization.

Feed parsing and the summary format follow discord-bitcoinist-ai-rss-summarizer.
The embed has no footer. Delivery is done by the cog with the bot, not a webhook.

HTTP calls use the ``requests`` package already installed for Forex and screening.
There is no separate HTTP client and no second AI client.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import feedparser
import requests

from config import NEWS_API_URL, NEWS_CONTENT_POSTFIX, NEWS_FEED_URL, NEWS_REQUEST_TIMEOUT

logger = logging.getLogger("crypto_tool.news.feed")

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
EMBED_COLOR = 9442302
AI_MODEL = "openai"
AI_SEED = 42
CONTENT_MAX_LENGTH = 6000
DESCRIPTION_MAX_LENGTH = 4096
TITLE_MAX_LENGTH = 256

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that summarizes news articles strictly in the "
    "specified format with bolded subheadings, without extra text or a title."
)
DEFAULT_USER_PROMPT = """Summarize this news article in English with the following exact format:

**Summary:**
> A brief one-paragraph summary that captures the essence of the news.

**Key Points:**
- First main point
- Second main point
- And so on (at least 3-5 key points)

Do not add a title or any other extra text. Just provide the summary and key points. Article content: {content}"""

_PROMPTS_LOADED = False
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
USER_PROMPT_TEMPLATE = DEFAULT_USER_PROMPT


def load_prompts():
    """Load the prompt files next to this module. Safe to call more than once."""
    global _PROMPTS_LOADED, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
    if _PROMPTS_LOADED:
        return
    SYSTEM_PROMPT = _read_prompt(os.path.join(MODULE_DIR, "system_prompt.txt"), DEFAULT_SYSTEM_PROMPT)
    USER_PROMPT_TEMPLATE = _read_prompt(os.path.join(MODULE_DIR, "user_prompt.txt"), DEFAULT_USER_PROMPT)
    _PROMPTS_LOADED = True


def _read_prompt(path: str, default_text: str) -> str:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read().strip()
                return text or default_text
        logger.warning("%s not found. Using default prompt.", path)
    except OSError as exc:
        logger.error("Failed to read %s: %s. Using default prompt.", path, exc)
    return default_text


def truncate_content(content: str, max_length: int = CONTENT_MAX_LENGTH) -> str:
    """Cut long article text on a sentence boundary when one is near the limit."""
    if content is None:
        return ""
    if len(content) <= max_length:
        return content

    truncated = content[:max_length]
    last_sentence_end = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_sentence_end > max_length * 0.8:
        return truncated[: last_sentence_end + 1]
    return truncated


def article_published(entry) -> datetime | None:
    """Publication time as an aware UTC datetime, or None when the feed omits it."""
    parsed = _entry_value(entry, "published_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6]).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def select_new_articles(entries, last_time: datetime) -> list:
    """Articles published strictly after ``last_time``, oldest first."""
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    chosen = []
    for entry in entries:
        published = article_published(entry)
        if published is not None and published > last_time:
            chosen.append(entry)
    chosen.sort(key=lambda entry: article_published(entry))
    return chosen


def extract_article(entry) -> dict | None:
    """Title, link, truncated body, image, and publication time for one entry."""
    published = article_published(entry)
    title = _entry_value(entry, "title")
    link = _entry_value(entry, "link")
    if published is None or not title or not link:
        return None

    content_blocks = _entry_value(entry, "content")
    raw = ""
    if content_blocks and isinstance(content_blocks, (list, tuple)) and isinstance(content_blocks[0], dict):
        raw = content_blocks[0].get("value") or ""
    if not raw:
        raw = _entry_value(entry, "description") or ""

    image_url = None
    media = _entry_value(entry, "media_content")
    if media and isinstance(media, (list, tuple)) and isinstance(media[0], dict):
        image_url = media[0].get("url")

    return {
        "title": str(title),
        "link": str(link),
        "content": truncate_content(str(raw or "")),
        "image_url": image_url,
        "published": published,
    }


def fetch_feed(feed_url: str = NEWS_FEED_URL):
    """
    Download and parse the RSS feed.

    The first attempt verifies TLS. If that fails, a second attempt skips
    certificate verification, matching the original feed fallback. The parsed
    object is returned only when feedparser produced entries or a clean parse.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; RSS-Bot/1.0)"}
    for verify in (True, False):
        try:
            if not verify:
                logger.warning("Retrying feed fetch without TLS verification")
            response = requests.get(
                feed_url,
                headers=headers,
                timeout=30,
                verify=verify,
            )
            if response.status_code != 200:
                logger.error("Feed request failed with status %s", response.status_code)
                continue
            feed = feedparser.parse(response.content)
            if getattr(feed, "entries", None) or not getattr(feed, "bozo", False):
                return feed
            logger.warning("Feed parse warning: %s", getattr(feed, "bozo_exception", "unknown"))
        except requests.RequestException as exc:
            logger.error("Feed request failed (verify=%s): %s", verify, exc)
    return None


def articles_since(last_time: datetime, feed_url: str = NEWS_FEED_URL) -> list[dict] | None:
    """
    New articles since ``last_time``.

    ``None`` means the feed could not be fetched. An empty list means the feed
    was read and nothing new was published.
    """
    feed = fetch_feed(feed_url)
    if feed is None:
        return None
    entries = getattr(feed, "entries", None) or []
    articles = []
    for entry in select_new_articles(entries, last_time):
        article = extract_article(entry)
        if article is not None:
            articles.append(article)
    return articles


def summarize_article(content: str) -> str | None:
    """Ask Pollinations for the summary. None when the API call fails."""
    load_prompts()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(content=content)},
    ]
    payload = {"model": AI_MODEL, "messages": messages, "seed": AI_SEED}
    try:
        response = requests.post(
            NEWS_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=NEWS_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Summary API request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.error("Summary API status %s: %s", response.status_code, response.text[:300])
        return None

    try:
        result = response.json()
    except ValueError as exc:
        logger.error("Summary API returned invalid JSON: %s", exc)
        return None

    summary = (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "Failed to get summary.")
    )
    if "---" in summary:
        summary = summary.split("---")[0].strip()
    return summary


def build_embed_dict(article: dict, summary: str) -> dict:
    """Discord embed payload. No footer and no webhook fields."""
    description = summary or ""
    if NEWS_CONTENT_POSTFIX:
        description = f"{description}\n\n{NEWS_CONTENT_POSTFIX}"
    if len(description) > DESCRIPTION_MAX_LENGTH:
        description = description[: DESCRIPTION_MAX_LENGTH - 1] + "…"

    title = article["title"]
    if len(title) > TITLE_MAX_LENGTH:
        title = title[: TITLE_MAX_LENGTH - 1] + "…"

    embed = {
        "title": title,
        "url": article["link"],
        "description": description,
        "color": EMBED_COLOR,
        "timestamp": article["published"].isoformat(),
    }
    if article.get("image_url"):
        embed["image"] = {"url": article["image_url"]}
    return embed


def _entry_value(entry, key: str, default=None):
    if isinstance(entry, dict):
        return entry.get(key, default)
    getter = getattr(entry, "get", None)
    if callable(getter):
        try:
            value = getter(key, default)
        except TypeError:
            value = getter(key)
        return default if value is None else value
    return getattr(entry, key, default)
