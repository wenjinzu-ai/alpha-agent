"""10 个真实投资场景评测脚本。

场景选择原则：
  - 从真实投资领域抽取，不针对本项目能力定制（避免过拟合）
  - 覆盖：行业分析、个股对比、市场择时、ETF配置、风险管理、
          因子选股、策略回测、数据诊断、宏观分析、投资教育
  - 每个场景评测：任务完成度、工具调用合理性、输出质量、错误处理

运行方式:
  python scripts/eval_scenarios.py [--scenario 1-10] [--output report.json]
"""
import json
import sys
import time
import uuid
import argparse
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

sys.path.insert(0, ".")

from alpha_agent.core.agent_loop import AgentLoop
from alpha_agent.utils.logger import logger
from alpha_agent.config import settings


@dataclass
class ScenarioResult:
    id: str
    name: str
    query: str
    category: str
    success: bool
    response: str = ""
    tool_calls: List[str] = field(default_factory=list)
    error: str = ""
    duration_seconds: float = 0.0
    finished: bool = False
    tokens_used: int = 0
    score: Dict[str, int] = field(default_factory=lambda: {
        "task_completion": 0,
        "tool_usage": 0,
        "response_quality": 0,
        "error_handling": 0,
    })

SCENARIOS = [
    {
        "id": "S01",
        "name": "行业分析-半导体",
        "category": "industry_analysis",
        "query": "分析一下半导体行业当前的景气度和投资机会，重点关注哪些公司值得关注。请基于真实数据分析，不要泛泛而谈。",
    },
    {
        "id": "S02",
        "name": "个股对比-白酒双雄",
        "category": "stock_comparison",
        "query": "对比一下贵州茅台(600519)和五粮液(000858)的基本面，从估值、盈利能力、成长性三个维度分析哪个更适合长期持有。请查询真实财报数据。",
    },
    {
        "id": "S03",
        "name": "市场择时判断",
        "category": "market_timing",
        "query": "当前市场环境下，如何判断是应该加仓还是减仓？请从技术面指标（如均线、MACD、成交量）和基本面（PE分位、市场情绪）两个角度分析，给出具体判断依据。",
    },
    {
        "id": "S04",
        "name": "ETF组合配置",
        "category": "portfolio_config",
        "query": "我想配置一个攻守兼备的ETF组合，预算100万。请从A股ETF中推荐3-5只，说明配置逻辑和权重分配，并给出每只ETF的推荐理由。",
    },
    {
        "id": "S05",
        "name": "行业分散化风险管理",
        "category": "risk_management",
        "query": "我的持仓集中在新能源板块，占比超过70%。请分析这种集中持仓的风险，并给出具体的行业分散化建议，推荐2-3个可以配置的行业方向。",
    },
    {
        "id": "S06",
        "name": "多因子选股",
        "category": "factor_screening",
        "query": "请从价值、成长、质量、动量四个维度，帮我筛选出当前A股市场最具性价比的10只股票。给出每只股票的核心指标数据和入选理由。",
    },
    {
        "id": "S07",
        "name": "策略回测验证",
        "category": "backtest",
        "query": "验证一下'低估值+高股息'策略在A股市场过去一年的表现。请用PE<15且股息率>3%作为筛选条件，回测结果与沪深300指数对比，给出年化收益、最大回撤、夏普比率。",
    },
    {
        "id": "S08",
        "name": "数据质量诊断",
        "category": "data_diagnosis",
        "query": "帮我检查一下系统中的数据质量：最近一个月的数据是否存在缺失或异常？各数据表的更新状态如何？有哪些数据需要修复？",
    },
    {
        "id": "S09",
        "name": "宏观政策影响分析",
        "category": "macro_analysis",
        "query": "分析央行降息降准政策对A股市场的影响机制。哪些行业受益最大？哪些行业承压？请结合历史数据和行业特征给出分析。",
    },
    {
        "id": "S10",
        "name": "估值方法教育",
        "category": "education",
        "query": "请详细解释PE、PB、ROE三种估值指标的区别和适用场景，然后用贵州茅台(600519)作为实例，用这三个指标分析其当前估值水平是否合理。",
    },
]


