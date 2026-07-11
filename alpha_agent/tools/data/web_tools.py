"""网络搜索和新闻工具"""
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool

from alpha_agent.utils.logger import logger


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """通过互联网搜索获取最新信息。
    当遇到以下情况时，优先使用搜索工具：
    - 用户问的是最新的新闻、事件、政策
    - 实时行情、最新价格
    - 不确定的知识、数据
    - 需要最新的财经资讯、公司公告
    - 数据仓库里查不到的数据
    - 宏观经济数据、政策变化
    - 公司最新动态、新闻
    """
    try:
        if num_results > 10:
            num_results = 10
        if num_results < 1:
            num_results = 1

        logger.info(f"[web_search] 搜索: {query} (num={num_results})")

        for searcher in [_try_bing_search, _try_duckduckgo_search, _try_news_search]:
            try:
                result = searcher(query, num_results)
                if result:
                    return result
            except Exception:
                continue

        return f"搜索不可用：无法连接任何搜索引擎。可尝试以下方式获取信息：\n1. 查询数据库中的历史数据\n2. 使用 get_kline_data 获取行情数据\n3. 使用 get_current_time 获取当前时间\n关键词: {query}"

    except Exception as e:
        logger.error(f"[web_search] 搜索失败: {e}")
        return f"搜索失败: {str(e)}"


def _try_duckduckgo_search(query: str, num: int) -> Optional[str]:
    try:
        import urllib.request
        import urllib.parse
        import json

        encoded_query = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        lines = [f"搜索结果（关键词: {query}）：", ""]

        abstract = data.get('AbstractText', '')
        abstract_source = data.get('AbstractSource', '')
        if abstract:
            lines.append(f"📌 百科摘要: {abstract[:500]}")
            if abstract_source:
                lines.append(f"   来源: {abstract_source}")
            lines.append("")

        related_topics = data.get('RelatedTopics', [])
        count = 0
        for topic in related_topics:
            if count >= num:
                break
            if isinstance(topic, dict) and 'Text' in topic:
                count += 1
                text = topic.get('Text', '')
                first_url = topic.get('FirstURL', '')
                lines.append(f"{count}. {text[:300]}")
                if first_url:
                    lines.append(f"   链接: {first_url}")
                lines.append("")

        if count == 0 and not abstract:
            return None

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[DuckDuckGo] 搜索失败: {e}")
        return None


def _try_bing_search(query: str, num: int) -> Optional[str]:
    try:
        import urllib.request
        import urllib.parse
        import json

        encoded_query = urllib.parse.quote(query)
        url = f"https://api.bing.microsoft.com/v7.0/search?q={encoded_query}&count={num}&mkt=zh-CN"

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Ocp-Apim-Subscription-Key': 'demo',
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        lines = [f"Bing搜索结果（关键词: {query}）：", ""]
        web_pages = data.get('webPages', {}).get('value', [])
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
        return None


def _try_news_search(query: str, num: int) -> Optional[str]:
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


def get_web_tools() -> list:
    return [web_search]