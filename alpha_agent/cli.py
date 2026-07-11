import sys
import uuid
import argparse
from typing import Optional, List

from alpha_agent.utils.logger import logger
from alpha_agent.domain.screener import get_stock_screener
from alpha_agent.domain.factor import get_factor_service
from alpha_agent.domain.rotation import get_industry_rotation_service
from alpha_agent.domain.backtest import get_factor_backtest_engine
from alpha_agent.infra.db.warehouse import get_data_warehouse


BANNER = r"""
 ___                      _                         _    
|_ _|_ __   __ _  ___ _ __| |_ _ __ ___   ___ _ __ | |_  
 | || '_ \ / _` |/ _` '__| __| '_ ` _ \ / _ \ '_ \| __| 
 | || | | | (_| |  __/ |  | |_| | | | | |  __/ | | | |_  
|___|_| |_|\__, |\___|_|   \__|_| |_| |_|\___|_| |_|\__| 
           |___/                                         
  智能投顾助手 · AgentLoop 持久循环
  输入问题开始对话，输入 /help 查看命令
"""

HELP_TEXT = """
命令列表:
  /help, /h              显示帮助信息
  /clear, /c             清空对话历史
  /history               查看对话历史
  /analyze <code>        直接分析一只股票（如 /analyze 000001.SZ）
  /tasks                 查看后台任务列表
  /screen [stock|etf]    全市场选股扫描
  /factor <name>         按因子排名
  /factors               列出所有可用因子
  /rotation              行业轮动分析
  /fbt <codes...>        因子策略回测
  /exit, /quit, /q       退出程序
"""


