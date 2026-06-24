# GenAI Learning Mentor - Integration Validation Script

import os
import unittest
import sqlite3
import json

from app import app
import database
import rag_service

class TestLearningMentorApp(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    def test_database_initialization(self):
        """Verify that database tables are created correctly."""
        database.init_db()
        self.assertTrue(os.path.exists(database.DATABASE_PATH), "Database file not created.")

        # Query SQLite metadata to check for tables
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row['name'] for row in cursor.fetchall()]
        conn.close()

        expected_tables = ['users', 'study_plans', 'uploaded_materials', 'quiz_attempts', 'weak_areas']
        for table in expected_tables:
            self.assertIn(table, tables, f"Table {table} is missing from the database schema.")
        print("[PASS] Database initialization test passed.")

    def test_landing_page_redirect_or_load(self):
        """Verify that landing page is online and returns HTTP 200."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Learning Mentor', response.data)
        print("[PASS] Landing page validation passed.")

    def test_authentication_pages(self):
        """Verify auth route pages load."""
        response = self.client.get('/auth')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sign In', response.data)
        print("[PASS] Auth page validation passed.")

    def test_user_flow(self):
        """Verify that registering and logging in creates database records."""
        # Use a unique username for the test run
        test_username = f"testuser_{int(datetime_timestamp_mock())}"
        test_password = "password123"

        # 1. Test register
        response = self.client.post('/register', data={
            'username': test_username,
            'password': test_password,
            'confirm_password': test_password
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful', response.data)

        # 2. Test login
        response = self.client.post('/login', data={
            'username': test_username,
            'password': test_password
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Welcome back', response.data) # Dashboard welcome message
        print("[PASS] Registration and Login user flow test passed.")

        # Clean up test user
        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (test_username,))
        conn.commit()
        conn.close()

def datetime_timestamp_mock():
    import time
    return time.time()

if __name__ == "__main__":
    print("Starting validation checks on GenAI Learning Mentor...")
    unittest.main()
