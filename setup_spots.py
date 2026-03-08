import sqlite3

conn = sqlite3.connect('app.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS spots (
        spot_id INTEGER PRIMARY KEY AUTOINCREMENT,
        photographer_id INTEGER,
        target_id INTEGER,
        photo_url TEXT,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (photographer_id) REFERENCES users(user_id),
        FOREIGN KEY (target_id) REFERENCES users(user_id)
    )
''')

conn.commit()
conn.close()
print("Spots table created successfully!")