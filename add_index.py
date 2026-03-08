import sqlite3

conn = sqlite3.connect('app.db')
cursor = conn.cursor()

# This command creates the B-Tree index on the first_name column
cursor.execute('CREATE INDEX IF NOT EXISTS idx_first_name ON users(first_name)')

conn.commit()
conn.close()
print("B-Tree Index added for scalable searching!")