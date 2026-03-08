import sqlite3

conn = sqlite3.connect('app.db')
cursor = conn.cursor()

cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")

conn.commit()
conn.close()
print("Password column added successfully!")