from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import shutil
import os
import math
import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Create the images directory if it doesn't exist
os.makedirs("images", exist_ok=True)

# Security configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "your_super_secret_key_here" # We will use this to sign the tokens
ALGORITHM = "HS256"
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    
    try:
        # Decode the token using your secret key
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
            
        return int(user_id)
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Create a folder to store the images
os.makedirs("images", exist_ok=True)

app = FastAPI()

# Add this line right below app = FastAPI()
app.mount("/images", StaticFiles(directory="images"), name="images")

# --- MODELS ---
class NewUser(BaseModel):
    email: str
    password: str
    first_name: str
    city: str
    profile_picture_url: str

class LoginRequest(BaseModel):
    email: str
    password: str

class SightingRequest(BaseModel):
    target_id: int
    photo_url: str

class FollowRequest(BaseModel):
    followed_id: int

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float

class CommentRequest(BaseModel):
    content: str

class BlockRequest(BaseModel):
    blocked_id: int


# --- ENDPOINTS ---
@app.get("/")
def test_server():
    return {"message": "Hello Bar-Ilan University! The server is running."}

@app.post("/register")
def register_user(user: NewUser):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # Encrypt the password
    hashed_password = pwd_context.hash(user.password)
    
    try:
        cursor.execute('''
            INSERT INTO users (email, password_hash, first_name, city, profile_picture_url) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user.email, hashed_password, user.first_name, user.city, user.profile_picture_url))
        
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        
        return {"message": "Account created successfully", "user_id": new_id}
        
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

@app.post("/spot")
def spot_user(request: SightingRequest, photographer_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, ghost_mode_active FROM users WHERE user_id = ?", (request.target_id,))
    target = cursor.fetchone()
    
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Target user not found")
        
    if target[1] == 1:
        conn.close()
        raise HTTPException(status_code=403, detail="This user is currently in Ghost Mode and cannot be spotted.")

    cursor.execute('''
        SELECT sighting_id FROM sightings 
        WHERE photographer_id = ? AND target_id = ? 
        AND status IN ('Pending', 'Approved')
    ''', (photographer_id, request.target_id))
    
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="You have already spotted this user.")

    cursor.execute('''
        INSERT INTO sightings (photographer_id, target_id, photo_url, status)
        VALUES (?, ?, ?, 'Pending')
    ''', (photographer_id, request.target_id, request.photo_url))
    
    sighting_id = cursor.lastrowid
    
    # --- NEW: Get photographer's name and create notification ---
    cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (photographer_id,))
    photographer_name = cursor.fetchone()[0]
    
    cursor.execute('''
        INSERT INTO notifications (user_id, type, message)
        VALUES (?, 'spot_request', ?)
    ''', (request.target_id, f"{photographer_name} spotted you! Review the photo."))
    
    conn.commit()
    conn.close()
    
    return {"message": "Sighting request sent!", "sighting_id": sighting_id}

@app.get("/pending-requests")
def get_pending_requests(user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT sighting_id, photographer_id, photo_url 
        FROM sightings 
        WHERE target_id = ? AND status = 'Pending'
    ''', (user_id,))
    
    requests = cursor.fetchall()
    conn.close()
    
    return [{"sighting_id": r[0], "photographer_id": r[1], "photo_url": r[2]} for r in requests]


@app.patch("/decide-sighting/{sighting_id}")
def decide_sighting(sighting_id: int, approve: bool, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT target_id, status FROM sightings WHERE sighting_id = ?", (sighting_id,))
    sighting = cursor.fetchone()
    
    if not sighting:
        conn.close()
        raise HTTPException(status_code=404, detail="Sighting not found")
        
    if sighting[0] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="You are not authorized to decide on this sighting")
        
    if sighting[1] != 'Pending':
        conn.close()
        raise HTTPException(status_code=400, detail="This sighting has already been decided")
    
    new_status = "Approved" if approve else "Denied"
    
    cursor.execute('UPDATE sightings SET status = ? WHERE sighting_id = ?', (new_status, sighting_id))
    
    cursor.execute("SELECT photographer_id FROM sightings WHERE sighting_id = ?", (sighting_id,))
    p_id = cursor.fetchone()[0]
    
    # --- NEW: Get target's name to send notification to photographer ---
    cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (user_id,))
    target_name = cursor.fetchone()[0]
    
    if approve:
        cursor.execute('UPDATE users SET points = points + 1 WHERE user_id = ?', (p_id,))
        cursor.execute('UPDATE users SET spotted_count = spotted_count + 1 WHERE user_id = ?', (user_id,))
        
        cursor.execute('''
            INSERT INTO notifications (user_id, type, message)
            VALUES (?, 'spot_approved', ?)
        ''', (p_id, f"{target_name} approved your spotting photo! You earned 1 point."))
    else:
        cursor.execute('''
            INSERT INTO notifications (user_id, type, message)
            VALUES (?, 'spot_denied', ?)
        ''', (p_id, f"{target_name} denied your spotting photo."))
    
    conn.commit()
    conn.close()
    
    return {"message": "Sighting decision saved. Stats updated if approved."}


