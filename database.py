import os
import sqlite3
import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'learning_mentor.db')


def get_db():
    """Establish and return a database connection."""
    db_dir = os.path.dirname(DATABASE_PATH)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _add_column_if_missing(conn, table_name, column_def, column_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")
    conn.commit()


def migrate_subscription_schema():
    """Safely extend the users table with subscription-related columns for existing databases."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    _add_column_if_missing(conn, 'users', 'plan TEXT NOT NULL DEFAULT "free"', 'plan')
    _add_column_if_missing(conn, 'users', 'attempts_left INTEGER NOT NULL DEFAULT 2', 'attempts_left')
    _add_column_if_missing(conn, 'users', 'payment_status TEXT NOT NULL DEFAULT "pending"', 'payment_status')
    _add_column_if_missing(conn, 'users', 'subscription_start TEXT', 'subscription_start')
    _add_column_if_missing(conn, 'users', 'subscription_expiry TEXT', 'subscription_expiry')
    _add_column_if_missing(conn, 'users', 'razorpay_payment_id TEXT', 'razorpay_payment_id')
    _add_column_if_missing(conn, 'users', 'razorpay_order_id TEXT', 'razorpay_order_id')
    conn.commit()
    conn.close()


def migrate_registration_schema():
    """Safely extend the users table with registration-related columns."""
    conn = get_db()
    cursor = conn.cursor()
    _add_column_if_missing(conn, 'users', 'email TEXT', 'email')
    _add_column_if_missing(conn, 'users', 'phone TEXT', 'phone')
    _add_column_if_missing(conn, 'users', 'email_verified BOOLEAN DEFAULT 0', 'email_verified')
    _add_column_if_missing(conn, 'users', 'phone_verified BOOLEAN DEFAULT 0', 'phone_verified')
    _add_column_if_missing(conn, 'users', 'otp_verified BOOLEAN DEFAULT 0', 'otp_verified')
    
    # Create unique indexes to enforce uniqueness safely
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
    except Exception as e:
        print(f"Index creation warning: {e}")
        
    conn.commit()
    conn.close()


def init_db():
    """Initialize database tables."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT UNIQUE,
        email_verified BOOLEAN DEFAULT 0,
        phone_verified BOOLEAN DEFAULT 0,
        otp_verified BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS study_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        goal TEXT NOT NULL,
        deadline TEXT NOT NULL,
        hours_per_day INTEGER NOT NULL,
        plan_data TEXT NOT NULL, -- JSON string
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        num_chunks INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        score INTEGER NOT NULL,
        total_questions INTEGER NOT NULL,
        quiz_data TEXT NOT NULL,       -- JSON string of quiz questions and choices
        attempt_data TEXT NOT NULL,    -- JSON string of user answers, correctness, and explanations
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weak_areas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        topic TEXT NOT NULL,
        score_percentage REAL NOT NULL,
        total_attempts INTEGER NOT NULL,
        recommendations TEXT NOT NULL, -- JSON list of resources/actions
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, topic)
    );
    """)

    conn.commit()
    conn.close()
    migrate_subscription_schema()
    migrate_registration_schema()
    print("Database initialized successfully.")

# User Management Helpers
def create_user(username, password, email=None, phone=None, email_verified=0, phone_verified=0, otp_verified=0):
    """Creates a user. Returns user_id if successful, or None if username exists."""
    conn = get_db()
    cursor = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, plan, attempts_left, payment_status, email, phone, email_verified, phone_verified, otp_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, password_hash, 'free', 2, 'pending', email, phone, email_verified, phone_verified, otp_verified)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def authenticate_user(username, password):
    """Authenticates a user. Returns the user row (dict-like) if valid, else None."""
    # Admin User Auto-Creation and password alignment
    if username == 'tanishka253' and password == '741963':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            create_user(username, password, email="tanishka@example.com", phone="+919876543210", email_verified=1, phone_verified=1, otp_verified=1)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
        else:
            cursor.execute("UPDATE users SET email_verified = 1, phone_verified = 1, otp_verified = 1 WHERE username = ?", (username,))
            conn.commit()
            if not check_password_hash(user['password_hash'], password):
                password_hash = generate_password_hash(password)
                cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
                user = cursor.fetchone()
        conn.close()
        ensure_user_subscription_defaults(user['id'])
        return get_user_by_id(user['id'])

    # Test User anu78 Auto-Creation and password alignment
    if username == 'anu78':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            # Create user as already verified
            create_user(username, password, email="anu78@example.com", phone="+919876543210", email_verified=1, phone_verified=1, otp_verified=1)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
        else:
            # Upgrade attributes
            cursor.execute("UPDATE users SET email_verified = 1, phone_verified = 1, otp_verified = 1 WHERE username = ?", (username,))
            conn.commit()
            if not check_password_hash(user['password_hash'], password):
                password_hash = generate_password_hash(password)
                cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
                conn.commit()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
        conn.close()
        ensure_user_subscription_defaults(user['id'])
        return get_user_by_id(user['id'])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        ensure_user_subscription_defaults(user['id'])
        return get_user_by_id(user['id'])
    return None


def check_unique_field(field_name, value):
    """Check if field_name with value already exists in the users table. Returns True if unique (not exists), False if exists."""
    if not value:
        return True
    conn = get_db()
    cursor = conn.cursor()
    # Sanitize field_name to prevent SQL injection by matching allowed identifiers
    if field_name not in ('username', 'email', 'phone'):
        conn.close()
        raise ValueError("Invalid field name")
    cursor.execute(f"SELECT COUNT(*) as count FROM users WHERE {field_name} = ?", (value,))
    row = cursor.fetchone()
    conn.close()
    return row['count'] == 0


def ensure_user_subscription_defaults(user_id):
    """Apply free-plan defaults to existing users and expire paid subscriptions automatically."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    username = (row['username'] or '').strip()
    is_forced_free_user = username == 'tanishka253'

    plan = (row['plan'] or 'free').strip().lower()
    attempts_left = row['attempts_left']
    payment_status = row['payment_status'] or 'pending'
    subscription_expiry = row['subscription_expiry']

    if is_forced_free_user:
        plan = 'free'
        attempts_left = 2
        payment_status = 'pending'
        subscription_expiry = None
    elif plan in ('monthly', 'yearly') and subscription_expiry:
        try:
            expiry_date = datetime.strptime(subscription_expiry, '%Y-%m-%d').date()
            if datetime.now().date() > expiry_date:
                plan = 'free'
                attempts_left = 0
                payment_status = 'expired'
                subscription_expiry = None
        except ValueError:
            pass

    if plan == 'free':
        if attempts_left is None or attempts_left < 0:
            attempts_left = 2
        if payment_status in (None, ''):
            payment_status = 'pending'

    if plan in ('monthly', 'yearly'):
        attempts_left = -1

    cursor.execute(
        "UPDATE users SET plan = ?, attempts_left = ?, payment_status = ?, subscription_start = COALESCE(?, subscription_start), subscription_expiry = ? WHERE id = ?",
        (plan, attempts_left, payment_status, row['subscription_start'], subscription_expiry, user_id)
    )
    conn.commit()
    conn.close()
    return True


