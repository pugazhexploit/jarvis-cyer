"""
core/search_store.py — State / Store for JARVIS Web Search Lifecycle.

Trace flow:
  Web Search → Search Response → State/Store → Dashboard UI

Manages:
  - Loading state
  - Empty results
  - Search errors
  - Multiple results
  - Structured fields: Title, URL, snippet, and source
"""

from __future__ import annotations

import html
import re
import threading
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse


def parse_search_response(raw_text: str, query: str = "") -> tuple[str, list[dict], str]:
    """
    Parses any search response (from DDG, Gemini, The Hacker News, RSS)
    into (status, results_list, error_or_empty_msg).
    
    Each result dict contains:
      - title: str
      - url: str
      - snippet: str
      - source: str
    """
    text = (raw_text or "").strip()
    if not text:
        return "empty", [], f"No results returned for query: '{query}'" if query else "No results returned."

    # Error detection
    if text.startswith("Search failed:") or text.startswith("Error:"):
        return "error", [], text

    # Empty detection
    if any(text.startswith(prefix) for prefix in [
        "No results", "No news found", "Please provide", "No cyber security news found",
    ]):
        return "empty", [], text

    items: list[dict] = []

    # 1. Check for numbered list format: e.g. "1. Title\n   Snippet\n   Source: URL"
    blocks = re.split(r'\n(?=\d+[\.\)])', text)
    for b in blocks:
        b = b.strip()
        m = re.match(r'^\d+[\.\)]\s*(.+)', b, re.DOTALL)
        if not m:
            continue
        body = m.group(1).strip()
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        if not lines:
            continue
        title_line = lines[0]

        # Extract [Source] badge from title if present
        src = ""
        src_match = re.search(r'\[([^\]]+)\]\s*$', title_line)
        if src_match:
            src = src_match.group(1).strip()
            title = title_line[:src_match.start()].strip()
        else:
            title = title_line

        url = ""
        snippet_lines = []
        for l in lines[1:]:
            if re.match(r'^(Source|URL|Link):\s*(https?://\S+)', l, re.IGNORECASE):
                url_match = re.search(r'https?://\S+', l)
                if url_match:
                    url = url_match.group(0).rstrip('.)')
            elif l.startswith("http://") or l.startswith("https://"):
                url = l.rstrip('.)')
            else:
                snippet_lines.append(l)

        # Fallback source from URL domain
        if not src and url:
            try:
                domain = urlparse(url).netloc.removeprefix("www.")
                if domain:
                    src = domain
            except Exception:
                src = "Web"

        snippet = " ".join(snippet_lines).strip()
        items.append({
            "title": title or (query or "Result"),
            "url": url,
            "snippet": snippet,
            "source": src or "Web",
        })

    if items:
        return "success", items, ""

    # 2. Check for markdown link format: e.g. [Title](URL) - Snippet or • Title: URL
    md_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', text)
    if md_links:
        for title, u in md_links:
            try:
                src = urlparse(u).netloc.removeprefix("www.")
            except Exception:
                src = "Web"
            items.append({
                "title": title.strip(),
                "url": u.strip(),
                "snippet": "",
                "source": src or "Web",
            })
        if items:
            return "success", items, ""

    # 3. Fallback for raw text (e.g. Gemini grounded paragraph answers)
    urls = re.findall(r'https?://[^\s\)]+', text)
    first_url = urls[0].rstrip('.)') if urls else ""
    src = "Google Gemini"
    if first_url:
        try:
            domain = urlparse(first_url).netloc.removeprefix("www.")
            if domain:
                src = domain
        except Exception:
            pass

    items.append({
        "title": query or "Web Intelligence Overview",
        "url": first_url,
        "snippet": text[:2000],
        "source": src,
    })
    return "success", items, ""