def extract_tool_calls(result: dict) -> List[str]:
    """从 AgentLoop 结果中提取工具调用列表。"""
    tools = []
    messages = result.get("messages", [])
    for msg in messages:
        if hasattr(msg, "tool_calls"):
            for tc in msg.tool_calls:
                name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
                tools.append(name)
        if hasattr(msg, "__class__") and msg.__class__.__name__ == "ToolMessage":
            if hasattr(msg, "name"):
                tools.append(msg.name)
    return tools


def extract_final_response(result: dict) -> str:
    """从 AgentLoop 结果中提取最终 AI 回复。"""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        cls_name = msg.__class__.__name__ if hasattr(msg, "__class__") else ""
        if cls_name == "AIMessage":
            content = str(msg.content) if hasattr(msg, "content") else ""
            if content and not any(
                content.strip().startswith(p) for p in ["Tool", "function", "{", "["]
            ):
                return content
    return ""


def score_response(scenario: dict, result: ScenarioResult) -> Dict[str, int]:
    """根据响应质量评分。"""
    scores = {"task_completion": 0, "tool_usage": 0, "response_quality": 0, "error_handling": 0}

    if not result.success:
        return scores

    response = result.response.lower()
    query = scenario["query"].lower()

    # 任务完成度：是否正面回应了问题
    if response and len(response) > 200:
        scores["task_completion"] = min(80, len(response) // 10)

    # 工具调用合理性
    if result.tool_calls:
        has_data_tool = any(t in result.tool_calls for t in ["query_data", "execute_code", "execute_pipeline", "terminal"])
        if has_data_tool:
            scores["tool_usage"] = 70
        else:
            scores["tool_usage"] = 40

    # 响应质量：是否有具体数据/判断
    quality_indicators = ["数据", "指标", "PE", "估值", "建议", "风险", "推荐", "分析", "%", "倍"]
    quality_count = sum(1 for kw in quality_indicators if kw in response)
    scores["response_quality"] = min(80, quality_count * 10)

    # 错误处理
    if "错误" in result.response or "失败" in result.response:
        scores["error_handling"] = 30
    else:
        scores["error_handling"] = 60

    return scores


def run_scenario(scenario: dict, agent: AgentLoop, timeout: int = 300) -> ScenarioResult:
    """执行单个场景评测。"""
    result = ScenarioResult(
        id=scenario["id"],
        name=scenario["name"],
        query=scenario["query"],
        category=scenario["category"],
        success=False,
    )

    session_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print(f"[{scenario['id']}] {scenario['name']}")
    print(f"    类别: {scenario['category']}")
    print(f"    问题: {scenario['query'][:100]}...")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        agent_result = agent.invoke(scenario["query"], session_id=session_id)
        duration = time.time() - start_time

        result.duration_seconds = round(duration, 1)
        result.tool_calls = extract_tool_calls(agent_result)
        result.response = extract_final_response(agent_result)
        result.success = True
        result.finished = True

        # 评分
        result.score = score_response(scenario, result)

        print(f"    耗时: {duration:.1f}s")
        print(f"    工具调用: {result.tool_calls}")
        print(f"    响应长度: {len(result.response)} 字符")
        print(f"    评分: {result.score}")
        print(f"    响应预览: {result.response[:300]}...")

    except Exception as e:
        duration = time.time() - start_time
        result.duration_seconds = round(duration, 1)
        result.error = str(e)
        result.success = False
        print(f"    错误: {e}")
        traceback.print_exc()

    print()
    return result


def print_summary(results: List[ScenarioResult]):
    """打印评测汇总。"""
    print("\n" + "=" * 70)
    print("评测汇总")
    print("=" * 70)

    total = len(results)
    success = sum(1 for r in results if r.success)
    avg_duration = sum(r.duration_seconds for r in results) / max(total, 1)
    avg_task_completion = sum(r.score["task_completion"] for r in results) / max(total, 1)
    avg_tool_usage = sum(r.score["tool_usage"] for r in results) / max(total, 1)
    avg_response_quality = sum(r.score["response_quality"] for r in results) / max(total, 1)
    avg_error_handling = sum(r.score["error_handling"] for r in results) / max(total, 1)

    print(f"\n{'场景':<6} {'名称':<20} {'状态':<8} {'耗时':<8} {'完成度':<8} {'工具':<8} {'质量':<8} {'容错':<8}")
    print("-" * 70)

    for r in results:
        status = "OK" if r.success else "FAIL"
        print(
            f"{r.id:<6} {r.name:<20} {status:<8} {r.duration_seconds:.1f}s{'':>3} "
            f"{r.score['task_completion']:<8} {r.score['tool_usage']:<8} "
            f"{r.score['response_quality']:<8} {r.score['error_handling']:<8}"
        )
        if r.error:
            print(f"      错误: {r.error[:80]}")

    print("-" * 70)
    print(f"总计: {total} | 成功: {success} | 失败: {total - success}")
    print(f"平均耗时: {avg_duration:.1f}s")
    print(f"平均评分: 任务完成度={avg_task_completion:.0f} | 工具调用={avg_tool_usage:.0f} | 响应质量={avg_response_quality:.0f} | 容错={avg_error_handling:.0f}")

    overall = (avg_task_completion + avg_tool_usage + avg_response_quality + avg_error_handling) / 4
    print(f"\n综合评分: {overall:.1f}/100")
    print("=" * 70)


def save_report(results: List[ScenarioResult], output_path: str):
    """保存评测报告。"""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_scenarios": len(results),
        "success_count": sum(1 for r in results if r.success),
        "results": [asdict(r) for r in results],
        "summary": {
            "avg_duration": sum(r.duration_seconds for r in results) / max(len(results), 1),
            "avg_task_completion": sum(r.score["task_completion"] for r in results) / max(len(results), 1),
            "avg_tool_usage": sum(r.score["tool_usage"] for r in results) / max(len(results), 1),
            "avg_response_quality": sum(r.score["response_quality"] for r in results) / max(len(results), 1),
            "avg_error_handling": sum(r.score["error_handling"] for r in results) / max(len(results), 1),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存至: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="10 场景评测")
    parser.add_argument("--scenario", type=str, help="指定场景 ID（如 S01）或编号范围（如 1-5）")
    parser.add_argument("--output", type=str, default="eval_report.json", help="输出报告路径")
    parser.add_argument("--timeout", type=int, default=300, help="每个场景超时时间（秒）")
    args = parser.parse_args()

    selected = SCENARIOS
    if args.scenario:
        if "-" in args.scenario:
            start, end = args.scenario.split("-")
            ids = [f"S{int(i):02d}" for i in range(int(start), int(end) + 1)]
            selected = [s for s in SCENARIOS if s["id"] in ids]
        else:
            sid = args.scenario if args.scenario.startswith("S") else f"S{int(args.scenario):02d}"
            selected = [s for s in SCENARIOS if s["id"] == sid]

    if not selected:
        print("未找到匹配的场景")
        return

    print("=" * 70)
    print("投资分析 Agent 场景评测")
    print(f"LLM: {settings.llm_model} @ {settings.llm_base_url}")
    print(f"场景数: {len(selected)}")
    print("=" * 70)

    agent = AgentLoop()
    results = []

    for scenario in selected:
        result = run_scenario(scenario, agent, timeout=args.timeout)
        results.append(result)

    print_summary(results)
    save_report(results, args.output)


if __name__ == "__main__":
    main()