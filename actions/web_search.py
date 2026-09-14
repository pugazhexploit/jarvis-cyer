#web_search.py
import json
import sys
import threading
import time
from pathlib import Path

from core.search_store import search_store

# ── Gemini grounding quota circuit breaker ────────────────────────────────────
# The google_search grounding tool has its own small quota, separate from plain
# generation.  Once it is spent every call returns 429 — so retrying it at the
# top of every search only adds a dead round-trip before the DDG fallback runs.
# After a quota error, skip Gemini entirely for a cooldown period.
_QUOTA_COOLDOWN_SEC  = 900          # 15 minutes
_quota_blocked_until = 0.0
_quota_lock          = threading.Lock()


def _gemini_available() -> bool:
    with _quota_lock:
        return time.monotonic() >= _quota_blocked_until


def _note_gemini_error(exc: Exception) -> None:
    """Trip the breaker when the error is a quota / rate-limit rejection."""
    global _quota_blocked_until
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        with _quota_lock:
            already = time.monotonic() < _quota_blocked_until
            _quota_blocked_until = time.monotonic() + _QUOTA_COOLDOWN_SEC
        if not already:
            print(
                "[WebSearch] Gemini grounding quota exhausted — skipping it for "
                f"{_QUOTA_COOLDOWN_SEC // 60} min and serving results from DDG."
            )


class _QuotaCooldown(RuntimeError):
    """Raised instead of calling Gemini while the quota breaker is open."""


def _log_gemini_failure(context: str, exc: Exception) -> None:
    """Log a Gemini failure — silently when it is just the expected cooldown."""
    if isinstance(exc, _QuotaCooldown):
        return          # announced once when the breaker tripped; not a warning
    print(f"[WebSearch] ⚠️ {context} failed ({exc}) — using DDG instead")


def _run_bounded(fn, timeout: float, label: str = "task"):
    """Run fn() in a daemon thread; return its result, or None if it overruns."""
    box = [None]

    def _run():
        try:
            box[0] = fn()
        except Exception as e:
            _log_gemini_failure(label, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print(f"[WebSearch] {label} exceeded {timeout:.0f}s — moving on")
    return box[0]

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    if not _gemini_available():
        raise _QuotaCooldown("Gemini grounding is in quota cooldown")

    from google import genai

    client = genai.Client(api_key=_get_api_key())
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=query,
            config={"tools": [{"google_search": {}}]},
        )
    except Exception as e:
        _note_gemini_error(e)
        raise

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _get_ddgs():
    """
    Returns the DDGS class.  The package was renamed duckduckgo-search -> ddgs;
    the legacy package's endpoints are now rejected by DuckDuckGo (news() gets a
    403 Ratelimit, text() silently returns zero results), so warn loudly if we
    end up on it instead of failing in silence.
    """
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        print(
            "[WebSearch] ⚠️ Using the deprecated 'duckduckgo-search' package — "
            "DuckDuckGo blocks its endpoints, so every search will come back "
            "empty.  Fix with:  pip install -U ddgs"
        )
        return DDGS


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("href",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG text() failed: {e}")
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
    # Also covers the legacy-package case, where news() returns an empty list
    # instead of raising.
    if not results:
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=f"Current cybersecurity news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini search", e)
        results = _ddg_search(query)
        return _format_ddg(query, results)


