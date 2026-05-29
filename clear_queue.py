import sqlite3

conn = sqlite3.connect("deal_engine.sqlite3")

rows = conn.execute("""
SELECT source_category, status, COUNT(*) AS count
FROM product_queue
GROUP BY source_category, status
ORDER BY source_category, status
""").fetchall()

for row in rows:
    print(row)