"""计算选股因子（非同步，基于已有K线数据计算）。

用法:
  python scripts/calc_stock_factors.py
  terminal("python scripts/calc_stock_factors.py", background=True)
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

    print("开始计算: 选股因子")
    start = time.time()
    result = sync.sync_stock_factors()
    elapsed = time.time() - start

    if isinstance(result, dict):
        status = result.get("status", "unknown")
        if status == "success":
            print(f"计算完成 - {result} - 耗时{elapsed:.1f}s")
        else:
            print(f"计算失败 - {result} - 耗时{elapsed:.1f}s")
            sys.exit(1)
    else:
        print(f"计算完成 - {result} - 耗时{elapsed:.1f}s")


if __name__ == "__main__":
    main()