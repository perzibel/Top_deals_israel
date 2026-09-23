from app.storage.paths import get_conn

conn = get_conn()

rows = conn.execute("""
SELECT source_category, status, COUNT(*) AS count
FROM product_queue
GROUP BY source_category, status
ORDER BY source_category, status
""").fetchall()

for row in rows:
    print(row)