"""网络搜索和新闻工具 —— 多层级搜索 + 熔断 + 网页抓取。

搜索层级（按优先级）：
  1. Tavily — AI Agent 专用搜索，国内可直接访问（需 API Key，免费 1000 次/月）
  2. 博查 AI — 国内搜索 API，支持中文搜索和摘要（需 API Key）
  3. SearXNG — 开源元搜索引擎，聚合多引擎结果（免费，需部署或公共实例）
  4. Bing CN — Bing 中国版，国内免费可用，无需 Key，解析搜索结果页
  5. Wikipedia — 免费知识搜索，无需 Key，中英文自动切换（国内可能需要代理）
  6. DuckDuckGo — 免费全文搜索（国内需要代理）
  7. Bing API — 微软搜索 API（需 API Key）
  8. News — 东方财富新闻（AkShare，仅金融领域）

增强能力：
  - web_fetch: 抓取网页正文内容，补充搜索结果
  - SearchCircuitBreaker: 熔断器，防止重复请求已失败的搜索源
"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from langchain_core.tools import tool

from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


class SearchCircuitBreaker:
    """搜索熔断器 —— 防止对已失败的搜索源重复请求。"""

    PERMANENT_ERRORS = {401, 403}
    COOLDOWN_SECONDS = 300
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self):
        self._lock = threading.Lock()
        self._source_status: dict[str, dict] = {}
        self._global_tripped = False
        self._global_trip_time = 0.0

    def record_success(self, source: str) -> None:
        with self._lock:
            if source in self._source_status:
                self._source_status[source]["consecutive_failures"] = 0

    def record_failure(self, source: str, error: Exception) -> str:
        error_code = self._extract_http_code(error)
        error_msg = str(error)

        with self._lock:
            if source not in self._source_status:
                self._source_status[source] = {
                    "consecutive_failures": 0,
                    "status": "healthy",
                    "trip_time": 0,
                }

            info = self._source_status[source]
            info["consecutive_failures"] += 1

            if error_code in self.PERMANENT_ERRORS or "PermissionDenied" in error_msg or "Unauthorized" in error_msg:
                info["status"] = "permanent"
                info["trip_time"] = time.time()
                self._check_global_trip()
                return (
                    f"⚠️ 搜索源 [{source}] 认证失败 (HTTP {error_code})，"
                    f"API Key 无效或未配置，更换搜索关键词无法解决此问题。"
                    f"请不要再次调用 web_search，改用其他工具获取信息。"
                )

            if info["consecutive_failures"] >= self.MAX_CONSECUTIVE_FAILURES:
                info["status"] = "cooldown"
                info["trip_time"] = time.time()
                self._check_global_trip()
                return (
                    f"⚠️ 搜索源 [{source}] 连续失败 {info['consecutive_failures']} 次，"
                    f"已进入冷却状态。请不要继续使用 web_search。"
                )

            return (
                f"⚠️ 搜索源 [{source}] 请求失败: {error_msg[:100]}。"
                f"可尝试其他搜索方式或使用数据库查询。"
            )

    def is_source_available(self, source: str) -> bool:
        with self._lock:
            info = self._source_status.get(source)
            if not info:
                return True
            if info["status"] == "permanent":
                return False
            if info["status"] == "cooldown":
                elapsed = time.time() - info["trip_time"]
                if elapsed > self.COOLDOWN_SECONDS:
                    info["status"] = "healthy"
                    info["consecutive_failures"] = 0
                    return True
                return False
            return True

    def is_global_tripped(self) -> bool:
        with self._lock:
            if not self._global_tripped:
                return False
            if time.time() - self._global_trip_time > self.COOLDOWN_SECONDS:
                self._global_tripped = False
                return False
            return True

    def get_status_summary(self) -> str:
        with self._lock:
            if not self._source_status:
                return "搜索服务状态: 正常"
            lines = ["搜索服务状态:"]
            for source, info in self._source_status.items():
                status_emoji = {"healthy": "✅", "cooldown": "⏳", "permanent": "❌"}
                emoji = status_emoji.get(info["status"], "❓")
                lines.append(f"  {emoji} {source}: {info['status']} (连续失败: {info['consecutive_failures']})")
            return "\n".join(lines)

    def _check_global_trip(self) -> None:
        permanent_sources = [
            s for s, info in self._source_status.items()
            if info["status"] == "permanent"
        ]
        if len(permanent_sources) >= 2:
            self._global_tripped = True
            self._global_trip_time = time.time()

    @staticmethod
    def _extract_http_code(error: Exception) -> int:
        error_str = str(error)
        for code in [401, 403, 429, 500, 502, 503]:
            if str(code) in error_str:
                return code
        return 0


_search_breaker = SearchCircuitBreaker()


def _is_auth_error(error: Exception) -> bool:
    error_str = str(error)
    return any(marker in error_str for marker in ["401", "403", "PermissionDenied", "Unauthorized", "Forbidden"])


def _get_proxy_url() -> str:
    proxy_url = getattr(settings, "search_proxy", None) or ""
    if proxy_url:
        return proxy_url
    import os
    for env_var in ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]:
        proxy_url = os.environ.get(env_var, "")
        if proxy_url:
            return proxy_url
    return ""


def _urlopen_with_proxy(url: str, timeout: int = 15, headers: dict | None = None) -> urllib.request.urlopen:
    proxy_url = _get_proxy_url()
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if headers:
        default_headers.update(headers)
    req = urllib.request.Request(url, headers=default_headers)
    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _try_tavily_search(query: str, num: int) -> str | None:
    """Tavily 搜索 —— AI Agent 专用搜索 API，国内可直接访问，返回结构化高质量结果。"""
    api_key = getattr(settings, "tavily_api_key", None) or ""
    if not api_key:
        return None

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=num, search_depth="advanced")

        lines = [f"Tavily 搜索结果（关键词: {query}）：", ""]
        for i, result in enumerate(response.get("results", [])[:num], 1):
            title = result.get("title", "")
            content = result.get("content", "")
            url = result.get("url", "")
            score = result.get("score", 0)

            lines.append(f"{i}. {title}")
            if content:
                lines.append(f"   {content[:500]}")
            if url:
                lines.append(f"   链接: {url}")
            if score:
                lines.append(f"   相关度: {score:.0%}")
            lines.append("")

        if len(response.get("results", [])) == 0:
            return None

        return "\n".join(lines)

    except ImportError:
        logger.debug("[Tavily] tavily-python 未安装，跳过")
        return None
    except Exception as e:
        error_str = str(e)
        is_quota = (
            "429" in error_str
            or "quota" in error_str.lower()
            or "rate" in error_str.lower()
            or "limit" in error_str.lower()
        )
        if is_quota:
            logger.warning(f"[Tavily] 配额耗尽或限流: {e}")
            raise
        logger.warning(f"[Tavily] 搜索失败: {e}")
        if _is_auth_error(e):
            raise
        return None


def _try_bocha_search(query: str, num: int) -> str | None:
    """博查 AI 搜索 —— 国内搜索 API，支持中文搜索和智能摘要。"""
    api_key = getattr(settings, "bocha_api_key", None) or ""
    if not api_key:
        return None

    try:
        url = "https://api.bochaai.com/v1/web-search"
        payload = json.dumps({
            "query": query,
            "count": num,
            "summary": True,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
        if not web_pages:
            return None

        lines = [f"博查搜索结果（关键词: {query}）：", ""]
        for i, page in enumerate(web_pages[:num], 1):
            name = page.get("name", "")
            snippet = page.get("snippet", "")
            page_url = page.get("url", "")
            summary = page.get("summary", "")

            lines.append(f"{i}. {name}")
            if summary:
                lines.append(f"   摘要: {summary[:500]}")
            elif snippet:
                lines.append(f"   {snippet[:400]}")
            if page_url:
                lines.append(f"   链接: {page_url}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[博查] 搜索失败: {e}")
        if _is_auth_error(e):
            raise
        return None


_SEARXNG_INSTANCES = [
    "https://search.sapti.me",
    "https://searx.be",
    "https://search.bus-hit.me",
    "https://searxng.ch",
    "https://search.mdosch.de",
]


def _try_searxng_search(query: str, num: int) -> str | None:
    """SearXNG 元搜索 —— 聚合 Google/Bing/DuckDuckGo 等多个搜索引擎。"""
    custom_url = getattr(settings, "searxng_url", None) or ""
    instances = [custom_url] + _SEARXNG_INSTANCES if custom_url else _SEARXNG_INSTANCES

    for base_url in instances:
        try:
            encoded_query = urllib.parse.quote(query)

            all_results = []
            for categories in ["general", "web"]:
                url = (
                    f"{base_url}/search?q={encoded_query}"
                    f"&format=json&categories={categories}&language=zh-CN"
                )
                try:
                    with _urlopen_with_proxy(url, timeout=6) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    all_results.extend(data.get("results", []))
                    if all_results:
                        break
                except Exception:
                    continue

            seen_urls = set()
            results = []
            for r in all_results:
                r_url = r.get("url", "")
                if r_url not in seen_urls:
                    seen_urls.add(r_url)
                    results.append(r)

            if not results:
                continue

            lines = [f"搜索结果（关键词: {query}）：", ""]
            for i, r in enumerate(results[:num], 1):
                title = r.get("title", "")
                content = r.get("content", "")
                r_url = r.get("url", "")
                engine = r.get("engine", "")

                lines.append(f"{i}. {title}")
                if content:
                    lines.append(f"   {content[:400]}")
                if r_url:
                    lines.append(f"   链接: {r_url}")
                if engine:
                    lines.append(f"   来源: {engine}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            logger.debug(f"[SearXNG] {base_url} 失败: {e}")
            continue

    return None


def _try_ddgs_search(query: str, num: int) -> str | None:
    """DuckDuckGo 全文搜索 —— 免费、无需 API Key（国内可能需要代理）。"""
    try:
        from duckduckgo_search import DDGS

        proxy_url = _get_proxy_url()

        kwargs = {"timeout": 20}
        if proxy_url:
            kwargs["proxy"] = proxy_url

        with DDGS(**kwargs) as ddgs:
            results = list(ddgs.text(query, max_results=num))

        if not results:
            return None

        lines = [f"搜索结果（关键词: {query}）：", ""]
        for i, r in enumerate(results[:num], 1):
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")

            lines.append(f"{i}. {title}")
            if body:
                lines.append(f"   {body[:400]}")
            if href:
                lines.append(f"   链接: {href}")
            lines.append("")

        return "\n".join(lines)

    except ImportError:
        logger.debug("[DuckDuckGo] duckduckgo-search 未安装，跳过")
        return None
    except Exception as e:
        logger.warning(f"[DuckDuckGo] 搜索失败: {e}")
        if _is_auth_error(e):
            raise
        return None


def _try_bing_search(query: str, num: int) -> str | None:
    """Bing 搜索 API —— 需要配置 API Key。"""
    api_key = getattr(settings, "bing_api_key", None) or ""
    if not api_key:
        return None

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.bing.microsoft.com/v7.0/search?q={encoded_query}&count={num}&mkt=zh-CN"

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Ocp-Apim-Subscription-Key": api_key,
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        lines = [f"Bing 搜索结果（关键词: {query}）：", ""]
        web_pages = data.get("webPages", {}).get("value", [])
        for i, page in enumerate(web_pages[:num], 1):
            lines.append(f"{i}. {page.get('name', '')}")
            lines.append(f"   {page.get('snippet', '')[:300]}")
            lines.append(f"   链接: {page.get('url', '')}")
            lines.append("")

        if not web_pages:
            return None
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[Bing] 搜索失败: {e}")
        if _is_auth_error(e):
            raise
        return None


def _try_bing_cn_search(query: str, num: int) -> str | None:
    """Bing 中国版搜索 —— 国内免费可用，无需 API Key，解析搜索结果页。"""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://cn.bing.com/search?q={encoded_query}&count={num}&setlang=zh-CN"

        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        results = _parse_bing_cn_html(html)
        if not results:
            return None

        lines = [f"Bing 搜索结果（关键词: {query}）：", ""]
        for i, r in enumerate(results[:num], 1):
            lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:400]}")
            if r.get("url"):
                lines.append(f"   链接: {r['url']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[BingCN] 搜索失败: {e}")
        return None


def _parse_bing_cn_html(html: str) -> list[dict]:
    """解析 Bing CN 搜索结果页 HTML，提取标题、摘要、链接。"""
    results = []

    algo_blocks = re.findall(
        r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
        html, re.DOTALL,
    )

    for block in algo_blocks:
        title = ""
        url = ""
        snippet = ""

        h2_match = re.search(
            r'<h2[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            block, re.DOTALL,
        )
        if h2_match:
            url = h2_match.group(1)
            title = re.sub(r"<[^>]+>", "", h2_match.group(2)).strip()
            title = title.replace("&#0183;", "·").replace("&ensp;", " ").replace("&#183;", "·")

        caption_match = re.search(
            r'<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>',
            block, re.DOTALL,
        )
        if caption_match:
            snippet = re.sub(r"<[^>]+>", "", caption_match.group(1)).strip()
            snippet = snippet.replace("&#0183;", "·").replace("&ensp;", " ").replace("&#183;", "·")

        if title:
            results.append({"title": title, "snippet": snippet, "url": url})

    if results:
        return results

    h2_links = re.findall(
        r'<h2[^>]*>.*?<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>',
        html, re.DOTALL,
    )
    for url, raw_title in h2_links:
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        title = title.replace("&#0183;", "·").replace("&ensp;", " ").replace("&#183;", "·")
        if title and "bing.com" not in url:
            results.append({"title": title, "snippet": "", "url": url})

    return results


def _try_wikipedia_search(query: str, num: int) -> str | None:
    """Wikipedia 搜索 —— 免费、无需 Key，适合知识类查询。"""
    try:
        encoded_query = urllib.parse.quote(query)
        url = (
            f"https://zh.wikipedia.org/w/api.php"
            f"?action=query&list=search&srsearch={encoded_query}"
            f"&srlimit={num}&format=json&utf8=1"
        )

        with _urlopen_with_proxy(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            url_en = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=query&list=search&srsearch={encoded_query}"
                f"&srlimit={num}&format=json&utf8=1"
            )
            with _urlopen_with_proxy(url_en, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            search_results = data.get("query", {}).get("search", [])

        if not search_results:
            return None

        lines = [f"Wikipedia 搜索结果（关键词: {query}）：", ""]
        for i, r in enumerate(search_results[:num], 1):
            title = r.get("title", "")
            snippet = re.sub(r"<[^>]+>", "", r.get("snippet", ""))

            lines.append(f"{i}. {title}")
            if snippet:
                lines.append(f"   {snippet[:400]}")
            if title:
                lines.append(f"   链接: https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"[Wikipedia] 搜索失败: {e}")
        return None


def _try_news_search(query: str, num: int) -> str | None:
    """东方财富新闻搜索 —— 仅限金融/股票领域。"""
    try:
        from alpha_agent.domain.market.providers.akshare_provider import AkShareProvider

        provider = AkShareProvider()
        ak = provider._ensure_ak()

        df = provider._safe_call(ak.stock_news_em, symbol=query)
        if df is None or df.empty:
            return None

        lines = [f"新闻搜索结果（关键词: {query}）：", ""]
        for i, (_, row) in enumerate(df.head(num).iterrows(), 1):
            title = str(row.get("标题", row.iloc[0] if len(df.columns) > 0 else ""))
            content = str(row.get("内容", ""))[:200]
            date = str(row.get("发布时间", ""))
            lines.append(f"{i}. {title}")
            if content:
                lines.append(f"   {content}")
            if date:
                lines.append(f"   时间: {date}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[News] 搜索失败: {e}")
        return None


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """通过互联网搜索获取最新信息。

    搜索策略：Tavily → 博查AI → SearXNG → Bing CN → Wikipedia → DuckDuckGo → Bing API → 新闻
    如果搜索结果不够详细，可以用 web_fetch 抓取具体网页的完整内容。

    何时使用：
    - 用户问的是最新的新闻、事件、政策
    - 实时行情、最新价格
    - 不确定的知识、数据
    - 需要最新的财经资讯、公司公告
    - 数据仓库里查不到的数据
    """
    try:
        if num_results > 10:
            num_results = 10
        if num_results < 1:
            num_results = 1

        if _search_breaker.is_global_tripped():
            logger.warning("[web_search] 全局熔断中，跳过搜索")
            return (
                "⚠️ web_search 当前不可用（搜索源均失败），请不要再调用此工具。\n"
                "替代方案：\n"
                "1. 使用 execute_code + SQL 查询数据库中的历史数据\n"
                "2. 使用 get_database_schema 了解可查询的数据表\n"
                "3. 基于已有信息直接回答，并说明数据来源限制"
            )

        logger.info(f"[web_search] 搜索: {query} (num={num_results})")

        searchers = [
            ("Tavily", _try_tavily_search),
            ("博查AI", _try_bocha_search),
            ("SearXNG", _try_searxng_search),
            ("BingCN", _try_bing_cn_search),
            ("Wikipedia", _try_wikipedia_search),
            ("DuckDuckGo", _try_ddgs_search),
            ("Bing", _try_bing_search),
            ("News", _try_news_search),
        ]

        failure_messages = []
        for source_name, searcher in searchers:
            if not _search_breaker.is_source_available(source_name):
                logger.info(f"[web_search] 跳过已熔断的搜索源: {source_name}")
                continue

            try:
                result = searcher(query, num_results)
                if result:
                    _search_breaker.record_success(source_name)
                    result += (
                        "\n💡 以上为搜索摘要，如果需要更详细的内容，"
                        "可以使用 web_fetch 工具抓取上述链接的完整网页内容。"
                    )
                    return result
            except Exception as e:
                msg = _search_breaker.record_failure(source_name, e)
                failure_messages.append(msg)
                logger.warning(f"[{source_name}] 搜索失败: {e}")
                continue

        if _search_breaker.is_global_tripped():
            return (
                "⚠️ web_search 所有搜索源均已失败，此工具暂时不可用。\n"
                "请不要再调用 web_search，改用以下方式获取信息：\n"
                "1. 使用 execute_code + SQL 查询数据库\n"
                "2. 使用 get_database_schema 了解数据结构\n"
                "3. 基于已有信息直接回答"
            )

        if failure_messages:
            permanent = any("认证失败" in m or "API Key" in m for m in failure_messages)
            if permanent:
                return (
                    "⚠️ web_search 认证失败，API Key 无效或未配置。\n"
                    "更换搜索关键词无法解决此问题，请不要再调用 web_search。\n"
                    "替代方案：使用 execute_code 查询数据库，或基于已有信息回答。"
                )
            return (
                "搜索暂时不可用：\n"
                + "\n".join(failure_messages)
                + "\n\n建议：尝试使用 execute_code 查询数据库获取信息。"
            )

        return (
            f"搜索无结果（关键词: {query}）。\n"
            "建议：\n"
            "1. 换一个更具体的关键词\n"
            "2. 使用 web_fetch 抓取相关网页内容\n"
            "3. 使用 execute_code 查询数据库"
        )

    except Exception as e:
        logger.error(f"[web_search] 搜索失败: {e}")
        return f"搜索失败: {e}"


_FETCH_BREAKER = SearchCircuitBreaker()

_FETCH_RETRYABLE_ERRORS = {
    "timeout", "timed out", "connection", "reset", "refused",
    "network", "unreachable", "resolve", "eof", "broken pipe",
    "502", "503", "504",
}

_FETCH_MAX_RETRIES = 3
_FETCH_BASE_DELAY = 1.5
_FETCH_MAX_DELAY = 15.0


def _is_fetch_retryable(error: Exception) -> bool:
    error_str = str(error).lower()
    return any(p in error_str for p in _FETCH_RETRYABLE_ERRORS)


def _fetch_with_retry(url: str, timeout: int = 15, headers: dict | None = None) -> tuple[bytes, str]:
    last_error = None
    for attempt in range(_FETCH_MAX_RETRIES):
        try:
            with _urlopen_with_proxy(url, timeout=timeout, headers=headers) as resp:
                raw = resp.read()
            content_type = ""
            if hasattr(resp, "headers"):
                content_type = resp.headers.get("Content-Type", "")
            return raw, content_type
        except Exception as e:
            last_error = e
            if not _is_fetch_retryable(e):
                raise
            if attempt < _FETCH_MAX_RETRIES - 1:
                import random as _rnd
                delay = min(
                    _FETCH_BASE_DELAY * (2 ** attempt) + _rnd.uniform(0, 1.0),
                    _FETCH_MAX_DELAY,
                )
                logger.warning(
                    f"[web_fetch] 请求失败 (第 {attempt + 1}/{_FETCH_MAX_RETRIES} 次), "
                    f"{delay:.1f}s 后重试: {e}"
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"[web_fetch] 重试 {_FETCH_MAX_RETRIES} 次全部失败: {e}"
                )
                raise
    raise last_error


@tool
def web_fetch(url: str, max_length: int = 5000) -> str:
    """抓取网页正文内容，用于深入了解搜索结果中的链接。

    搜索返回的只是摘要，使用 web_fetch 可以获取完整内容。
    适合：公司公告、新闻全文、技术文档、研究报告等。

    使用场景：
    - web_search 返回了相关链接，但摘要信息不够详细
    - 需要获取公告、新闻、报告的完整正文
    - 验证搜索结果中的关键信息

    Args:
        url: 要抓取的网页 URL
        max_length: 返回内容的最大字符数（默认 5000）
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return f"无效的 URL: {url}"

    if parsed.scheme not in ("http", "https"):
        return f"不支持的协议: {parsed.scheme}，仅支持 http/https"

    domain = parsed.netloc.split(":")[0]
    if _FETCH_BREAKER.is_source_available(domain) is False:
        return (
            f"⚠️ 域名 {domain} 近期抓取连续失败，暂时不可用。\n"
            "建议：稍后再试，或使用 web_search 搜索其他来源。"
        )

    try:
        logger.info(f"[web_fetch] 抓取: {url}")

        raw, content_type = _fetch_with_retry(url, timeout=15, headers={
            "Accept": "text/html,application/xhtml+xml,application/pdf",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        if "application/pdf" in content_type or raw[:4] == b"%PDF":
            return (
                f"⚠️ 该链接是 PDF 文件，无法直接提取文本内容: {url}\n"
                "建议：使用 execute_code 工具下载 PDF 并用 PyPDF2 提取文本。"
            )

        for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                html = raw.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            html = raw.decode("utf-8", errors="replace")

        text = _html_to_text(html)

        if len(text) > max_length:
            text = text[:max_length] + f"\n\n... (已截断，原文共 {len(text)} 字符，可增大 max_length 获取更多)"

        if not text.strip():
            _FETCH_BREAKER.record_failure(domain, ValueError("网页内容为空"))
            return f"网页内容为空: {url}"

        _FETCH_BREAKER.record_success(domain)
        return f"网页内容 ({url}):\n\n{text}"

    except urllib.error.HTTPError as e:
        _FETCH_BREAKER.record_failure(domain, e)
        if e.code in (401, 403):
            return (
                f"⚠️ 网页拒绝访问 (HTTP {e.code}): {url}\n"
                "该网站需要认证或有访问限制，更换 URL 或使用 web_search 搜索其他来源。"
            )
        if e.code == 404:
            return f"网页不存在 (HTTP 404): {url}"
        if e.code == 429:
            return (
                f"⚠️ 请求过于频繁 (HTTP 429): {url}\n"
                "该网站限流，请稍后再试或使用 web_search 搜索其他来源。"
            )
        if e.code >= 500:
            return (
                f"⚠️ 服务器错误 (HTTP {e.code}): {url}\n"
                "目标服务器暂时不可用，建议稍后重试或使用 web_search 搜索其他来源。"
            )
        return f"网页抓取失败 (HTTP {e.code}): {e}"
    except urllib.error.URLError as e:
        _FETCH_BREAKER.record_failure(domain, e)
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            return (
                f"⚠️ 网页请求超时: {url}\n"
                "目标网站响应过慢，建议使用 web_search 搜索其他来源。"
            )
        if "refused" in reason.lower() or "reset" in reason.lower():
            return (
                f"⚠️ 连接被拒绝: {url}\n"
                "目标网站拒绝连接，可能已下线或有地域限制，建议使用 web_search 搜索其他来源。"
            )
        return f"网页抓取失败: {reason}"
    except TimeoutError:
        _FETCH_BREAKER.record_failure(domain, TimeoutError("请求超时"))
        return (
            f"⚠️ 网页请求超时: {url}\n"
            "目标网站响应过慢，建议使用 web_search 搜索其他来源。"
        )
    except Exception as e:
        _FETCH_BREAKER.record_failure(domain, e)
        if _is_auth_error(e):
            return (
                f"⚠️ 认证失败: {url}\n"
                "该网站需要认证，请不要再次尝试 web_fetch 该 URL。"
            )
        logger.warning(f"[web_fetch] 抓取失败: {e}")
        return f"网页抓取失败: {e}"


def _html_to_text(html: str) -> str:
    """将 HTML 转换为纯文本，提取正文内容。"""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)

    for tag in ["h1", "h2", "h3", "h4", "p", "li", "tr", "div"]:
        html = re.sub(f"<{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(f"</{tag}>", "\n", html, flags=re.IGNORECASE)

    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)

    html = html.replace("&nbsp;", " ")
    html = html.replace("&amp;", "&")
    html = html.replace("&lt;", "<")
    html = html.replace("&gt;", ">")
    html = html.replace("&quot;", '"')
    html = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), html)

    lines = []
    for line in html.split("\n"):
        stripped = line.strip()
        if stripped:
            lines.append(stripped)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def get_web_tools() -> list:
    return [web_search, web_fetch]
