"""同步股票日K线数据。

用法:
  python scripts/sync_stock_kline.py                    # 全量增量
  python scripts/sync_stock_kline.py 000001.SZ          # 指定股票
  python scripts/sync_stock_kline.py 000001.SZ 20250101 # 指定起始日期
  terminal("python scripts/sync_stock_kline.py", background=True)
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

    ts_code = sys.argv[1] if len(sys.argv) >= 2 else None
    start_date = sys.argv[2] if len(sys.argv) >= 3 else None

    desc = f"股票K线({ts_code})" if ts_code else "股票K线(全量)"
    print(f"开始同步: {desc}")
    start = time.time()

    result = sync.sync_stock_kline(ts_code=ts_code, start_date=start_date)
    elapsed = time.time() - start

    if isinstance(result, dict):
        status = result.get("status", "unknown")
        if status == "success":
            print(f"同步完成 - {result} - 耗时{elapsed:.1f}s")
        elif status == "skipped":
            print(f"同步跳过 - {result.get('reason', '')} - 耗时{elapsed:.1f}s")
        else:
            print(f"同步失败 - {result} - 耗时{elapsed:.1f}s")
            sys.exit(1)
    else:
        print(f"同步完成 - {result} - 耗时{elapsed:.1f}s")


if __name__ == "__main__":
    main()