def _fetch_thehackernews(query: str = "", max_results: int = 6) -> str:
    """
    Fetches latest cyber security news directly from The Hacker News (thehackernews.com).
    Uses direct HTML scraping with official RSS feed fallback.
    """
    import urllib.request
    import xml.etree.ElementTree as ET
    import re
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    articles = []
    q = (query or "").strip().lower()
    is_generic = q in ("", "news", "today", "latest", "top world news today", "cyber security", "cybersecurity", "cybersecurity news", "cyber security news")

    # 1. Scrape thehackernews.com directly
    try:
        req = urllib.request.Request("https://thehackernews.com", headers=headers)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        posts = soup.find_all("div", class_="body-post")
        for p in posts:
            t_el = p.find("h2", class_="home-title")
            d_el = p.find("div", class_="home-desc")
            u_el = p.find("a", class_="story-link")
            if t_el:
                title = t_el.text.strip()
                desc = d_el.text.strip() if d_el else ""
                url = u_el["href"] if u_el and u_el.has_attr("href") else "https://thehackernews.com"
                if not is_generic and (q not in title.lower() and q not in desc.lower()):
                    continue
                articles.append({"title": title, "desc": desc, "url": url})
                if len(articles) >= max_results:
                    break
    except Exception as e:
        print(f"[WebSearch] [TheHackerNews] Scrape failed ({e}) - trying RSS")

    # 2. RSS fallback if direct scraping returned nothing
    if not articles:
        try:
            req = urllib.request.Request("https://feeds.feedburner.com/TheHackersNews", headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else "https://thehackernews.com"
                desc = ""
                if desc_el is not None and desc_el.text:
                    desc = re.sub(r"<[^>]+>", "", desc_el.text).strip()
                if not is_generic and (q not in title.lower() and q not in desc.lower()):
                    continue
                articles.append({"title": title, "desc": desc, "url": link})
                if len(articles) >= max_results:
                    break
        except Exception as e:
            print(f"[WebSearch] [TheHackerNews] RSS failed ({e})")

    # 3. Format results
    if articles:
        lines = ["Latest Cyber Security News from The Hacker News (thehackernews.com):\n"]
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. {a['title']}  [The Hacker News]")
            if a["desc"]:
                lines.append(f"   {a['desc'][:160]}...")
            if a["url"]:
                lines.append(f"   Source: {a['url']}")
            lines.append("")
        return "\n".join(lines).strip()

    return ""


def _news(query: str) -> str:
    """
    Exclusively returns cyber security news from The Hacker News (thehackernews.com).
    Falls back to DDG search for thehackernews.com or Gemini if direct access is down.
    """
    # 1. Direct fetch from thehackernews.com
    hn_text = _run_bounded(lambda: _fetch_thehackernews(query), timeout=6.0, label="TheHackerNews")
    if hn_text and len(hn_text) > 60:
        return hn_text

    # 2. Search specifically on thehackernews.com via DDG
    ddg_query = f"site:thehackernews.com {query}" if query else "site:thehackernews.com cybersecurity news"
    def _ddg_attempt() -> str:
        results = _ddg_news(ddg_query, max_results=6)
        if not results:
            results = _ddg_search(ddg_query, max_results=6)
        return _format_news("The Hacker News (thehackernews.com)", results)

    text = _run_bounded(_ddg_attempt, timeout=5.0, label="DDG thehackernews")
    if text and len(text) > 60 and not text.startswith("No news found"):
        return text

    # 3. Gemini fallback for thehackernews.com
    gemini_query = f"latest cybersecurity news from thehackernews.com: {query}" if query else "latest cybersecurity news headlines from thehackernews.com today"
    text = _run_bounded(
        lambda: _gemini_search(gemini_query), timeout=6.0, label="Gemini thehackernews"
    )
    if text and len(text) > 60:
        return text

    return f"No cyber security news found from thehackernews.com for: {query or 'today'}"


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        _log_gemini_failure("Gemini research", e)
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        _log_gemini_failure("Gemini price", e)
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini compare", e)

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    q_label = query or ", ".join(items)
    if not q_label and mode != "news":
        search_store.set_empty("", mode, "Please provide a search query.")
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"
    elif mode == "search" and any(k in query.lower() for k in ("news", "headline", "thehackernews", "cybersecurity")):
        mode = "news"

    if player:
        player.write_log(f"[Search:{mode}] {q_label}")

    print(f"[WebSearch] mode={mode!r}  query={query!r}")
    search_store.start_search(q_label, mode)

    try:
        if mode == "compare" and items:
            res = _compare(items, aspect)
        elif mode == "news":
            res = _news(query)
        elif mode == "research":
            res = _research(query)
        elif mode == "price":
            res = _price(query)
        else:
            res = _search(query)

        search_store.set_response(q_label, mode, res)
        return res

    except Exception as e:
        print(f"[WebSearch] All backends failed: {e}")
        err_msg = f"Search failed: {e}"
        search_store.set_error(q_label, mode, str(e))
        return err_msg