@app.get("/profile/{user_id}")
def get_user_profile(user_id: int, current_user: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT first_name, city, profile_picture_url, points, spotted_count, followers_count, following_count 
        FROM users 
        WHERE user_id = ?
    ''', (user_id,))
    
    user_data = cursor.fetchone()
    conn.close()
    
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {
        "first_name": user_data[0],
        "city": user_data[1],
        "profile_picture_url": user_data[2],
        "points": user_data[3],
        "spotted": user_data[4],
        "followers": user_data[5],
        "following": user_data[6]
    }

@app.get("/feed")
def get_feed(limit: int = 10, offset: int = 0, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            s.sighting_id, 
            p.first_name AS photographer_name, 
            t.first_name AS target_name, 
            s.photo_url, 
            s.created_at
        FROM sightings s
        JOIN users p ON s.photographer_id = p.user_id
        JOIN users t ON s.target_id = t.user_id
        WHERE s.status = 'Approved'
        ORDER BY s.created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    
    posts = cursor.fetchall()
    conn.close()
    
    feed = []
    for post in posts:
        feed.append({
            "sighting_id": post[0],
            "photographer_name": post[1],
            "target_name": post[2],
            "photo_url": post[3],
            "timestamp": post[4]
        })
        
    return feed



@app.post("/follow")
def follow_user(request: FollowRequest, follower_id: int = Depends(get_current_user)):
    if follower_id == request.followed_id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself")

    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (request.followed_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    try:
        cursor.execute('''
            INSERT INTO follows (follower_id, followed_id) 
            VALUES (?, ?)
        ''', (follower_id, request.followed_id))
        
        cursor.execute('UPDATE users SET following_count = following_count + 1 WHERE user_id = ?', (follower_id,))
        cursor.execute('UPDATE users SET followers_count = followers_count + 1 WHERE user_id = ?', (request.followed_id,))
        
        # --- NEW: Get follower's name and create notification ---
        cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (follower_id,))
        follower_name = cursor.fetchone()[0]
        
        cursor.execute('''
            INSERT INTO notifications (user_id, type, message)
            VALUES (?, 'follow', ?)
        ''', (request.followed_id, f"{follower_name} started following you."))
        
        conn.commit()
        conn.close()
        
        return {"message": "Successfully followed user!"}
        
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="You are already following this user")
    

@app.get("/search")
def search_users(query: str, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, first_name, profile_picture_url 
        FROM users 
        WHERE first_name LIKE ?
        AND user_id != ?
        AND user_id NOT IN (SELECT blocked_id FROM blocks WHERE user_id = ?)
        AND user_id NOT IN (SELECT user_id FROM blocks WHERE blocked_id = ?)
        ORDER BY followers_count DESC, points DESC
        LIMIT 20
    ''', (query + '%', user_id, user_id, user_id))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{"user_id": r[0], "first_name": r[1], "profile_picture_url": r[2]} for r in results]