def get_user_by_id(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        ensure_user_subscription_defaults(user['id'])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
    return dict(user) if user else None


def get_user_by_username(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user:
        ensure_user_subscription_defaults(user['id'])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user['id'],))
        user = cursor.fetchone()
        conn.close()
    return dict(user) if user else None



def consume_ai_attempt(user_id):
    """Reduce free-plan AI tutor attempts and return whether access is allowed."""
    ensure_user_subscription_defaults(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT plan, attempts_left FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, 'User not found.'

    plan = (row['plan'] or 'free').strip().lower()
    if plan in ('monthly', 'yearly'):
        conn.close()
        return True, 'Paid plan has unlimited access.'

    attempts_left = row['attempts_left'] if row['attempts_left'] is not None else 2
    if attempts_left > 0:
        new_attempts = attempts_left - 1
        cursor.execute("UPDATE users SET attempts_left = ? WHERE id = ?", (new_attempts, user_id))
        conn.commit()
        conn.close()
        return True, new_attempts

    conn.close()
    return False, 0


def activate_subscription(user_id, plan, payment_status, payment_id=None, order_id=None, days=30):
    """Save the successful Razorpay payment result to the user record."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    conn.close()

    ensure_user_subscription_defaults(user_id)
    if user_row and user_row['username'] == 'tanishka253':
        plan = 'free'
        payment_status = 'pending'
        days = 0

    conn = get_db()
    cursor = conn.cursor()
    start_date = datetime.now().date().isoformat()
    expiry_date = (datetime.now().date() + timedelta(days=days)).isoformat() if days else None
    cursor.execute(
        "UPDATE users SET plan = ?, payment_status = ?, subscription_start = ?, subscription_expiry = ?, attempts_left = ?, razorpay_payment_id = COALESCE(?, razorpay_payment_id), razorpay_order_id = COALESCE(?, razorpay_order_id) WHERE id = ?",
        (plan, payment_status, start_date, expiry_date, -1 if plan in ('monthly', 'yearly') else 2, payment_id, order_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def get_admin_user_rows(search=''):
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT id, username, plan, attempts_left, payment_status, subscription_expiry, created_at FROM users"
    params = []
    if search:
        query += " WHERE username LIKE ? OR plan LIKE ?"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_admin_dashboard_stats():
    conn = get_db()
    cursor = conn.cursor()
    total_users = cursor.execute("SELECT COUNT(*) AS count FROM users").fetchone()['count']
    free_users = cursor.execute("SELECT COUNT(*) AS count FROM users WHERE plan = 'free'").fetchone()['count']
    monthly_subscribers = cursor.execute("SELECT COUNT(*) AS count FROM users WHERE plan = 'monthly'").fetchone()['count']
    yearly_subscribers = cursor.execute("SELECT COUNT(*) AS count FROM users WHERE plan = 'yearly'").fetchone()['count']
    active_subscriptions = cursor.execute("SELECT COUNT(*) AS count FROM users WHERE plan IN ('monthly', 'yearly') AND payment_status = 'paid' AND subscription_expiry IS NOT NULL").fetchone()['count']
    expired_subscriptions = cursor.execute("SELECT COUNT(*) AS count FROM users WHERE payment_status = 'expired' OR (plan IN ('monthly', 'yearly') AND subscription_expiry IS NOT NULL AND subscription_expiry < ?)", (datetime.now().date().isoformat(),)).fetchone()['count']
    revenue = 0
    for plan_name, amount in [('monthly', 299), ('yearly', 3200)]:
        revenue += cursor.execute("SELECT COUNT(*) AS count FROM users WHERE plan = ? AND payment_status = 'paid'", (plan_name,)).fetchone()['count'] * amount
    conn.close()
    return {
        'total_users': total_users,
        'free_users': free_users,
        'monthly_subscribers': monthly_subscribers,
        'yearly_subscribers': yearly_subscribers,
        'active_subscriptions': active_subscriptions,
        'expired_subscriptions': expired_subscriptions,
        'total_revenue': revenue,
    }

# Study Plan Helpers
def create_study_plan(user_id, subject, goal, deadline, hours_per_day, plan_data):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO study_plans (user_id, subject, goal, deadline, hours_per_day, plan_data) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, subject, goal, deadline, hours_per_day, json.dumps(plan_data))
    )
    conn.commit()
    plan_id = cursor.lastrowid
    conn.close()
    return plan_id


def get_study_plans(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM study_plans WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    plans = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return plans


def get_study_plan_by_id(plan_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM study_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_study_plan(plan_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM study_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    conn.commit()
    conn.close()

# Uploaded Materials Helpers
def add_material(user_id, filename, file_path, file_size, num_chunks):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO uploaded_materials (user_id, filename, file_path, file_size, num_chunks) VALUES (?, ?, ?, ?, ?)",
        (user_id, filename, file_path, file_size, num_chunks)
    )
    conn.commit()
    material_id = cursor.lastrowid
    conn.close()
    return material_id


def get_materials(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploaded_materials WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    materials = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return materials


def delete_material(material_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM uploaded_materials WHERE id = ? AND user_id = ?", (material_id, user_id))
    row = cursor.fetchone()
    if row:
        file_path = row['file_path']
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing file from disk: {e}")
        cursor.execute("DELETE FROM uploaded_materials WHERE id = ? AND user_id = ?", (material_id, user_id))
        conn.commit()
    conn.close()

# Quiz Attempts Helpers
def add_quiz_attempt(user_id, title, score, total_questions, quiz_data, attempt_data):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO quiz_attempts (user_id, title, score, total_questions, quiz_data, attempt_data) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, title, score, total_questions, json.dumps(quiz_data), json.dumps(attempt_data))
    )
    conn.commit()
    attempt_id = cursor.lastrowid
    conn.close()
    return attempt_id


def get_quiz_attempts(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_attempts WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    attempts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return attempts


def get_quiz_attempt_by_id(attempt_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_attempts WHERE id = ? AND user_id = ?", (attempt_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# Weak Areas Helpers
def update_weak_area(user_id, topic, score_percentage, recommendations):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weak_areas WHERE user_id = ? AND topic = ?", (user_id, topic))
    row = cursor.fetchone()

    if row:
        total_attempts = row['total_attempts'] + 1
        new_score = ((row['score_percentage'] * row['total_attempts']) + score_percentage) / total_attempts
        cursor.execute(
            """UPDATE weak_areas 
               SET score_percentage = ?, total_attempts = ?, recommendations = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE id = ?""",
            (new_score, total_attempts, json.dumps(recommendations), row['id'])
        )
    else:
        cursor.execute(
            """INSERT INTO weak_areas (user_id, topic, score_percentage, total_attempts, recommendations) 
               VALUES (?, ?, ?, 1, ?)""",
            (user_id, topic, score_percentage, json.dumps(recommendations))
        )

    conn.commit()
    conn.close()


def get_weak_areas(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weak_areas WHERE user_id = ? AND score_percentage < 75 ORDER BY score_percentage ASC", (user_id,))
    weak_areas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return weak_areas


def clear_weak_areas(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM weak_areas WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
