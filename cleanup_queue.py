import sqlite3

conn = sqlite3.connect("deal_engine.sqlite3")

conn.execute("""
UPDATE product_queue
SET status = 'skipped',
    skipped_reason = 'category overflow cleanup - kept top 5 per category'
WHERE status = 'queued'
  AND id NOT IN (
      SELECT id
      FROM (
          SELECT id,
                 ROW_NUMBER() OVER (
                     PARTITION BY source_category
                     ORDER BY score DESC, created_at ASC
                 ) AS rn
          FROM product_queue
          WHERE status = 'queued'
      )
      WHERE rn <= 5
  )
""")

conn.commit()

print("changed rows:", conn.total_changes)