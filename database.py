import sqlite3

conn = sqlite3.connect('app.db')
cursor = conn.cursor()

# 1. Users Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    first_name TEXT NOT NULL,
    city TEXT,
    profile_picture_url TEXT NOT NULL,
    points INTEGER DEFAULT 0,
    spotted_count INTEGER DEFAULT 0,
    followers_count INTEGER DEFAULT 0,
    following_count INTEGER DEFAULT 0,
    ghost_mode_active BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# 2. Sightings Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS sightings (
    sighting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    photographer_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    photo_url TEXT NOT NULL,
    status TEXT DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (photographer_id) REFERENCES users (user_id),
    FOREIGN KEY (target_id) REFERENCES users (user_id)
)
''')

# 3. NEW: Follows Table
cursor.execute('''
CREATE TABLE IF NOT EXISTS follows (
    follower_id INTEGER NOT NULL,
    followed_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (follower_id, followed_id),
    FOREIGN KEY (follower_id) REFERENCES users (user_id),
    FOREIGN KEY (followed_id) REFERENCES users (user_id)
)
''')

conn.commit()
conn.close()
print("Database blueprint is ready with the Follows table!")