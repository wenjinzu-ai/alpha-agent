import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5433, user="postgres",
    password="postgres", dbname="alpha_agent"
)
cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM public.\"{t}\"")
    print(f"  {t}: {cur.fetchone()[0]}")

cur.close()
conn.close()