class SearchStore:
    """
    Central state store for Web Search requests, active loading state,
    and structured responses.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []
        self._current: dict = {
            "status": "idle",       # "idle" | "loading" | "success" | "empty" | "error"
            "query": "",
            "mode": "search",
            "results": [],          # list of {title, url, snippet, source}
            "raw_text": "",
            "error": None,
            "timestamp": "",
        }
        self._history: list[dict] = []

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """Register a listener called synchronously or asynchronously on state changes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify(self, state: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(state)
            except Exception as e:
                print(f"[SearchStore] Listener error: {e}")

    def start_search(self, query: str, mode: str = "search") -> dict:
        """Transition state to 'loading'."""
        with self._lock:
            self._current = {
                "status": "loading",
                "query": query.strip(),
                "mode": mode.strip().lower(),
                "results": [],
                "raw_text": "",
                "error": None,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            state = dict(self._current)
        self._notify(state)
        return state

    def set_response(self, query: str, mode: str, raw_response: str) -> dict:
        """Process search response and transition state to success, empty, or error."""
        status, results, msg = parse_search_response(raw_response, query)
        with self._lock:
            self._current = {
                "status": status,
                "query": query.strip(),
                "mode": mode.strip().lower(),
                "results": results,
                "raw_text": raw_response or "",
                "error": msg if status == "error" else None,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            if status == "empty" and not self._current.get("error"):
                self._current["error"] = msg
            state = dict(self._current)
            self._history.append(state)
            if len(self._history) > 50:
                self._history.pop(0)
        self._notify(state)
        return state

    def set_error(self, query: str, mode: str, error_msg: str) -> dict:
        """Explicitly set an error state."""
        with self._lock:
            self._current = {
                "status": "error",
                "query": query.strip(),
                "mode": mode.strip().lower(),
                "results": [],
                "raw_text": "",
                "error": error_msg or "Search failed",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            state = dict(self._current)
            self._history.append(state)
        self._notify(state)
        return state

    def set_empty(self, query: str, mode: str = "search", message: str = "") -> dict:
        """Explicitly set an empty state."""
        with self._lock:
            self._current = {
                "status": "empty",
                "query": query.strip(),
                "mode": mode.strip().lower(),
                "results": [],
                "raw_text": "",
                "error": message or f"No results found for: '{query}'",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            state = dict(self._current)
            self._history.append(state)
        self._notify(state)
        return state

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._current)

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def to_html(self, state: dict | None = None) -> str:
        """
        Renders rich styled HTML for the JARVIS ContentPanel display.
        Uses high-tech cyber styling matching the Iron Man / JARVIS HUD palette.
        """
        s = state or self.get_state()
        st = s.get("status", "idle")
        query = html.escape(s.get("query", ""))
        mode = html.escape(s.get("mode", "search").upper())
        timestamp = html.escape(s.get("timestamp", ""))

        if st == "loading":
            return f"""
            <div style="font-family:'Courier New',Consolas,monospace; padding:10px; color:#e0f7fa;">
                <div style="color:#00ffff; font-weight:bold; font-size:12px; margin-bottom:6px; letter-spacing:1px;">
                    ◈ SEARCHING REAL-TIME WEB INTELLIGENCE...
                </div>
                <div style="color:#80deea; font-size:11px; margin-bottom:12px;">
                    Query: <strong style="color:#ffffff;">"{query}"</strong>  ·  Mode: [{mode}]  ·  {timestamp}
                </div>
                <div style="background:#0a192f; border:1px solid #00ffff; padding:10px; border-radius:4px; color:#4dd0e1; font-size:11px;">
                    <span style="color:#00ffff; font-weight:bold;">⚡ INITIALIZING GROUNDED QUERIES...</span><br>
                    Scanning live DuckDuckGo and internet intelligence feeds.<br>
                    Results will populate automatically when received.
                </div>
            </div>
            """

        if st == "error":
            err = html.escape(s.get("error") or "Unknown search error occurred.")
            return f"""
            <div style="font-family:'Courier New',Consolas,monospace; padding:10px; color:#ffcdd2;">
                <div style="color:#ff5252; font-weight:bold; font-size:12px; margin-bottom:6px; letter-spacing:1px;">
                    ✕ WEB SEARCH ERROR
                </div>
                <div style="color:#ff8a80; font-size:11px; margin-bottom:10px;">
                    Query: <strong style="color:#ffffff;">"{query}"</strong>  ·  Mode: [{mode}]
                </div>
                <div style="background:#2b0e12; border:1px solid #ff5252; padding:10px; border-radius:4px; color:#ff8a80; font-size:11px;">
                    <strong>Details:</strong> {err}<br>
                    <span style="color:#e0e0e0; font-size:10px;">Please check internet connectivity or verify query syntax.</span>
                </div>
            </div>
            """

        if st == "empty":
            msg = html.escape(s.get("error") or f"No results found for: '{query}'")
            return f"""
            <div style="font-family:'Courier New',Consolas,monospace; padding:10px; color:#fff9c4;">
                <div style="color:#ffd700; font-weight:bold; font-size:12px; margin-bottom:6px; letter-spacing:1px;">
                    ⚠ NO SEARCH RESULTS FOUND
                </div>
                <div style="color:#fff59d; font-size:11px; margin-bottom:10px;">
                    Query: <strong style="color:#ffffff;">"{query}"</strong>  ·  Mode: [{mode}]
                </div>
                <div style="background:#1f1c08; border:1px solid #ffd700; padding:10px; border-radius:4px; color:#fff176; font-size:11px;">
                    {msg}<br><br>
                    <span style="color:#cccccc; font-size:10px;">• Try broader keywords or alternate search phrasing.<br>• For cybersecurity headlines, verify specific CVE numbers or vendor names.</span>
                </div>
            </div>
            """

        # Success state: render multiple results with Title, URL, Snippet, Source
        results = s.get("results", [])
        if not results:
            raw = html.escape(s.get("raw_text", ""))
            return f"""
            <div style="font-family:'Courier New',Consolas,monospace; padding:8px; color:#e0f7fa;">
                <div style="color:#00ffff; font-weight:bold; font-size:11px; margin-bottom:8px;">
                    ◈ SEARCH RESULTS: "{query}" [{mode}]
                </div>
                <pre style="white-space:pre-wrap; color:#b2ebf2; font-size:10px;">{raw}</pre>
            </div>
            """

        cards_html = []
        for idx, item in enumerate(results, 1):
            t = html.escape(item.get("title") or "Untitled")
            u = item.get("url", "").strip()
            snip = html.escape(item.get("snippet") or "")
            src = html.escape(item.get("source") or "Web")

            link_html = f'<a href="{u}" style="color:#00ffff; text-decoration:underline;">{html.escape(u)}</a>' if u else '<span style="color:#78909c;">Direct Answer</span>'

            cards_html.append(f"""
            <div style="background:#09131e; border:1px solid #1a3650; border-left:3px solid #00ffff; padding:8px 10px; margin-bottom:8px; border-radius:3px;">
                <div style="display:flex; align-items:center; margin-bottom:4px;">
                    <span style="color:#00ffff; font-weight:bold; font-size:11px;">{idx}. {t}</span>
                    <span style="color:#ffd700; font-size:9px; margin-left:8px; background:#1e293b; padding:1px 5px; border-radius:3px;">[{src}]</span>
                </div>
                <div style="color:#cfd8dc; font-size:10px; line-height:1.4; margin-bottom:5px;">
                    {snip}
                </div>
                <div style="font-size:9px; color:#90a4ae;">
                    Source: {link_html}
                </div>
            </div>
            """)

        all_cards = "".join(cards_html)
        return f"""
        <div style="font-family:'Courier New',Consolas,monospace; padding:6px; color:#e0f7fa;">
            <div style="color:#00ffff; font-weight:bold; font-size:11px; margin-bottom:8px; letter-spacing:0.5px; border-bottom:1px solid #1a3650; padding-bottom:4px;">
                ◈ SEARCH RESULTS ({len(results)})  ·  QUERY: "{query}"  ·  [{mode}]
            </div>
            {all_cards}
        </div>
        """


# Global singleton instance
search_store = SearchStore()
