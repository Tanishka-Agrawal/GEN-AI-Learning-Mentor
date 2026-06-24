import os
import sqlite3
import json
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'learning_mentor.db')

def get_db():
    """Establish and return a database connection."""
    # Ensure the directory exists
    db_dir = os.path.dirname(DATABASE_PATH)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize database tables."""
    conn = get_db()
    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Study Plans Table
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

    # Uploaded Materials Table
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

    # Quiz Attempts Table
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

    # Weak Areas Table
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
    print("Database initialized successfully.")

# User Management Helpers
def create_user(username, password):
    """Creates a user. Returns user_id if successful, or None if username exists."""
    conn = get_db()
    cursor = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def get_user_by_id(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

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
    # First get file path to delete from disk
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
    
    # Check if entry exists
    cursor.execute("SELECT * FROM weak_areas WHERE user_id = ? AND topic = ?", (user_id, topic))
    row = cursor.fetchone()
    
    if row:
        # Calculate moving average score
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
    # We retrieve them where score_percentage < 75 (weak areas threshold)
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
