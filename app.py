import os
import hashlib
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
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
    """)
    # Create default admin if none exists
    cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if not cur.fetchone():
        pw_hash = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            ('admin', 'Admin', pw_hash, 'admin')
        )
        conn.commit()
    conn.close()

init_db()

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
    return render_template('admin.html', users=users)

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
    if not username or not display_name or not password:
        return jsonify({'success': False, 'error': 'Username, display name and password are required.'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'error': 'Password must be at least 4 characters.'}), 400
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, display_name, generate_password_hash(password), 'member')
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
    for mt, exts in ALLOWED_MEDIA.items():
        if ext in exts:
            media_type = mt
            break
    if not media_type:
        return jsonify({'success': False, 'error': 'File type not allowed.'}), 400

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    path = os.path.join(UPLOAD_DIR, unique_name)

    try:
        if ext in ('heic', 'heif'):
            from PIL import Image
            from pillow_heif import register_heif_opener
            register_heif_opener()
            img = Image.open(file.stream)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            unique_name = unique_name.rsplit('.', 1)[0] + '.jpg'
            path = os.path.join(UPLOAD_DIR, unique_name)
            img.save(path, 'JPEG', quality=90)
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
