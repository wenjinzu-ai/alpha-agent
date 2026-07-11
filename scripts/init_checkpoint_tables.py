import sys
sys.path.insert(0, '.')

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from alpha_agent.config import settings

conn_info = (
    f"host={settings.postgres_host} "
    f"port={settings.postgres_port} "
    f"dbname={settings.postgres_db} "
    f"user={settings.postgres_user} "
    f"password={settings.postgres_password}"
)

with psycopg.connect(conninfo=conn_info, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE")
        cur.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE")
        cur.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
        cur.execute("DROP TABLE IF EXISTS checkpoint_migrations CASCADE")
        print("✅ 旧表已清除")

with psycopg.connect(conninfo=conn_info) as conn:
    with conn.cursor() as cur:
        migrations = PostgresSaver.MIGRATIONS
        print(f"执行 {len(migrations)} 个迁移...")

        for v, migration in enumerate(migrations):
            migration_sql = migration.replace("CREATE INDEX CONCURRENTLY", "CREATE INDEX")
            cur.execute(migration_sql)
            if v > 0:
                cur.execute("INSERT INTO checkpoint_migrations (v) VALUES (%s)", (v,))
            print(f"  迁移 {v}: 完成")

        conn.commit()

        cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'checkpoint%' ORDER BY tablename")
        tables = cur.fetchall()
        print(f"\n✅ 检查点表创建完成: {[t[0] for t in tables]}")
