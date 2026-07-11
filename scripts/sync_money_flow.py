"""同步资金流向数据。

用法:
  python scripts/sync_money_flow.py
  terminal("python scripts/sync_money_flow.py", background=True)
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

    print("开始同步: 资金流向")
    start = time.time()
    result = sync.sync_money_flow()
    elapsed = time.time() - start

    if isinstance(result, dict):
        status = result.get("status", "unknown")
        if status == "success":
            print(f"同步完成 - {result} - 耗时{elapsed:.1f}s")
        else:
            print(f"同步失败 - {result} - 耗时{elapsed:.1f}s")
            sys.exit(1)
    else:
        print(f"同步完成 - {result} - 耗时{elapsed:.1f}s")


if __name__ == "__main__":
    main()