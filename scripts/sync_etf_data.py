"""同步ETF列表和K线数据。

用法:
  python scripts/sync_etf_data.py              # 同步列表+K线
  python scripts/sync_etf_data.py list         # 仅列表
  python scripts/sync_etf_data.py kline        # 仅K线
  terminal("python scripts/sync_etf_data.py", background=True)
"""
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alpha_agent.infra.sync.service import DataSyncService
from alpha_agent.infra.db.database import init_db, check_db_connection


def main():
    if not check_db_connection():
        print("数据库连接失败")
        sys.exit(1)

    init_db()
    sync = DataSyncService()

    mode = sys.argv[1] if len(sys.argv) >= 2 else "all"
    start = time.time()

    if mode in ("list", "all"):
        print("同步: ETF列表")
        result = sync.sync_etf_list()
        _print_result("ETF列表", result)

    if mode in ("kline", "all"):
        print("同步: ETF K线")
        result = sync.sync_etf_kline()
        _print_result("ETF K线", result)

    elapsed = time.time() - start
    print(f"总耗时: {elapsed:.1f}s")


def _print_result(name, result):
    if isinstance(result, dict):
        status = result.get("status", "unknown")
        if status == "success":
            print(f"  {name} 完成 - {result}")
        elif status == "skipped":
            print(f"  {name} 跳过 - {result.get('reason', '')}")
        else:
            print(f"  {name} 失败 - {result} - {result.get('error', '')}")
    else:
        print(f"  {name} 完成 - {result}")


if __name__ == "__main__":
    main()