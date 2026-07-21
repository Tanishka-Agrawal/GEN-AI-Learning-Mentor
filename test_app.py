
# GenAI Learning Mentor - Integration Validation Script

import os
import unittest
import sqlite3
import json

from app import app
import database
import rag_service

class TestLearningMentorApp(unittest.TestCase):
    def _clean_test_db(self):
        conn = database.get_db()
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("DELETE FROM users WHERE username LIKE 'sub_user_%' OR username LIKE 'attempt_user_%' OR username LIKE 'paywall_user_%' OR username LIKE 'limit_user_%' OR username LIKE 'testuser_%' OR username LIKE 'notify_user_%'")
        conn.commit()
        conn.close()

    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Clean DB before starting test to avoid conflicts
        self._clean_test_db()

        # Mock Gemini genai module to prevent outbound network requests and speed up tests
        from unittest.mock import MagicMock, patch
        self.genai_patcher = patch('app.genai')
        self.mock_genai = self.genai_patcher.start()

        self.mock_model = MagicMock()
        self.mock_genai.GenerativeModel.return_value = self.mock_model

        self.mock_chat = MagicMock()
        self.mock_response = MagicMock()
        self.mock_response.text = "Mocked Tutor Reply"
        self.mock_chat.send_message.return_value = self.mock_response
        self.mock_model.start_chat.return_value = self.mock_chat
        
        def mock_generate_content(prompt, *args, **kwargs):
            mock_resp = MagicMock()
            if "study plan" in prompt.lower() or "generate plan" in prompt.lower() or "subject:" in prompt.lower():
                mock_resp.text = json.dumps({
                    "subject": "Mock Subject",
                    "goal": "Mock Goal",
                    "deadline": "2026-12-31",
                    "hours_per_day": 2,
                    "weekly_milestones": [
                        {"week": 1, "focus": "Fundamentals", "objective": "Understand terminology", "tasks": ["Read Chapter 1"]}
                    ],
                    "daily_schedule": [
                        {"day": "Monday", "topics": "Definitions", "strategy": "Active recall", "hours": 2}
                    ],
                    "coach_advice": "Stay focused!"
                })
            else:
                # Default to Quiz JSON structure
                mock_resp.text = json.dumps({
                    "title": "Mock Quiz",
                    "questions": [
                        {
                            "question": "Mock Question?",
                            "type": "mcq",
                            "options": ["A", "B", "C", "D"],
                            "correct_answer": "A",
                            "explanation": "Mock explanation"
                        }
                    ]
                })
            return mock_resp

        self.mock_model.generate_content.side_effect = mock_generate_content

    def tearDown(self):
        self.genai_patcher.stop()
        self._clean_test_db()

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
        self.assertTrue(
            b'Learnmate AI' in response.data or b'Launch Free Dashboard' in response.data,
            "Landing page content did not include the expected branding text."
        )
        print("[PASS] Landing page validation passed.")

    def test_authentication_pages(self):
        """Verify auth route pages load."""
        response = self.client.get('/auth')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sign In', response.data)
        print("[PASS] Auth page validation passed.")

    def test_subscription_defaults_are_migrated_for_existing_users(self):
        """Verify free-plan defaults are applied automatically for users after migration."""
        database.init_db()
        user_id = database.create_user(f"sub_user_{int(datetime_timestamp_mock())}", "password123")
        self.assertIsNotNone(user_id)
        status = database.ensure_user_subscription_defaults(user_id)
        self.assertTrue(status)
        user = database.get_user_by_id(user_id)
        self.assertEqual(user['plan'], 'free')
        self.assertEqual(user['attempts_left'], 2)
        self.assertEqual(user['payment_status'], 'pending')

    def test_quiz_page_shows_paywall_after_two_free_attempts(self):
        """Verify the quiz page surfaces a pricing upgrade prompt once the free quota is exceeded."""
        test_username = f"paywall_user_{int(datetime_timestamp_mock())}"
        test_password = "password123"

        database.create_user(
            username=test_username,
            password=test_password,
            email=f"{test_username}@example.com",
            phone="+919876543210",
            email_verified=1,
            phone_verified=1,
            otp_verified=1
        )

        response = self.client.post('/login', data={
            'username': test_username,
            'password': test_password
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        user = database.authenticate_user(test_username, test_password)
        self.assertIsNotNone(user)

        for _ in range(3):
            database.add_quiz_attempt(user['id'], 'Trial Quiz', 2, 5, [], [])

        response = self.client.get('/quiz')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Upgrade to continue', html)
        self.assertIn('₹299/month', html)

        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (test_username,))
        conn.commit()
        conn.close()

    def test_quiz_page_shows_pricing_after_two_free_attempts(self):
        """Verify the quiz page exposes pricing only after the second free attempt is used."""
        test_username = f"attempt_user_{int(datetime_timestamp_mock())}"
        test_password = "password123"

        database.create_user(
            username=test_username,
            password=test_password,
            email=f"{test_username}@example.com",
            phone="+919876543210",
            email_verified=1,
            phone_verified=1,
            otp_verified=1
        )

        self.client.post('/login', data={
            'username': test_username,
            'password': test_password
        }, follow_redirects=True)

        user = database.authenticate_user(test_username, test_password)
        self.assertIsNotNone(user)
        for _ in range(2):
            database.add_quiz_attempt(user['id'], 'Trial Quiz', 2, 5, [], [])

        response = self.client.get('/quiz')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('2 free tries used', html)
        self.assertIn('/pricing', html)

        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (test_username,))
        conn.commit()
        conn.close()

    def test_user_flow(self):
        """Verify that registering and logging in creates database records."""
        # Use a unique username for the test run
        test_username = f"testuser_{int(datetime_timestamp_mock())}"
        test_password = "Password123!"

        # 1. Test register via API endpoints
        resp = self.client.post('/api/start-register', json={
            'username': test_username,
            'email': f"{test_username}@example.com",
            'phone': "+919876543210",
            'password': test_password,
            'verification_method': 'email'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Verification code sent successfully', resp.data)

        # Get code from session
        with self.client.session_transaction() as sess:
            otp_code = sess.get('reg_otp_code')

        # Verify registration
        resp = self.client.post('/api/verify-otp', json={
            'otp': otp_code
        })
        self.assertEqual(resp.status_code, 200)

        # 2. Test login
        response = self.client.post('/login', data={
            'username': test_username,
            'password': test_password
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data) # Dashboard welcome message
        print("[PASS] Registration and Login user flow test passed.")

        # Clean up test user
        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (test_username,))
        conn.commit()
        conn.close()

    def test_registration_notification_is_logged(self):
        """Verify that successful registration writes a backend notification entry."""
        test_username = f"notify_user_{int(datetime_timestamp_mock())}"
        test_password = "Password123!"
        log_path = os.path.join(os.path.dirname(__file__), 'instance', 'registration_events.log')

        if os.path.exists(log_path):
            os.remove(log_path)

        # Start registration via API
        resp = self.client.post('/api/start-register', json={
            'username': test_username,
            'email': f"{test_username}@example.com",
            'phone': "+919876543210",
            'password': test_password,
            'verification_method': 'email'
        })
        self.assertEqual(resp.status_code, 200)

        # Get code from session
        with self.client.session_transaction() as sess:
            otp_code = sess.get('reg_otp_code')

        # Verify registration
        resp = self.client.post('/api/verify-otp', json={
            'otp': otp_code
        })
        self.assertEqual(resp.status_code, 200)

        self.assertTrue(os.path.exists(log_path), "Registration notification log was not created.")

        with open(log_path, 'r', encoding='utf-8') as fh:
            content = fh.read()
        self.assertIn(test_username, content)

        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE username = ?", (test_username,))
        conn.commit()
        conn.close()

    def test_admin_bypass_and_auto_login(self):
        """Verify admin user 'tanishka253' is auto-created, bypasses limits, and gets free access."""
        with self.client.session_transaction() as session:
            # Manually trigger session creation if needed before the request
            pass

        with self.client as c: # 'c' will now persist the session
            # 1. Admin login auto-creation
            response = c.post('/login', data={
                'username': 'tanishka253',
                'password': '741963'
            }, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Dashboard', response.data) # Check for dashboard content

            user = database.get_user_by_username('tanishka253')
            self.assertIsNotNone(user, "Admin user 'tanishka253' was not created in the database.")
            self.assertEqual(user['username'], 'tanishka253')

            # 2. Add multiple quiz attempts & plans to database for admin
            for _ in range(5):
                database.add_quiz_attempt(user['id'], 'Admin Quiz', 1, 5, [], [])
                database.create_study_plan(user['id'], 'Admin Plan', 'Get A', '2026-12-31', 2, {})

            # 3. Verify admin does not see pricing paywall on /quiz page
            response = c.get('/quiz')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertNotIn('Upgrade to continue', html)
            self.assertNotIn('pricing-paywall-card', html)
            
            # 4. Verify admin does not see pricing paywall on /study-plan page
            response = c.get('/study-plan')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertNotIn('Upgrade to continue', html)
            self.assertNotIn('pricing-paywall-card', html)
            
            # 5. Clean up admin attempts and user since we want a clean state next run
            conn = database.get_db()
            conn.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user['id'],))
            conn.execute("DELETE FROM study_plans WHERE user_id = ?", (user['id'],))
            conn.execute("DELETE FROM users WHERE id = ?", (user['id'],))
            conn.commit()
            conn.close()

    def test_chat_remains_free_after_quiz_and_plan_limits_hit(self):
        """Verify AI chat does not lock out, while Quiz and Study Plan limit is enforced at 2."""
        test_username = f"limit_user_{int(datetime_timestamp_mock())}"
        test_password = "password123"

        database.create_user(
            username=test_username,
            password=test_password,
            email=f"{test_username}@example.com",
            phone="+919876543210",
            email_verified=1,
            phone_verified=1,
            otp_verified=1
        )

        self.client.post('/login', data={
            'username': test_username,
            'password': test_password
        }, follow_redirects=True)

        user = database.authenticate_user(test_username, test_password)
        self.assertIsNotNone(user)

        # 1. Study plan generation checks
        # Generate 1st plan
        response = self.client.post('/api/generate-plan', data=json.dumps({
            'subject': 'Chem', 'goal': 'Pass', 'deadline': '2026-12-31', 'hours_per_day': 2
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # Generate 2nd plan
        response = self.client.post('/api/generate-plan', data=json.dumps({
            'subject': 'Bio', 'goal': 'Pass', 'deadline': '2026-12-31', 'hours_per_day': 3
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # Generate 3rd plan - should fail with 403
        response = self.client.post('/api/generate-plan', data=json.dumps({
            'subject': 'Math', 'goal': 'Pass', 'deadline': '2026-12-31', 'hours_per_day': 4
        }), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'attempts are used up', response.data)

        # 2. Chat remains free and working
        response = self.client.post('/api/chat', data=json.dumps({
            'message': 'Hello Tutor', 'use_rag': False, 'history': []
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        # Clean up test user
        conn = database.get_db()
        conn.execute("DELETE FROM study_plans WHERE user_id = ?", (user['id'],))
        conn.execute("DELETE FROM users WHERE id = ?", (user['id'],))
        conn.commit()
        conn.close()

def datetime_timestamp_mock():
    import time
    return time.time()

if __name__ == "__main__":
    print("Starting validation checks on GenAI Learning Mentor...")
    unittest.main()
