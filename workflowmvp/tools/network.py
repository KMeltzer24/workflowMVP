"""Network-shaped tools: download, http_request, scrape_webpage, discover_urls."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from ._base import P, Tool, _BaseToolRegistry


class NetworkToolsMixin(_BaseToolRegistry):
    """HTTP-shaped primitives: pull bytes, scrape pages, discover URLs."""

    _SCRAPE_MAX_CHARS = 4000
    _SITEMAP_LOC_RE = re.compile(r"<loc[^>]*>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
    _DISCOVER_MAX_SITEMAP_LOCS = 2500
    _DISCOVER_MAX_CHILD_SITEMAPS = 8

    # ----- registration ---------------------------------------------------

    def _register_network_tools(self) -> None:
        net = "network"
        self.register_tool(Tool(
            name="download",
            description="Download content from a URL",
            function=self._download,
            category=net,
            side_effects=("network", "write"),
            parameters={
                "url": P("URL to download from", required=True),
                "output_file": P("Optional output file path"),
            },
        ))
        self.register_tool(Tool(
            name="http_request",
            description=(
                "Make an HTTP request (GET, POST, PUT, PATCH, DELETE) to any URL. "
                "Use this to call REST APIs, send webhooks, or submit forms. "
                "Supports custom headers and a JSON or text body."
            ),
            function=self._http_request,
            category=net,
            side_effects=("network",),
            parameters={
                "url": P("Target URL", required=True),
                "method": P("HTTP method: GET, POST, PUT, PATCH, DELETE (default: GET)"),
                "body": P("Request body as a dict (sent as JSON) or string (sent as text). Optional."),
                "headers": P("Extra headers as a dict (e.g. {'Authorization': 'Bearer token'}). Optional."),
                "timeout": P("Timeout in seconds (default: 30)"),
            },
        ))
        self.register_tool(Tool(
            name="scrape_webpage",
            description=(
                "Scrape content from a webpage. Pass a URL string, or a discover_urls row dict "
                "with a 'url' key (the whole entry is accepted for convenience)."
            ),
            function=self._scrape_webpage,
            category=net,
            side_effects=("network",),
            parameters={
                "url": P(
                    "URL string, or {'url': 'https://...', 'score': n} from discover_urls",
                    required=True,
                ),
                "selector": P("Optional CSS selector for targeted extraction"),
                "extract_text": P("Whether to return visible text instead of raw HTML (default: True)"),
            },
        ))
        self.register_tool(Tool(
            name="discover_urls",
            description=(
                "Find candidate URLs on a public website without deep crawling: reads sitemap.xml "
                "(and sitemap index) plus same-origin links from the given page, then ranks URLs "
                "using optional keywords (e.g. festival name words). The start_url page is always "
                "included as a candidate (so you can discover then scrape, or scrape that URL "
                "directly). On success, use the **urls** list (objects with url/score) or **urls_only** "
                "(plain strings). The **result** field is a JSON debug string — not a list of URLs."
            ),
            function=self._discover_urls,
            category=net,
            side_effects=("network",),
            parameters={
                "start_url": P("Entry URL (e.g. https://www.example.org/)", required=True),
                "keywords": P(
                    "Optional: string or list of words to rank URLs (e.g. 'dresser plans' or ['dresser', 'plans'])"
                ),
                "max_results": P("Max URLs to return (default 15, cap 50)"),
                "use_sitemap": P("If true (default), try /sitemap.xml and /sitemap_index.xml"),
                "use_page_links": P("If true (default), extract same-origin links from start_url HTML"),
            },
        ))

    # ----- implementations ------------------------------------------------

    def _download(
        self, url: str, output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            response = self._request_with_retry(url, timeout=30, attempts=3)
            if output_file:
                safe_output = self._sandbox_path(output_file)
                parent = os.path.dirname(safe_output)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(safe_output, "wb") as f:
                    f.write(response.content)
                return {"success": True, "file": safe_output, "size": len(response.content)}
            return {"success": True, "content": response.text, "size": len(response.content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _http_request(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        try:
            method = method.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
                return {"success": False, "error": f"Unsupported HTTP method: {method}"}
            req_headers = {**self._BROWSER_HEADERS, **(headers or {})}
            kwargs: Dict[str, Any] = {"timeout": timeout, "headers": req_headers}
            if body is not None:
                if isinstance(body, dict):
                    kwargs["json"] = body
                    req_headers.setdefault("Content-Type", "application/json")
                else:
                    kwargs["data"] = str(body)

            response = self._request_public_http(method, url, **kwargs)
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    result = response.json()
                except Exception:
                    result = response.text
            else:
                result = response.text
            return {
                "success": response.ok,
                "status_code": response.status_code,
                "result": result,
                "error": None if response.ok else f"HTTP {response.status_code}: {response.reason}",
                "meta": {
                    "status_code": response.status_code,
                    "url": url,
                    "method": method,
                    "headers": dict(response.headers),
                },
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _coerce_scrape_url(url: object) -> str:
        """Accept a URL string or a discover_urls row ``{'url': '...', 'score': ...}``."""
        if isinstance(url, dict):
            raw = url.get("url") or url.get("URL")
            if raw is None:
                return ""
            return str(raw).strip()
        if url is None:
            return ""
        return str(url).strip()

    def _scrape_webpage(
        self,
        url: object,
        selector: Optional[str] = None,
        extract_text: bool = True,
    ) -> Dict[str, Any]:
        """Fetch a page and return clean readable text (HTML tags stripped).

        Uses BeautifulSoup when available to extract only visible text, removing
        scripts, styles, and other noise. Falls back to raw HTML if
        BeautifulSoup is not installed. Content is truncated to keep payloads
        well inside LLM context limits.
        """
        try:
            resolved = self._coerce_scrape_url(url)
            if not resolved:
                return {
                    "success": False,
                    "error": "url is empty or missing a string 'url' field (pass a page URL or a discover_urls entry).",
                }
            response = self._request_with_retry(resolved, timeout=30, attempts=3)
            raw_html = response.text

            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(raw_html, "html.parser")
                selected = soup.select(selector) if selector else [soup]
                if selector and not selected:
                    return {
                        "success": False,
                        "error": f"No elements matched selector: {selector}",
                    }
                soup = BeautifulSoup(
                    "\n".join(str(node) for node in selected),
                    "html.parser",
                )
                for tag in soup(
                    [
                        "script", "style", "nav", "header", "footer",
                        "aside", "noscript", "iframe", "form",
                    ]
                ):
                    tag.decompose()
                if extract_text:
                    text = soup.get_text(separator="\n")
                    text = "\n".join(
                        line.strip() for line in text.splitlines() if line.strip()
                    )
                else:
                    text = str(soup)
            except ImportError:
                text = raw_html if not selector or not extract_text else raw_html

            truncated = len(text) > self._SCRAPE_MAX_CHARS
            content = text[: self._SCRAPE_MAX_CHARS] if truncated else text
            result: Dict[str, Any] = {
                "success": True,
                "content": content,
                "url": resolved,
                "meta": {
                    "url": resolved,
                    "selector": selector,
                    "extract_text": extract_text,
                    "truncated": truncated,
                    "content_length": len(text),
                },
            }
            if truncated:
                result["note"] = (
                    f"Content truncated to {self._SCRAPE_MAX_CHARS} chars "
                    f"(original: {len(text)})"
                )
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ----- discover_urls helpers -----------------------------------------

    @staticmethod
    def _discover_keyword_tokens(keywords: Optional[str]) -> List[str]:
        if not keywords or not str(keywords).strip():
            return []
        raw = re.split(r"[\s,;]+", str(keywords).lower())
        out: List[str] = []
        for t in raw:
            t = t.strip().strip("'\"")
            if len(t) >= 2:
                out.append(t)
        seen: set[str] = set()
        uniq: List[str] = []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq[:24]

    @staticmethod
    def _discover_score(url: str, link_text: str, tokens: List[str]) -> int:
        if not tokens:
            return 0
        blob = f"{url} {link_text}".lower()
        return sum(1 for t in tokens if t in blob)

    def _normalize_discover_url(self, raw: str, allowed_netloc: str) -> Optional[str]:
        raw = (raw or "").strip()
        if not raw:
            return None
        u, _frag = urldefrag(raw)
        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            return None
        if p.netloc.lower() != allowed_netloc.lower():
            return None
        path = p.path or "/"
        return urlunparse((p.scheme, p.netloc.lower(), path, "", p.query, ""))

    def _collect_sitemap_locs(self, base: str, allowed_netloc: str) -> List[str]:
        """Return page URLs from sitemap.xml, expanding sitemap index one level."""
        out: List[str] = []
        for sm_path in (f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"):
            try:
                resp = self._request_with_retry(sm_path, timeout=15, attempts=2)
            except Exception:
                continue
            body = resp.text
            locs = self._SITEMAP_LOC_RE.findall(body)
            if not locs:
                continue
            lower_head = body.lower()[:4000]
            if "sitemapindex" in lower_head:
                page_locs: List[str] = []
                for child in locs[: self._DISCOVER_MAX_CHILD_SITEMAPS]:
                    c = child.strip()
                    cp = urlparse(c)
                    if cp.netloc and cp.netloc.lower() != allowed_netloc.lower():
                        continue
                    try:
                        r2 = self._request_with_retry(c.strip(), timeout=15, attempts=2)
                        page_locs.extend(self._SITEMAP_LOC_RE.findall(r2.text))
                    except Exception:
                        continue
                    if len(page_locs) >= self._DISCOVER_MAX_SITEMAP_LOCS:
                        break
                locs = page_locs
            for loc in locs[: self._DISCOVER_MAX_SITEMAP_LOCS]:
                nu = self._normalize_discover_url(loc, allowed_netloc)
                if nu:
                    out.append(nu)
            if out:
                break
        return out

    def _collect_page_links(
        self, start_url: str, allowed_netloc: str
    ) -> List[Tuple[str, str]]:
        """Return ``(normalized_url, link_text)`` from same-origin anchors."""
        pairs: List[Tuple[str, str]] = []
        try:
            resp = self._request_with_retry(start_url, timeout=20, attempts=2)
        except Exception:
            return pairs
        html = resp.text
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                    continue
                full = urljoin(start_url, href)
                text = a.get_text(" ", strip=True)[:240]
                nu = self._normalize_discover_url(full, allowed_netloc)
                if nu:
                    pairs.append((nu, text))
        except ImportError:
            for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html, re.I):
                href = m.group(1).strip()
                if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                    continue
                full = urljoin(start_url, href)
                nu = self._normalize_discover_url(full, allowed_netloc)
                if nu:
                    pairs.append((nu, ""))
        return pairs

    @staticmethod
    def _coerce_tool_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("0", "false", "no", "off", ""):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
        return default

    def _discover_urls(
        self,
        start_url: str,
        keywords: Optional[str] = None,
        max_results: int = 15,
        use_sitemap: bool = True,
        use_page_links: bool = True,
    ) -> Dict[str, Any]:
        """Bounded URL discovery: sitemap + same-origin links, keyword-ranked."""
        try:
            use_sitemap = self._coerce_tool_bool(use_sitemap, True)
            use_page_links = self._coerce_tool_bool(use_page_links, True)
            start_url = (start_url or "").strip()
            parsed = urlparse(start_url)
            if not parsed.scheme or not parsed.netloc:
                return {
                    "success": False,
                    "error": "start_url must include scheme and host (e.g. https://www.example.org/)",
                }
            allowed_netloc = parsed.netloc.lower()
            base = f"{parsed.scheme}://{allowed_netloc}".rstrip("/")
            try:
                mr = int(max_results)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                mr = 15
            max_results = max(1, min(mr, 50))
            if isinstance(keywords, (list, tuple, set)):
                keywords = " ".join(
                    str(x).strip() for x in keywords if str(x).strip()
                ) or None
            elif keywords is not None:
                keywords = str(keywords).strip() or None
            tokens = self._discover_keyword_tokens(keywords)
            best_score: Dict[str, int] = {}

            def note(u: str, link_text: str = "") -> None:
                s = self._discover_score(u, link_text, tokens)
                if u not in best_score or s > best_score[u]:
                    best_score[u] = s

            # Always include the entry page itself. Many sites block or omit sitemaps and expose
            # few parseable <a> tags; callers still need a concrete URL to scrape.
            normalized_start = self._normalize_discover_url(start_url, allowed_netloc)
            if normalized_start:
                note(normalized_start, "")

            if use_sitemap:
                for u in self._collect_sitemap_locs(base, allowed_netloc):
                    note(u, "")
            if use_page_links:
                for u, lt in self._collect_page_links(start_url, allowed_netloc):
                    note(u, lt)

            if not best_score:
                return {
                    "success": False,
                    "error": (
                        "No same-origin URLs found (missing sitemap, blocked, or no parseable links). "
                        "Try another start_url or add an explicit page URL to the workflow step."
                    ),
                }

            ranked = sorted(best_score.items(), key=lambda kv: (-kv[1], len(kv[0])))
            top = ranked[:max_results]
            out_list = [{"url": u, "score": s} for u, s in top]
            summary = json.dumps(out_list, indent=2)
            return {
                "success": True,
                "urls": out_list,
                "urls_only": [u for u, _ in top],
                "count": len(out_list),
                "result": summary,
                "start_url": start_url,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
