from typing import Optional, Dict, Any, List
import re
import json

from pydantic import BaseModel, Field

from alpha_agent.infra.llm import get_llm_service
from alpha_agent.utils.logger import logger


class QueryParseResult(BaseModel):
    ts_code: Optional[str] = Field(default=None, description="股票代码，格式如000001.SZ或600519.SH，如果是股票名称请转换为代码")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    analysis_type: str = Field(default="full", description="分析类型：full=全面分析, fundamental=仅基本面, technical=仅技术面, risk=仅风控")
    user_intent: str = Field(default="", description="用户的核心需求，用一句话概括")
    focus_points: List[str] = Field(default_factory=list, description="用户关注的重点方面列表")


SYSTEM_PROMPT = """你是一个股票查询解析助手，负责把用户的自然语言问题解析成结构化的查询参数。

股票代码规则：
- 沪市主板：60开头，后缀.SH（如600519.SH）
- 深市主板：000开头，后缀.SZ（如000001.SZ）
- 创业板：300开头，后缀.SZ
- 科创板：688开头，后缀.SH
- 北交所：8开头，后缀.BJ

常见股票名称映射（仅作参考，不确定就留空）：
- 平安银行：000001.SZ
- 贵州茅台：600519.SH
- 宁德时代：300750.SZ
- 比亚迪：002594.SZ
- 招商银行：600036.SH
- 五粮液：000858.SZ
- 美的集团：000333.SZ
- 格力电器：000651.SZ
- 腾讯控股：00700.HK
- 阿里巴巴：BABA

分析类型判断：
- 用户没说具体分析什么 → full
- 只问基本面/财务/业绩 → fundamental
- 只问技术面/走势/K线 → technical
- 只问风险/风控/波动率 → risk

注意：
1. 如果用户只说了股票名称，你不确定代码，ts_code 可以为 null
2. 只提取确定的信息，不确定的不要瞎编
3. 输出必须是严格的 JSON 格式"""


def parse_query(query: str, ts_code_hint: Optional[str] = None) -> Dict[str, Any]:
    if not query and not ts_code_hint:
        return {
            "ts_code": None,
            "stock_name": None,
            "analysis_type": "full",
            "user_intent": "",
            "focus_points": [],
        }

    if ts_code_hint and _is_valid_ts_code(ts_code_hint):
        result = {
            "ts_code": ts_code_hint,
            "stock_name": None,
            "analysis_type": "full",
            "user_intent": query or "",
            "focus_points": [],
        }
    else:
        result = _parse_by_regex(query)
        if ts_code_hint and not result["ts_code"]:
            result["ts_code"] = ts_code_hint

    llm = get_llm_service()
    if llm.enabled and query:
        llm_result = _parse_by_llm(query)
        if llm_result:
            if llm_result.get("ts_code"):
                result["ts_code"] = llm_result["ts_code"]
            if llm_result.get("stock_name"):
                result["stock_name"] = llm_result["stock_name"]
            if llm_result.get("analysis_type"):
                result["analysis_type"] = llm_result["analysis_type"]
            if llm_result.get("user_intent"):
                result["user_intent"] = llm_result["user_intent"]
            if llm_result.get("focus_points"):
                result["focus_points"] = llm_result["focus_points"]

    logger.info(f"[query_parser] 解析结果: ts_code={result['ts_code']}, type={result['analysis_type']}")
    return result


def _is_valid_ts_code(code: str) -> bool:
    if not code:
        return False
    pattern = r'^(000|001|002|003|300|301|600|601|603|605|688|8)\d{3,5}\.(SZ|SH|BJ)$'
    return bool(re.match(pattern, code, re.IGNORECASE))


def _parse_by_regex(query: str) -> Dict[str, Any]:
    result = {
        "ts_code": None,
        "stock_name": None,
        "analysis_type": "full",
        "user_intent": query,
        "focus_points": [],
    }

    pattern = r'(000\d{3}|001\d{3}|002\d{3}|300\d{3}|600\d{3}|601\d{3}|603\d{3}|688\d{3})'
    match = re.search(pattern, query)
    if match:
        code = match.group(1)
        if code.startswith(("000", "001", "002", "003", "300", "301")):
            result["ts_code"] = f"{code}.SZ"
        elif code.startswith(("600", "601", "603", "605", "688")):
            result["ts_code"] = f"{code}.SH"

    if any(k in query for k in ["基本面", "财务", "业绩", "营收", "利润", "估值"]):
        result["analysis_type"] = "fundamental"
        result["focus_points"].append("基本面")
    if any(k in query for k in ["技术面", "走势", "K线", "均线", "MACD", "KDJ", "RSI"]):
        result["analysis_type"] = "technical" if result["analysis_type"] == "full" else "full"
        result["focus_points"].append("技术面")
    if any(k in query for k in ["风险", "风控", "波动", "回撤", "仓位"]):
        result["analysis_type"] = "risk" if result["analysis_type"] == "full" else "full"
        result["focus_points"].append("风控")

    return result


def _parse_by_llm(query: str) -> Optional[Dict[str, Any]]:
    try:
        llm = get_llm_service()
        user_prompt = f"""请解析以下用户查询，输出严格的JSON格式：

用户查询：{query}

JSON格式要求：
{{
  "ts_code": "股票代码或null",
  "stock_name": "股票名称或null",
  "analysis_type": "full/fundamental/technical/risk",
  "user_intent": "用户核心需求一句话",
  "focus_points": ["关注点1", "关注点2"]
}}

只输出JSON，不要有其他文字。"""
        response = llm.chat(SYSTEM_PROMPT, user_prompt)
        if not response:
            return None
        response = response.strip()
        if response.startswith("```"):
            response = response.strip("`")
            if response.lower().startswith("json"):
                response = response[4:].strip()
        return json.loads(response)
    except Exception as e:
        logger.debug(f"LLM 解析查询失败: {e}")
        return None
