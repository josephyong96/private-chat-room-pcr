import os
import json
import base64
import hashlib
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from cryptography.hazmat.primitives import serialization
import sqlite3
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

ROOM_NAME = 'pcr-family'
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'chat.db'))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(os.path.dirname(__file__), 'uploads'))
DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin1234')

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_MEDIA = {
    'image': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'},
    'video': {'mp4', 'mov', 'webm'},
    'audio': {'mp3', 'ogg', 'wav', 'm4a', 'webm'},
    'document': {'pdf'}
}

VAPID_CLAIM_EMAIL = os.environ.get('VAPID_CLAIM_EMAIL', 'mailto:admin@pcr.local')

def get_or_create_vapid_keys():
    keys_path = os.path.join(os.path.dirname(DB_PATH), 'vapid_keys.json')
    if os.path.exists(keys_path):
        with open(keys_path, 'r') as f:
            return json.load(f)
    from pywebpush import Vapid
    v = Vapid()
    v.generate_keys()
    private_pem = v.private_pem().decode('utf-8')
    public_raw = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint
    )
    public_b64u = base64.urlsafe_b64encode(public_raw).decode('utf-8').rstrip('=')
    keys = {
        'private_pem': private_pem,
        'public_key': public_b64u
    }
    with open(keys_path, 'w') as f:
        json.dump(keys, f)
    return keys

VAPID_KEYS = get_or_create_vapid_keys()

from pywebpush import webpush, WebPushException