@app.get("/feed/personal")
def get_personalized_feed(limit: int = 10, offset: int = 0, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT
            s.sighting_id, 
            p.first_name AS photographer_name, 
            t.first_name AS target_name, 
            s.photo_url, 
            s.created_at
        FROM sightings s
        JOIN users p ON s.photographer_id = p.user_id
        JOIN users t ON s.target_id = t.user_id
        JOIN follows f ON (f.followed_id = s.photographer_id OR f.followed_id = s.target_id)
        WHERE s.status = 'Approved' AND f.follower_id = ?
        AND p.user_id NOT IN (SELECT blocked_id FROM blocks WHERE user_id = ?)
        AND p.user_id NOT IN (SELECT user_id FROM blocks WHERE blocked_id = ?)
        AND t.user_id NOT IN (SELECT blocked_id FROM blocks WHERE user_id = ?)
        AND t.user_id NOT IN (SELECT user_id FROM blocks WHERE blocked_id = ?)
        ORDER BY s.created_at DESC
        LIMIT ? OFFSET ?
    ''', (user_id, user_id, user_id, user_id, user_id, limit, offset))
    
    posts = cursor.fetchall()
    conn.close()
    
    feed = []
    for post in posts:
        feed.append({
            "sighting_id": post[0],
            "photographer_name": post[1],
            "target_name": post[2],
            "photo_url": post[3],
            "timestamp": post[4]
        })
        
    return feed




@app.patch("/ghost-mode")
def toggle_ghost_mode(is_active: bool, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # SQLite stores booleans as 1 (true) or 0 (false)
    ghost_status = 1 if is_active else 0
    
    cursor.execute('''
        UPDATE users 
        SET ghost_mode_active = ? 
        WHERE user_id = ?
    ''', (ghost_status, user_id))
    
    conn.commit()
    conn.close()
    
    status_text = "activated" if is_active else "deactivated"
    return {"message": f"Ghost mode {status_text}."}



@app.get("/followers/{user_id}")
def get_followers(user_id: int, current_user: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # Get the details of users who are following the requested user_id
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.profile_picture_url
        FROM follows f
        JOIN users u ON f.follower_id = u.user_id
        WHERE f.followed_id = ?
    ''', (user_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{"user_id": r[0], "first_name": r[1], "profile_picture_url": r[2]} for r in results]


@app.get("/following/{user_id}")
def get_following(user_id: int, current_user: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # Get the details of users that the requested user_id is following
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.profile_picture_url
        FROM follows f
        JOIN users u ON f.followed_id = u.user_id
        WHERE f.follower_id = ?
    ''', (user_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{"user_id": r[0], "first_name": r[1], "profile_picture_url": r[2]} for r in results]


@app.delete("/unfollow")
def unfollow_user(request: FollowRequest, follower_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # 1. Delete the relationship from the follows table
    cursor.execute('''
        DELETE FROM follows 
        WHERE follower_id = ? AND followed_id = ?
    ''', (follower_id, request.followed_id))
    
    # Check if a row was actually deleted (if not, they weren't following them)
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="You are not following this user.")
        
    # 2. Update the counts in the users table by subtracting 1
    cursor.execute('UPDATE users SET following_count = following_count - 1 WHERE user_id = ?', (follower_id,))
    cursor.execute('UPDATE users SET followers_count = followers_count - 1 WHERE user_id = ?', (request.followed_id,))
    
    conn.commit()
    conn.close()
    
    return {"message": "Successfully unfollowed user!"}


@app.post("/upload-photo")
def upload_photo(file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    # Create the destination path using the original filename
    file_location = f"images/{file.filename}"
    
    # Save the physical file to the server
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"message": "File uploaded successfully", "photo_url": file_location}


@app.patch("/location")
def update_location(location: LocationUpdate, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE users 
        SET latitude = ?, longitude = ? 
        WHERE user_id = ?
    ''', (location.latitude, location.longitude, user_id))
    
    conn.commit()
    conn.close()
    
    return {"message": "Location updated successfully"}



def calculate_distance(lat1, lon1, lat2, lon2):
    # Earth radius in meters
    R = 6371000.0 
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

@app.get("/nearby")
def get_nearby_users(radius_meters: float = 500.0, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # 1. Get the current user's location
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id = ?", (user_id,))
    current_user = cursor.fetchone()
    
    if not current_user or (current_user[0] == 0.0 and current_user[1] == 0.0):
        conn.close()
        raise HTTPException(status_code=400, detail="User location not set")
        
    current_lat, current_lon = current_user
    
    # 2. Get all other users (excluding ghost mode)
    cursor.execute('''
        SELECT user_id, first_name, profile_picture_url, latitude, longitude 
        FROM users 
        WHERE user_id != ? AND ghost_mode_active = 0
    ''', (user_id,))
    
    all_users = cursor.fetchall()
    conn.close()
    
    # 3. Filter users by distance
    nearby_users = []
    for user in all_users:
        target_lat, target_lon = user[3], user[4]
        
        # Skip users who haven't set their location
        if target_lat == 0.0 and target_lon == 0.0:
            continue
            
        distance = calculate_distance(current_lat, current_lon, target_lat, target_lon)
        
        if distance <= radius_meters:
            nearby_users.append({
                "user_id": user[0],
                "first_name": user[1],
                "profile_picture_url": user[2],
                "distance_meters": round(distance, 2)
            })
            
    # Sort by closest first
    nearby_users.sort(key=lambda x: x["distance_meters"])
    
    return nearby_users

@app.post("/login")
def login_user(request: LoginRequest):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    # Find the user by email
    cursor.execute("SELECT user_id, password_hash FROM users WHERE email = ?", (request.email,))
    user = cursor.fetchone()
    conn.close()
    
    # If the email doesn't exist
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
        
    user_id, hashed_password = user
    
    # Check if the password matches the hash
    if not pwd_context.verify(request.password, hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
        
    # Create the token (Set to expire in 30 days so they stay logged in like Instagram)
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode = {"sub": str(user_id), "exp": expire}
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer", "user_id": user_id}



@app.post("/sightings/{sighting_id}/like")
def like_sighting(sighting_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('INSERT INTO likes (user_id, sighting_id) VALUES (?, ?)', (user_id, sighting_id))
        conn.commit()
        conn.close()
        return {"message": "Sighting liked"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="You already liked this sighting")

@app.delete("/sightings/{sighting_id}/like")
def unlike_sighting(sighting_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM likes WHERE user_id = ? AND sighting_id = ?', (user_id, sighting_id))
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="You have not liked this sighting")
        
    conn.commit()
    conn.close()
    return {"message": "Sighting unliked"}

@app.post("/sightings/{sighting_id}/comment")
def add_comment(sighting_id: int, request: CommentRequest, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO comments (user_id, sighting_id, content)
        VALUES (?, ?, ?)
    ''', (user_id, sighting_id, request.content))
    
    conn.commit()
    comment_id = cursor.lastrowid
    conn.close()
    
    return {"message": "Comment added", "comment_id": comment_id}

@app.get("/sightings/{sighting_id}/comments")
def get_comments(sighting_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.comment_id, c.content, c.created_at, u.user_id, u.first_name, u.profile_picture_url
        FROM comments c
        JOIN users u ON c.user_id = u.user_id
        WHERE c.sighting_id = ?
        ORDER BY c.created_at ASC
    ''', (sighting_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [
        {
            "comment_id": r[0],
            "content": r[1],
            "created_at": r[2],
            "user": {
                "user_id": r[3],
                "first_name": r[4],
                "profile_picture_url": r[5]
            }
        } for r in results
    ]


@app.post("/block")
def block_user(request: BlockRequest, user_id: int = Depends(get_current_user)):
    if user_id == request.blocked_id:
        raise HTTPException(status_code=400, detail="You cannot block yourself")

    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    try:
        # Insert the block record
        cursor.execute('INSERT INTO blocks (user_id, blocked_id) VALUES (?, ?)', (user_id, request.blocked_id))
        
        # If they were following each other, we should automatically remove the follows
        cursor.execute('DELETE FROM follows WHERE (follower_id = ? AND followed_id = ?) OR (follower_id = ? AND followed_id = ?)', 
                       (user_id, request.blocked_id, request.blocked_id, user_id))
        
        conn.commit()
        conn.close()
        return {"message": "User blocked successfully. Follows removed if they existed."}
        
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="You have already blocked this user")

@app.delete("/block")
def unblock_user(request: BlockRequest, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM blocks WHERE user_id = ? AND blocked_id = ?', (user_id, request.blocked_id))
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="You have not blocked this user")
        
    conn.commit()
    conn.close()
    return {"message": "User unblocked successfully"}


@app.get("/notifications")
def get_notifications(user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT notification_id, type, message, is_read, created_at 
        FROM notifications 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 20
    ''', (user_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [
        {
            "notification_id": r[0],
            "type": r[1],
            "message": r[2],
            "is_read": bool(r[3]),
            "created_at": r[4]
        } for r in results
    ]

@app.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect('app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE notifications 
        SET is_read = 1 
        WHERE notification_id = ? AND user_id = ?
    ''', (notification_id, user_id))
    
    conn.commit()
    rowcount = cursor.rowcount
    conn.close()
    
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    return {"message": "Notification marked as read"}