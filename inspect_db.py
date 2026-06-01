import sqlite3

conn = sqlite3.connect('tmp_test_pm.sqlite')
cur = conn.cursor()
print('tables:', [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
print('bootstrap:', cur.execute("SELECT bootstrap_complete, first_developer_id FROM bootstrap_state LIMIT 1").fetchone())
print('users:', cur.execute("SELECT count(*) FROM users").fetchone())
conn.close()