def send_push_to_all(sender_id, title, body):
    conn = get_db()
    subs = conn.execute(
        "SELECT id, subscription FROM push_subscriptions WHERE user_id != ?",
        (sender_id,)
    ).fetchall()
    conn.close()
    payload = json.dumps({'title': title, 'body': body, 'url': '/chat'})
    removed = []
    for sub in subs:
        try:
            webpush(
                subscription_info=json.loads(sub['subscription']),
                data=payload,
                vapid_private_key=VAPID_KEYS['private_pem'],
                vapid_claims={'sub': VAPID_CLAIM_EMAIL}
            )
        except WebPushException as e:
            if getattr(e, 'response', None) and e.response.status_code in (404, 410):
                removed.append(sub['id'])
        except Exception:
            pass
    if removed:
        conn = get_db()
        conn.executemany("DELETE FROM push_subscriptions WHERE id = ?", [(i,) for i in removed])
        conn.commit()
        conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            is_superuser INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            profile_picture TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            content TEXT,
            file_name TEXT,
            file_type TEXT,
            media_type TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS read_receipts (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subscription TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id)
        );
    """)
    # Create default admin if none exists
    cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if not cur.fetchone():
        pw_hash = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_superuser) VALUES (?, ?, ?, ?, ?)",
            ('admin', 'Admin', pw_hash, 'admin', 1)
        )
        conn.commit()
    conn.close()

init_db()

def migrate_db():
    """Add columns introduced in newer app versions to existing databases."""
    conn = get_db()
    cur = conn.cursor()
    
    # Migrate messages table
    cur.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cur.fetchall()}
    
    if 'media_type' not in columns:
        cur.execute("ALTER TABLE messages ADD COLUMN media_type TEXT")
    if 'deleted' not in columns:
        cur.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    
    # Migrate users table
    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}
    if 'is_superuser' not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN is_superuser INTEGER NOT NULL DEFAULT 0")
        # Promote the very first admin as superuser
        cur.execute("UPDATE users SET is_superuser = 1 WHERE id = (SELECT MIN(id) FROM users WHERE role = 'admin')")
    if 'status' not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN status TEXT")
    if 'profile_picture' not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
    
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_subscriptions'")
    if not cur.fetchone():
        cur.execute("""
            CREATE TABLE push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subscription TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            )
        """)
    
    conn.commit()
    conn.close()

migrate_db()

def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        conn = get_db()
        user = conn.execute("SELECT role FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        conn.close()
        if not user or user['role'] != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('chat'))
        return f(*args, **kwargs)
    return wrapper

def current_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    return user

@app.after_request
def add_no_cache_headers(response):
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username.lower(),)
        ).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            return redirect(url_for('chat'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@require_login
def profile():
    user = current_user()
    if request.method == 'POST':
        display_name = (request.form.get('display_name') or '').strip()
        status_text = (request.form.get('status') or '').strip()
        if not display_name:
            flash('Display name is required.', 'error')
            return redirect(url_for('profile'))

        profile_picture = user['profile_picture']
        file = request.files.get('profile_picture')
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in ALLOWED_MEDIA['image']:
                flash('Profile picture must be an image.', 'error')
                return redirect(url_for('profile'))
            try:
                from PIL import Image
                file.stream.seek(0)
                if ext in ('heic', 'heif'):
                    from pillow_heif import register_heif_opener
                    register_heif_opener()
                img = Image.open(file.stream)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                # Square crop from center then resize
                size = min(img.width, img.height)
                left = (img.width - size) // 2
                top = (img.height - size) // 2
                img = img.crop((left, top, left + size, top + size))
                img.thumbnail((400, 400), Image.Resampling.LANCZOS)
                unique_name = f"pp_{uuid.uuid4().hex}.jpg"
                path = os.path.join(UPLOAD_DIR, unique_name)
                img.save(path, 'JPEG', quality=85, optimize=True)
                profile_picture = unique_name
            except Exception as e:
                flash('Failed to process image: ' + str(e), 'error')
                return redirect(url_for('profile'))

        conn = get_db()
        conn.execute(
            "UPDATE users SET display_name = ?, status = ?, profile_picture = ? WHERE id = ?",
            (display_name, status_text, profile_picture, session['user_id'])
        )
        conn.commit()
        conn.close()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user)

@app.route('/chat')
@require_login
def chat():
    user = current_user()
    return render_template('chat.html', user=user, room=ROOM_NAME)

@app.route('/admin')
@require_admin
def admin():
    conn = get_db()
    users = conn.execute(
        "SELECT id, username, display_name, role, is_active, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    user = current_user()
    return render_template('admin.html', users=users, current_user=user)

@app.route('/api/messages')
@require_login
def api_messages():
    conn = get_db()
    rows = conn.execute("""
        SELECT m.id, m.sender_id, m.content, m.file_name, m.file_type, m.media_type, m.created_at, m.deleted,
               u.display_name, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.deleted = 0
        ORDER BY m.id DESC
        LIMIT 200
    """).fetchall()
    conn.close()
    messages = []
    for r in rows:
        messages.append({
            'id': r['id'],
            'sender_id': r['sender_id'],
            'sender_name': r['display_name'],
            'username': r['username'],
            'content': r['content'],
            'file_name': r['file_name'],
            'file_type': r['file_type'],
            'media_type': r['media_type'],
            'created_at': r['created_at'],
            'deleted': r['deleted']
        })
    return jsonify({'messages': list(reversed(messages))})

@app.route('/api/members')
@require_login
def api_members():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, role FROM users WHERE is_active = 1 ORDER BY display_name"
    ).fetchall()
    conn.close()
    return jsonify({'members': [dict(r) for r in rows]})

@app.route('/api/admin/add-member', methods=['POST'])
@require_admin
def add_member():
    data = request.get_json()
    username = (data.get('username') or '').strip().lower()
    display_name = (data.get('display_name') or '').strip()
    password = data.get('password', '')
    requested_role = (data.get('role') or 'member').strip().lower()
    if not username or not display_name or not password:
        return jsonify({'success': False, 'error': 'Username, display name and password are required.'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'error': 'Password must be at least 4 characters.'}), 400
    if requested_role not in ('member', 'admin'):
        return jsonify({'success': False, 'error': 'Invalid role.'}), 400

    conn = get_db()
    current = conn.execute("SELECT is_superuser FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    if requested_role == 'admin' and (not current or not current['is_superuser']):
        conn.close()
        return jsonify({'success': False, 'error': 'Only superuser can create admins.'}), 403

    try:
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, display_name, generate_password_hash(password), requested_role)
        )
        conn.commit()
        conn.close()
        socketio.emit('member_joined', {'username': username, 'display_name': display_name}, room=ROOM_NAME)
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Username already exists.'}), 400

@app.route('/api/admin/remove-member', methods=['POST'])
@require_admin
def remove_member():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'User ID required.'}), 400
    if int(user_id) == session['user_id']:
        return jsonify({'success': False, 'error': 'Cannot remove yourself.'}), 400
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/reset-password', methods=['POST'])
@require_admin
def reset_password():
    data = request.get_json()
    user_id = data.get('user_id')
    new_password = data.get('new_password', '')
    if not user_id or not new_password:
        return jsonify({'success': False, 'error': 'User ID and new password required.'}), 400
    if len(new_password) < 4:
        return jsonify({'success': False, 'error': 'Password must be at least 4 characters.'}), 400
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/change-role', methods=['POST'])
@require_admin
def change_role():
    data = request.get_json()
    user_id = data.get('user_id')
    new_role = (data.get('role') or '').strip().lower()
    if not user_id or not new_role:
        return jsonify({'success': False, 'error': 'User ID and role required.'}), 400
    if new_role not in ('member', 'admin'):
        return jsonify({'success': False, 'error': 'Invalid role.'}), 400
    if int(user_id) == session['user_id']:
        return jsonify({'success': False, 'error': 'Cannot change your own role.'}), 400

    conn = get_db()
    current = conn.execute("SELECT is_superuser FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    if not current or not current['is_superuser']:
        conn.close()
        return jsonify({'success': False, 'error': 'Only superuser can change roles.'}), 403

    target = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'success': False, 'error': 'User not found.'}), 404

    conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/delete-message', methods=['POST'])
@require_admin
def delete_message():
    data = request.get_json()
    message_id = data.get('message_id')
    if not message_id:
        return jsonify({'success': False, 'error': 'Message ID required.'}), 400
    conn = get_db()
    conn.execute("UPDATE messages SET deleted = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    socketio.emit('message_deleted', {'message_id': message_id}, room=ROOM_NAME)
    return jsonify({'success': True})

@app.route('/api/admin/clear-chat', methods=['POST'])
@require_admin
def clear_chat():
    conn = get_db()
    conn.execute("UPDATE messages SET deleted = 1")
    conn.commit()
    conn.close()
    socketio.emit('chat_cleared', {}, room=ROOM_NAME)
    return jsonify({'success': True})

@app.route('/api/vapid-public-key')
@require_login
def vapid_public_key():
    return jsonify({'public_key': VAPID_KEYS.get('public_key')})

@app.route('/api/push-subscribe', methods=['POST'])
@require_login
def push_subscribe():
    data = request.get_json()
    subscription = data.get('subscription')
    if not subscription:
        return jsonify({'success': False, 'error': 'Subscription required.'}), 400
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO push_subscriptions (user_id, subscription) VALUES (?, ?)",
        (session['user_id'], json.dumps(subscription))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
@require_login
def upload():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided.'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Empty file.'}), 400
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    media_type = None
    # Prefer the file's actual MIME type; fall back to extension
    content_type = (file.content_type or '').lower()
    is_voice_note = 'voice-note' in filename.lower()
    if content_type.startswith('image/'):
        media_type = 'image'
    elif content_type.startswith('audio/') or is_voice_note:
        media_type = 'audio'
    elif content_type.startswith('video/'):
        media_type = 'video'
    elif content_type == 'application/pdf':
        media_type = 'document'
    else:
        for mt, exts in ALLOWED_MEDIA.items():
            if ext in exts:
                media_type = mt
                break
    if not media_type:
        return jsonify({'success': False, 'error': 'File type not allowed.'}), 400

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    path = os.path.join(UPLOAD_DIR, unique_name)

    try:
        if media_type == 'image':
            from PIL import Image
            file.stream.seek(0)
            if ext in ('heic', 'heif'):
                from pillow_heif import register_heif_opener
                register_heif_opener()
            img = Image.open(file.stream)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            # Resize if larger than 1920px on any side
            max_size = 1920
            if max(img.width, img.height) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            # Save as JPEG with 85% quality
            unique_name = unique_name.rsplit('.', 1)[0] + '.jpg'
            path = os.path.join(UPLOAD_DIR, unique_name)
            img.save(path, 'JPEG', quality=85, optimize=True)
            ext = 'jpg'
            media_type = 'image'
        else:
            file.save(path)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'file_name': filename,
        'file_url': f"/uploads/{unique_name}",
        'file_type': ext,
        'media_type': media_type
    })

@app.route('/sw.js')
@require_login
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/uploads/<path:filename>')
@require_login
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# SocketIO events
@socketio.on('connect')
def handle_connect():
    user = current_user()
    if not user:
        return False
    join_room(ROOM_NAME)
    emit('joined', {'user': user['display_name'], 'room': ROOM_NAME})

@socketio.on('disconnect')
def handle_disconnect():
    leave_room(ROOM_NAME)

@socketio.on('send_message')
def handle_send_message(data):
    user = current_user()
    if not user:
        return
    content = (data.get('content') or '').strip()
    file_info = data.get('file') or {}
    if not content and not file_info.get('file_url'):
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (sender_id, content, file_name, file_type, media_type) VALUES (?, ?, ?, ?, ?)",
        (user['id'], content, file_info.get('file_name'), file_info.get('file_type'), file_info.get('media_type'))
    )
    message_id = cur.lastrowid
    conn.commit()
    row = conn.execute("""
        SELECT m.*, u.display_name, u.username FROM messages m
        JOIN users u ON m.sender_id = u.id WHERE m.id = ?
    """, (message_id,)).fetchone()
    conn.close()

    payload = {
        'id': row['id'],
        'sender_id': row['sender_id'],
        'sender_name': row['display_name'],
        'username': row['username'],
        'content': row['content'],
        'file_name': row['file_name'],
        'file_type': row['file_type'],
        'media_type': row['media_type'],
        'file_url': file_info.get('file_url'),
        'created_at': row['created_at']
    }
    emit('new_message', payload, room=ROOM_NAME)

    # Send push notifications to offline users
    try:
        preview = (row['content'] or '')[:60]
        if not preview and row['file_name']:
            preview = '📎 Attachment'
        send_push_to_all(
            user['id'],
            f"{row['display_name']} in PCR",
            preview or 'New message'
        )
    except Exception:
        pass

@socketio.on('mark_read')
def handle_mark_read(data):
    user = current_user()
    if not user:
        return
    message_id = data.get('message_id')
    if not message_id:
        return
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO read_receipts (message_id, user_id) VALUES (?, ?)",
        (message_id, user['id'])
    )
    conn.commit()
    conn.close()
    emit('read_receipt', {'message_id': message_id, 'user_id': user['id']}, room=ROOM_NAME)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