def _input_loop(session_id: str, on_command, on_message):
    while True:
        try:
            user_input = input("你 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if user_input in ("/exit", "/quit", "/q"):
                print("再见！")
                break
            if user_input in ("/help", "/h"):
                print(HELP_TEXT)
                continue
            if user_input in ("/clear", "/c"):
                session_id = str(uuid.uuid4())
                print(f"已清空对话历史，新会话: {session_id[:8]}")
                continue
            switched = on_command(user_input)
            if switched:
                return
            continue

        print()
        print("小投 > ", end="", flush=True)

        try:
            on_message(user_input)
        except Exception as e:
            logger.error(f"对话处理失败: {e}")
            print(f"抱歉，处理你的问题时出错了: {e}")
        print()
        print()


def run_interactive():
    print(BANNER)
    print("🚀 AgentLoop 模式")
    print()

    from alpha_agent.core.agent_loop import get_agent_loop
    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    print(f"对话 Session ID: {session_id[:8]}")
    print("你好！我是小投，你的智能投顾助手。有什么可以帮你的？")
    print()

    def on_command(user_input):
        if user_input == "/tasks":
            _cmd_list_tasks()
            return False
        _handle_cli_command(user_input)
        return False

    def on_message(user_input):
        _stream_agent_loop(agent_loop, session_id, user_input)

    _input_loop(session_id, on_command, on_message)


def _stream_agent_loop(agent_loop, session_id: str, user_input: str):
    from langchain_core.messages import HumanMessage

    full_response = ""
    in_thinking = False
    tool_count = 0

    for chunk in agent_loop.stream(user_input, session_id=session_id):
        if "messages" in chunk and chunk["messages"]:
            last_msg = chunk["messages"][-1]
            if last_msg.type == "ai":
                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                    if not in_thinking:
                        print("\n  💭 思考中...", end="", flush=True)
                        in_thinking = True
                    for tc in last_msg.tool_calls:
                        tool_count += 1
                        print(f" 🔧{tc['name']}", end="", flush=True)
                elif last_msg.content:
                    if in_thinking:
                        print(f"\n  ✅ 完成 {tool_count} 次工具调用\n")
                        print("小投 > ", end="", flush=True)
                        in_thinking = False
                    if not full_response:
                        full_response = last_msg.content
                        print(last_msg.content, end="", flush=True)

    if full_response:
        pass
    elif in_thinking:
        state = agent_loop.graph.get_state(
            {"configurable": {"thread_id": session_id}}
        )
        messages = state.values.get("messages", [])
        for msg in reversed(messages):
            if msg.type == "ai" and msg.content:
                print()
                print(msg.content)
                break


def _cmd_list_tasks():
    from alpha_agent.infra.process_registry import get_process_registry
    registry = get_process_registry()
    result = registry.list_tasks()

    total = result.get("total", 0)
    running = result.get("running", 0)
    tasks = result.get("tasks", [])

    if total == 0:
        print("当前没有后台任务")
        return

    print(f"后台任务列表（共{total}个，运行中{running}个）")
    print("-" * 70)
    for t in tasks:
        tid = t.get("task_id", "")
        cmd = t.get("command", "")
        st = t.get("status", "")
        elapsed = t.get("elapsed", 0)
        emoji = {
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "killed": "🛑",
            "timeout": "⏰",
        }.get(st, "⏳")
        print(f"  {emoji} {tid}  [{st}]  {elapsed}s  {cmd}")


def _handle_cli_command(user_input: str):
    cmd = user_input.lower().strip()

    if cmd.startswith("/screen"):
        parts = cmd.split()
        universe = "stock"
        if len(parts) > 1:
            universe = parts[1]
        _cmd_screen(universe, 20)
    elif cmd.startswith("/factor "):
        factor_name = cmd[len("/factor "):].strip()
        if factor_name:
            _cmd_factor_rank(factor_name)
        else:
            print("请指定因子名称，如 /factor change_pct_20d")
    elif cmd == "/factors":
        _cmd_list_factors()
    elif cmd == "/rotation":
        _cmd_rotation()
    elif cmd.startswith("/fbt "):
        codes_str = cmd[len("/fbt "):].strip()
        if codes_str:
            _cmd_factor_backtest(codes_str.split())
        else:
            print("请指定股票代码，如 /fbt 000001.SZ 600519.SH")
    elif cmd.startswith("/analyze "):
        code = cmd[len("/analyze "):].strip().upper()
        if "." not in code:
            if code.startswith(("000", "001", "002", "003", "300", "301")):
                code = f"{code}.SZ"
            elif code.startswith(("600", "601", "603", "605", "688")):
                code = f"{code}.SH"
        print(f"请在对话中输入: 分析 {code}")
    else:
        print(f"未知命令: {user_input}，输入 /help 查看帮助")


def _cmd_screen(universe: str, top_n: int):
    try:
        warehouse = get_data_warehouse()
        if not warehouse.enabled:
            print("⚠️  本地数据仓库未启用，选股扫描需要PostgreSQL数据库")
            print("请先配置 .env 中的 DATABASE_URL 并同步数据")
            return

        print(f"🔍 正在扫描{'A股股票' if universe == 'stock' else 'ETF'}，请稍候...")

        screener = get_stock_screener()

        def progress_cb(current, total, code):
            if current % 200 == 0 or current == total:
                print(f"  进度: {current}/{total}", end="\r", flush=True)

        results = screener.scan(universe=universe, top_n=top_n, progress_cb=progress_cb)
        print()

        if not results:
            print("未找到符合条件的标的，请检查数据是否已同步")
            return

        report = screener.get_scan_report(results, top_n=top_n)
        print(report)
    except Exception as e:
        logger.error(f"选股扫描失败: {e}")
        print(f"扫描失败: {e}")


def _cmd_factor_rank(factor_name: str):
    try:
        warehouse = get_data_warehouse()
        if not warehouse.enabled:
            print("⚠️  本地数据仓库未启用，因子排名需要PostgreSQL数据库")
            return

        print(f"📊 正在计算因子排名: {factor_name}，请稍候...")

        svc = get_factor_service()
        df = svc.rank_by_factor(factor_name, universe="stock", top_n=20)

        if df.empty:
            print(f"未找到数据，请检查因子名称是否正确。可用因子: {', '.join(svc.get_available_factors().keys())}")
            return

        print()
        print(f"{'排名':<5}{'代码':<12}{'名称':<10}{factor_name:<15}")
        print("-" * 50)
        for i, row in df.iterrows():
            val = row[factor_name]
            val_str = f"{val:.2f}" if isinstance(val, float) else str(val)
            print(f"{i+1:<5}{row['ts_code']:<12}{row['name']:<10}{val_str:<15}")
    except Exception as e:
        logger.error(f"因子排名失败: {e}")
        print(f"查询失败: {e}")


def _cmd_list_factors():
    try:
        svc = get_factor_service()
        factors = svc.get_available_factors()
        print("📋 可用技术因子列表:")
        print()
        for name, desc in factors.items():
            print(f"  {name:<20} - {desc}")
    except Exception as e:
        logger.error(f"获取因子列表失败: {e}")
        print(f"查询失败: {e}")


def _cmd_rotation():
    try:
        warehouse = get_data_warehouse()
        if not warehouse.enabled:
            print("⚠️  本地数据仓库未启用，行业轮动分析需要PostgreSQL数据库")
            return

        print("🔄 正在计算行业轮动，请稍候...")

        svc = get_industry_rotation_service()
        signals = svc.get_rotation_signals(top_n=5)

        if not signals:
            print("暂无行业轮动数据，请先同步股票数据")
            return

        print()
        print(svc.get_report(signals))
    except Exception as e:
        logger.error(f"行业轮动分析失败: {e}")
        print(f"分析失败: {e}")


def _cmd_factor_backtest(codes: List[str]):
    try:
        print(f"📈 正在运行因子策略回测，标的数: {len(codes)}，请稍候...")

        engine = get_factor_backtest_engine()
        result = engine.run_factor_strategy(
            universe=codes,
            factor_name="technical_score",
            rebalance_freq="monthly",
            top_n=min(5, len(codes)),
        )

        print()
        print(engine.get_report(result))
    except Exception as e:
        logger.error(f"因子回测失败: {e}")
        print(f"回测失败: {e}")


def run_once(query: str, code: Optional[str] = None):
    from alpha_agent.core.agent_loop import get_agent_loop
    from langchain_core.messages import HumanMessage

    agent_loop = get_agent_loop()
    session_id = str(uuid.uuid4())

    if code:
        query = f"{query}，股票代码是{code}"

    for chunk in agent_loop.stream(query, session_id=session_id):
        if "messages" in chunk and chunk["messages"]:
            last_msg = chunk["messages"][-1]
            if last_msg.type == "ai" and last_msg.content:
                if not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
                    print(last_msg.content)


def main():
    parser = argparse.ArgumentParser(description="智能投顾助手 - AgentLoop 架构")
    parser.add_argument("-q", "--query", type=str, help="单次查询，直接返回结果")
    parser.add_argument("-c", "--code", type=str, help="股票代码（配合 -q 使用）")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互式对话模式")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    p_screen = subparsers.add_parser("screen", help="全市场选股扫描")
    p_screen.add_argument("-u", "--universe", default="stock", choices=["stock", "etf"], help="选股范围")
    p_screen.add_argument("-n", "--top-n", type=int, default=20, help="返回前N名")

    p_factor = subparsers.add_parser("factor", help="因子排名")
    p_factor.add_argument("factor_name", type=str, help="因子名称")
    p_factor.add_argument("-u", "--universe", default="stock", choices=["stock", "etf"], help="范围")
    p_factor.add_argument("-n", "--top-n", type=int, default=20, help="返回前N名")

    subparsers.add_parser("factors", help="列出所有可用因子")

    p_rotation = subparsers.add_parser("rotation", help="行业轮动分析")
    p_rotation.add_argument("-n", "--top-n", type=int, default=5, help="最强/最弱各N个行业")

    p_fbt = subparsers.add_parser("fbt", help="因子策略回测")
    p_fbt.add_argument("codes", nargs="+", help="股票代码列表")
    p_fbt.add_argument("-f", "--factor", default="technical_score", help="因子名称")
    p_fbt.add_argument("-r", "--rebalance", default="monthly", help="调仓频率")
    p_fbt.add_argument("-n", "--top-n", type=int, default=5, help="每期持仓数")

    args = parser.parse_args()

    if args.command == "screen":
        _cmd_screen(args.universe, args.top_n)
        return

    if args.command == "factor":
        _cmd_factor_rank(args.factor_name)
        return

    if args.command == "factors":
        _cmd_list_factors()
        return

    if args.command == "rotation":
        _cmd_rotation()
        return

    if args.command == "fbt":
        _cmd_factor_backtest(args.codes)
        return

    if args.query:
        run_once(args.query, args.code)
    else:
        run_interactive()


if __name__ == "__main__":
    main()