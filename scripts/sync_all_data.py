"""全量数据同步 —— 按依赖顺序依次执行所有同步任务。

用法:
  python scripts/sync_all_data.py
  terminal("python scripts/sync_all_data.py", background=True)
"""
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alpha_agent.infra.sync.service import DataSyncService
from alpha_agent.infra.db.database import init_db, check_db_connection


TASKS = [
    ("股票列表", "sync_stock_list"),
    ("ETF列表", "sync_etf_list"),
    ("股票K线", "sync_stock_kline"),
    ("ETF K线", "sync_etf_kline"),
    ("财务数据", "sync_financial_data"),
    ("资金流向", "sync_money_flow"),
    ("行业聚合", "sync_industry_aggregation"),
    ("宏观数据", "sync_macro_data"),
    ("选股因子", "sync_stock_factors"),
]


def main():
    if not check_db_connection():
        print("数据库连接失败")
        sys.exit(1)

    init_db()
    sync = DataSyncService()

    print("=" * 60)
    print("全量数据同步")
    print("=" * 60)

    total_start = time.time()
    results = []

    for name, method_name in TASKS:
        method = getattr(sync, method_name, None)
        if method is None:
            print(f"  ⚠️ {name}: 方法不存在，跳过")
            results.append((name, "skipped", "方法不存在"))
            continue

        print(f"\n>>> 同步: {name}")
        start = time.time()
        try:
            result = method()
            elapsed = time.time() - start

            if isinstance(result, dict):
                status = result.get("status", "unknown")
                if status == "success":
                    print(f"  ✅ {name} 完成 - {result} - {elapsed:.1f}s")
                    results.append((name, "success", f"{elapsed:.1f}s"))
                elif status == "skipped":
                    print(f"  ⏭️ {name} 跳过 - {result.get('reason', '')} - {elapsed:.1f}s")
                    results.append((name, "skipped", result.get("reason", "")))
                else:
                    print(f"  ❌ {name} 失败 - {result} - {elapsed:.1f}s")
                    results.append((name, "failed", str(result)))
            else:
                print(f"  ✅ {name} 完成 - {result} - {elapsed:.1f}s")
                results.append((name, "success", f"{elapsed:.1f}s"))

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ {name} 异常 - {e} - {elapsed:.1f}s")
            results.append((name, "error", str(e)))

    total_elapsed = time.time() - total_start

    print("\n" + "=" * 60)
    print("同步汇总")
    print("=" * 60)

    success = sum(1 for _, s, _ in results if s == "success")
    skipped = sum(1 for _, s, _ in results if s == "skipped")
    failed = sum(1 for _, s, _ in results if s in ("failed", "error"))

    for name, status, detail in results:
        emoji = {"success": "✅", "skipped": "⏭️", "failed": "❌", "error": "❌"}.get(status, "❓")
        print(f"  {emoji} {name}: {detail}")

    print(f"\n总计: {len(results)} 项 | ✅ {success} | ⏭️ {skipped} | ❌ {failed} | 耗时 {total_elapsed:.1f}s")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()