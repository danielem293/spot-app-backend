import sqlite3

conn = sqlite3.connect('app.db')
cursor = conn.cursor()

cursor.execute("ALTER TABLE users ADD COLUMN latitude REAL DEFAULT 0.0")
cursor.execute("ALTER TABLE users ADD COLUMN longitude REAL DEFAULT 0.0")

conn.commit()
conn.close()
print("Location columns added successfully!")