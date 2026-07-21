import os
import json
import sqlite3
import hashlib
import hmac
import random
import time
import re
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

import database
import rag_service

# Load env configurations
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
# Secure secret key loading
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_mentor_sec_key_2026")
FREE_QUIZ_ATTEMPTS = 2
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
REGISTRATION_LOG_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'registration_events.log')
os.makedirs(os.path.dirname(REGISTRATION_LOG_PATH), exist_ok=True)

# Import google-generativeai client
import google.generativeai as genai
api_key = os.getenv("GEMINI_API_KEY")
if api_key and not api_key.startswith("your_") and api_key.strip():
    genai.configure(api_key=api_key)
else:
    api_key = None

FREE_QUIZ_ATTEMPTS = 2

# Helper function to clean and parse JSON from LLM outputs
def clean_and_parse_json(text):
    """Robust helper to extract JSON data from Markdown or raw completion strings."""
    if not text:
        return {}
    
    cleaned = text.strip()
    # Remove markdown code block wrappings if present
    if cleaned.startswith("```"):
        # Remove leading ```json or ```
        first_line_end = cleaned.find("\n")
        if first_line_end != -1:
            cleaned = cleaned[first_line_end:].strip()
        else:
            cleaned = cleaned[3:].strip()
            
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
            
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"JSON Parse error: {e}. Output was:\n{text}")
        # Try to find brackets as fallback
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1:
            try:
                return json.loads(cleaned[start_idx:end_idx+1])
            except Exception as e2:
                print(f"Fallback parse failed: {e2}")
        return None


def log_registration_notification(username, user_id):
    """Emit a backend notification for a newly registered user."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] NEW REGISTRATION - username='{username}', user_id={user_id}"
    print(message, flush=True)
    with open(REGISTRATION_LOG_PATH, 'a', encoding='utf-8') as handle:
        handle.write(message + "\n")
    return message


def sync_user_session(user_id):
    """Synchronize the session with the current subscription and free-attempt state."""
    user = database.get_user_by_id(user_id)
    if not user:
        return False

    database.ensure_user_subscription_defaults(user_id)
    user = database.get_user_by_id(user_id)
    session['plan'] = (user.get('plan') or 'free').lower()
    plan = session['plan']
    if plan in ('monthly', 'yearly') or user.get('username') == 'tanishka253':
        session['attempts_left'] = -1
        session['quiz_attempts_left'] = -1
        session['plan_attempts_left'] = -1
    else:
        used_quiz_attempts = len(database.get_quiz_attempts(user_id))
        used_plan_attempts = len(database.get_study_plans(user_id))
        session['quiz_attempts_left'] = max(0, FREE_QUIZ_ATTEMPTS - used_quiz_attempts)
        session['plan_attempts_left'] = max(0, 2 - used_plan_attempts)
        session['attempts_left'] = session['quiz_attempts_left']
    session['payment_status'] = user.get('payment_status') or 'pending'
    session['subscription_expiry'] = user.get('subscription_expiry')
    return True

# Middleware to require login
@app.before_request
def require_login():
    # Endpoints that are accessible without login
    allowed_routes = [
        'landing_route', 'auth_route', 'login_route', 'register_route', 'static', 'pricing_route',
        'api_start_register', 'api_verify_otp', 'api_resend_otp'
    ]
    if request.path.startswith('/api/start-register') or request.path.startswith('/api/verify-otp') or request.path.startswith('/api/resend-otp'):
        return
    if request.endpoint in allowed_routes or request.path.startswith('/static') or request.path == '/favicon.ico':
        if 'user_id' in session:
            sync_user_session(session['user_id'])
        return
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required.'}), 401
        return redirect(url_for('auth_route'))

    user = database.get_user_by_id(session['user_id'])
    if user:
        sync_user_session(session['user_id'])

# --- WEB PAGE ROUTING ---

@app.route('/')
def landing_route():
    if 'user_id' in session:
        return redirect(url_for('dashboard_route'))
    return render_template('landing.html')

@app.route('/auth', methods=['GET'])
def auth_route():
    if 'user_id' in session:
        return redirect(url_for('dashboard_route'))
    tab = request.args.get('tab', 'login')
    return render_template('auth.html', tab=tab)

def validate_password_strength(password, username=''):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character."
    if username and username.lower() in password.lower():
        return False, "Password cannot contain your username."
    return True, ""

def generate_otp():
    return str(random.randint(100000, 999999))

def _is_placeholder(val):
    if not val:
        return True
    val_upper = val.upper().strip()
    return "YOUR_" in val_upper or "CHANGE_THIS" in val_upper or val_upper == "PLACEHOLDER"

def _otp_dev_mode_enabled():
    """Simulate OTP delivery when no provider credentials are configured (local dev)."""
    flag = os.getenv("OTP_DEV_MODE", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
        
    smtp_configured = bool(
        os.getenv("SMTP_SERVER") and not _is_placeholder(os.getenv("SMTP_SERVER")) and
        os.getenv("SMTP_USERNAME") and not _is_placeholder(os.getenv("SMTP_USERNAME")) and
        os.getenv("SMTP_PASSWORD") and not _is_placeholder(os.getenv("SMTP_PASSWORD"))
    )
    sms_configured = bool(
        (os.getenv("TWILIO_ACCOUNT_SID") and not _is_placeholder(os.getenv("TWILIO_ACCOUNT_SID")) and
         os.getenv("TWILIO_AUTH_TOKEN") and not _is_placeholder(os.getenv("TWILIO_AUTH_TOKEN")) and
         os.getenv("TWILIO_FROM_NUMBER") and not _is_placeholder(os.getenv("TWILIO_FROM_NUMBER")))
        or (os.getenv("FAST2SMS_API_KEY") and not _is_placeholder(os.getenv("FAST2SMS_API_KEY")))
    )
    
    if flag in ("0", "false", "no"):
        if not smtp_configured and not sms_configured:
            print("[DEV OPT FALLBACK] SMTP and SMS credentials are unconfigured or placeholders. Overriding to simulated delivery.", flush=True)
            return True
        return False
        
    return not smtp_configured and not sms_configured

def send_email_otp(email, otp_code):
    if _otp_dev_mode_enabled():
        print(
            f"[MAIL OTP DEV] Simulated email delivery to {email}. OTP: {otp_code}",
            flush=True,
        )
        return True

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    body = (
        "Welcome to Learnmate AI!\n\n"
        f"Your verification code is:\n\n{otp_code}\n\n"
        "This code expires in 5 minutes.\n"
    )
    
    if not smtp_server or not smtp_username or not smtp_password:
        print("[SMTP ERROR] SMTP settings not configured. Please set SMTP_SERVER, SMTP_USERNAME, and SMTP_PASSWORD in .env file.", flush=True)
        return False
        
    try:
        msg = MIMEText(body)
        msg['Subject'] = 'Verify your Learnmate AI account'
        msg['From'] = smtp_username
        msg['To'] = email
        
        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_server, port)
            server.login(smtp_username, smtp_password)
        else:
            server = smtplib.SMTP(smtp_server, port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            
        server.sendmail(smtp_username, [email], msg.as_string())
        server.quit()
        print(f"[SMTP SUCCESS] Email sent successfully to {email}", flush=True)
        return True
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send email to {email}: {e}", flush=True)
        return False

def send_sms_otp(phone, otp_code):
    if _otp_dev_mode_enabled():
        print(
            f"[SMS OTP DEV] Simulated SMS delivery to {phone}. OTP: {otp_code}",
            flush=True,
        )
        return True

    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER")
    fast2sms_api_key = os.getenv("FAST2SMS_API_KEY")
    
    if twilio_sid and twilio_token and twilio_from:
        try:
            import urllib.request
            import urllib.parse
            import base64
            
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            data = urllib.parse.urlencode({
                'From': twilio_from,
                'To': phone,
                'Body': f"Welcome to Learnmate AI! Your verification code is: {otp_code}. Expires in 5 minutes."
            }).encode('utf-8')
            
            req = urllib.request.Request(url, data=data, method='POST')
            auth_str = f"{twilio_sid}:{twilio_token}"
            auth_header = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
            req.add_header("Authorization", f"Basic {auth_header}")
            
            with urllib.request.urlopen(req) as response:
                res_code = response.getcode()
                if res_code in (200, 201):
                    print(f"[TWILIO SUCCESS] SMS sent successfully to {phone}", flush=True)
                    return True
        except Exception as e:
            print(f"[TWILIO ERROR] Failed to send SMS to {phone}: {e}", flush=True)
            
    elif fast2sms_api_key:
        try:
            import urllib.request
            import urllib.parse
            import json
            
            # Clean phone number to exactly 10 digits for Indian SMS delivery
            clean_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if clean_phone.startswith('+91'):
                clean_phone = clean_phone[3:]
            elif clean_phone.startswith('91') and len(clean_phone) > 10:
                clean_phone = clean_phone[2:]
            
            url = "https://www.fast2sms.com/dev/bulkV2"
            headers = {
                'authorization': fast2sms_api_key,
                'Content-Type': 'application/json'
            }
            payload = {
                'route': 'q',
                'message': f"Welcome to Learnmate AI! Your verification code is: {otp_code}. Expires in 5 minutes.",
                'language': 'english',
                'numbers': clean_phone
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req) as response:
                res_code = response.getcode()
                if res_code == 200:
                    print(f"[FAST2SMS SUCCESS] SMS sent successfully to {phone}", flush=True)
                    return True
        except Exception as e:
            print(f"[FAST2SMS ERROR] Failed to send SMS to {phone}: {e}", flush=True)
            
    print("[SMS ERROR] Twilio/Fast2SMS credentials not configured. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER or FAST2SMS_API_KEY in .env file.", flush=True)
    return False

@app.route('/login', methods=['POST'])
def login_route():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    if not username or not password:
        return render_template('auth.html', error="Username and password are required.", tab='login')
        
    user = database.authenticate_user(username, password)
    if user:
        if user.get('otp_verified') == 0:
            return render_template('auth.html', error="Please verify your email or phone first.", tab='login')
            
        database.ensure_user_subscription_defaults(user['id'])
        user = database.get_user_by_id(user['id'])
        session['user_id'] = user['id']
        session['username'] = user['username']
        sync_user_session(user['id'])
        return redirect(url_for('dashboard_route'))
    else:
        return render_template('auth.html', error="Invalid credentials. Please check details.", tab='login')

@app.route('/register', methods=['POST'])
def register_route():
    # Deprecated classic route - front-end now routes via `/api/start-register`
    return render_template('auth.html', error="Classic registration deprecated. Please use the styled Register form.", tab='register')

@app.route('/api/start-register', methods=['POST'])
def api_start_register():
    data = request.json or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    method = data.get('verification_method', 'email').strip().lower()
    
    if not username or not email or not phone or not password:
        return jsonify({'error': 'All fields are required.'}), 400
        
    # Uniqueness checks
    if not database.check_unique_field('username', username):
        return jsonify({'error': 'Username is already taken.'}), 400
    if not database.check_unique_field('email', email):
        return jsonify({'error': 'Email address is already registered.'}), 400
    if not database.check_unique_field('phone', phone):
        return jsonify({'error': 'Phone number is already registered.'}), 400
        
    strength_ok, strength_msg = validate_password_strength(password, username)
    if not strength_ok:
        return jsonify({'error': strength_msg}), 400
        
    otp_code = generate_otp()
    
    sent = False
    actual_method = method
    if method == 'sms':
        sent = send_sms_otp(phone, otp_code)
        if not sent:
            print("[FALLBACK] SMS delivery missed/unconfigured. Falling back to Email OTP.", flush=True)
            actual_method = 'email'
            sent = send_email_otp(email, otp_code)
    else:
        sent = send_email_otp(email, otp_code)
        
    if not sent:
        return jsonify({'error': 'Failed to deliver verification code. Please check credentials.'}), 500
        
    session['reg_temp_user'] = {
        'username': username,
        'email': email,
        'phone': phone,
        'password': password,
        'verification_method': actual_method
    }
    session['reg_otp_code'] = otp_code
    session['reg_otp_expiry'] = time.time() + 300
    session['reg_otp_attempts'] = 0
    session['reg_otp_last_sent'] = time.time()
    session['reg_otp_target'] = email if actual_method == 'email' else phone
    
    res_body = {
        'success': True,
        'message': f'Verification code sent successfully.',
        'target': session['reg_otp_target'],
        'method': actual_method
    }
    if _otp_dev_mode_enabled():
        res_body['dev_otp'] = otp_code
    return jsonify(res_body)

@app.route('/api/verify-otp', methods=['POST'])
def api_verify_otp():
    data = request.json or {}
    user_otp = data.get('otp', '').strip()
    
    if not user_otp:
        return jsonify({'error': 'Verification code is required.'}), 400
        
    temp_user = session.get('reg_temp_user')
    otp_code = session.get('reg_otp_code')
    otp_expiry = session.get('reg_otp_expiry', 0)
    attempts = session.get('reg_otp_attempts', 0)
    
    if not temp_user or not otp_code:
        return jsonify({'error': 'Registration session expired. Please start registration again.'}), 400
        
    if time.time() > otp_expiry:
        return jsonify({'error': 'Verification code has expired. Please request a new code.', 'expired': True}), 400
        
    if attempts >= 3:
        session.pop('reg_otp_code', None)
        return jsonify({'error': 'Maximum incorrect verification attempts exceeded. Please register again.'}), 400
        
    if user_otp != otp_code:
        attempts += 1
        session['reg_otp_attempts'] = attempts
        if attempts >= 3:
            session.pop('reg_otp_code', None)
            return jsonify({'error': 'Maximum incorrect attempts exceeded. Registration locked.'}), 400
        return jsonify({'error': f'Incorrect code. {3 - attempts} attempt(s) remaining.'}), 400
        
    username = temp_user['username']
    password = temp_user['password']
    email = temp_user['email']
    phone = temp_user['phone']
    method = temp_user['verification_method']
    
    email_ver = 1
    phone_ver = 1 if method == 'sms' else 0
    
    user_id = database.create_user(
        username=username,
        password=password,
        email=email,
        phone=phone,
        email_verified=email_ver,
        phone_verified=phone_ver,
        otp_verified=1
    )
    
    if not user_id:
        return jsonify({'error': 'Failed to create user. Data might have changed.'}), 500
        
    session.pop('reg_temp_user', None)
    session.pop('reg_otp_code', None)
    session.pop('reg_otp_expiry', None)
    session.pop('reg_otp_attempts', None)
    session.pop('reg_otp_target', None)
    
    log_registration_notification(username, user_id)
    
    return jsonify({'success': True, 'message': 'Account verified and created successfully! You can sign in now.'})

@app.route('/api/resend-otp', methods=['POST'])
def api_resend_otp():
    temp_user = session.get('reg_temp_user')
    last_sent = session.get('reg_otp_last_sent', 0)
    
    if not temp_user:
        return jsonify({'error': 'Registration session expired.'}), 400
        
    if time.time() - last_sent < 30:
        remaining = int(30 - (time.time() - last_sent))
        return jsonify({'error': f'Please wait {remaining} seconds before resending.'}), 400
        
    otp_code = generate_otp()
    email = temp_user['email']
    phone = temp_user['phone']
    method = temp_user['verification_method']
    
    sent = False
    actual_method = method
    if method == 'sms':
        sent = send_sms_otp(phone, otp_code)
        if not sent:
            actual_method = 'email'
            sent = send_email_otp(email, otp_code)
    else:
        sent = send_email_otp(email, otp_code)
        
    session['reg_otp_code'] = otp_code
    session['reg_otp_expiry'] = time.time() + 300
    session['reg_otp_attempts'] = 0
    session['reg_otp_last_sent'] = time.time()
    session['reg_otp_target'] = email if actual_method == 'email' else phone
    session['reg_temp_user']['verification_method'] = actual_method
    
    res_body = {
        'success': True,
        'message': f'A new verification code has been sent to your {actual_method}.',
        'target': session['reg_otp_target'],
        'method': actual_method
    }
    if _otp_dev_mode_enabled():
        res_body['dev_otp'] = otp_code
    return jsonify(res_body)

@app.route('/logout')
def logout_route():
    session.clear()
    return redirect(url_for('landing_route'))

@app.route('/pricing')
def pricing_route():
    if 'user_id' not in session:
        return redirect(url_for('auth_route'))
    user = database.get_user_by_id(session['user_id'])
    if user:
        database.ensure_user_subscription_defaults(session['user_id'])
        user = database.get_user_by_id(session['user_id'])
    return render_template('pricing.html', active_page='pricing', user=user)

@app.route('/admin')
def admin_route():
    if 'user_id' not in session:
        return redirect(url_for('auth_route'))
    search = request.args.get('search', '').strip()
    stats = database.get_admin_dashboard_stats()
    users = database.get_admin_user_rows(search)
    return render_template('admin.html', active_page='admin', stats=stats, users=users, search=search)

@app.route('/dashboard')
def dashboard_route():
    user_id = session['user_id']
    
    # Gather statistics
    plans = database.get_study_plans(user_id)
    materials = database.get_materials(user_id)
    quizzes = database.get_quiz_attempts(user_id)
    weaks = database.get_weak_areas(user_id)
    
    stats = {
        'plans_count': len(plans),
        'materials_count': len(materials),
        'quizzes_count': len(quizzes),
        'weak_areas_count': len(weaks)
    }
    
    last_quiz = quizzes[0] if quizzes else None
    
    return render_template(
        'dashboard.html', 
        active_page='dashboard', 
        stats=stats,
        recent_plans=plans,
        recent_materials=materials,
        last_quiz=last_quiz
    )

@app.route('/chat')
def chat_route():
    user_id = session['user_id']
    files = database.get_materials(user_id)
    
    # Check if we have prefilled topic redirection from weak areas
    topic_preload = request.args.get('topic', '')
    
    return render_template(
        'chat.html', 
        active_page='chat', 
        materials_count=len(files), 
        files=files,
        topic_preload=topic_preload
    )

@app.route('/study-plan')
def study_plan_route():
    user_id = session['user_id']
    user = database.get_user_by_id(user_id)
    username = user.get('username') if user else ''
    
    saved_plans = database.get_study_plans(user_id)
    used_attempts = len(saved_plans)
    
    is_admin = (username == 'tanishka253')
    is_subscribed = (user.get('plan') or 'free').lower() in ('monthly', 'yearly') if user else False
    
    if is_admin or is_subscribed:
        show_pricing = False
        show_pricing_hint = False
        free_attempts_remaining = -1
    else:
        if used_attempts >= 2:
            show_pricing = True
            show_pricing_hint = True
            free_attempts_remaining = 0
        else:
            show_pricing = False
            show_pricing_hint = False
            free_attempts_remaining = max(0, 2 - used_attempts)
        
    # Handle viewing a specific plan
    view_id = request.args.get('view', type=int)
    active_plan = None
    if view_id:
        plan_row = database.get_study_plan_by_id(view_id, user_id)
        if plan_row:
            active_plan = json.loads(plan_row['plan_data'])
            # Add plan metadata for the view
            active_plan['id'] = plan_row['id']
            active_plan['subject'] = plan_row['subject']
            active_plan['goal'] = plan_row['goal']
            active_plan['deadline'] = plan_row['deadline']
            active_plan['hours_per_day'] = plan_row['hours_per_day']
    elif saved_plans:
        # Default view the most recent plan
        plan_row = saved_plans[0]
        active_plan = json.loads(plan_row['plan_data'])
        active_plan['id'] = plan_row['id']
        active_plan['subject'] = plan_row['subject']
        active_plan['goal'] = plan_row['goal']
        active_plan['deadline'] = plan_row['deadline']
        active_plan['hours_per_day'] = plan_row['hours_per_day']
        view_id = plan_row['id']
        
    return render_template(
        'study_plan.html', 
        active_page='study_plan', 
        saved_plans=saved_plans, 
        active_plan=active_plan,
        view_id=view_id,
        show_pricing=show_pricing,
        show_pricing_hint=show_pricing_hint,
        attempt_count=used_attempts,
        free_attempts_remaining=free_attempts_remaining
    )

@app.route('/upload')
def upload_route():
    user_id = session['user_id']
    uploaded_materials = database.get_materials(user_id)
    return render_template(
        'upload.html', 
        active_page='upload', 
        uploaded_materials=uploaded_materials
    )

@app.route('/quiz')
def quiz_route():
    user_id = session['user_id']
    user = database.get_user_by_id(user_id)
    username = user.get('username') if user else ''
    
    files = database.get_materials(user_id)
    attempts = database.get_quiz_attempts(user_id)
    used_attempts = len(attempts)
    
    is_admin = (username == 'tanishka253')
    is_subscribed = (user.get('plan') or 'free').lower() in ('monthly', 'yearly') if user else False
    
    if is_admin or is_subscribed:
        show_pricing = False
        show_pricing_hint = False
        free_attempts_remaining = -1
    else:
        if used_attempts >= 2:
            show_pricing = True
            show_pricing_hint = True
            free_attempts_remaining = 0
        else:
            show_pricing = False
            show_pricing_hint = False
            free_attempts_remaining = max(0, 2 - used_attempts)
        
    session['attempts_left'] = free_attempts_remaining
    return render_template(
        'quiz.html', 
        active_page='quiz', 
        files=files,
        show_pricing=show_pricing,
        show_pricing_hint=show_pricing_hint,
        attempt_count=used_attempts,
        free_attempts_remaining=free_attempts_remaining
    )

@app.route('/weak-areas')
def weak_areas_route():
    user_id = session['user_id']
    weaks = database.get_weak_areas(user_id)
    
    # Calculate counters
    critical = sum(1 for w in weaks if w['score_percentage'] < 50)
    warning = sum(1 for w in weaks if 50 <= w['score_percentage'] < 75)
    
    # To find healthy, query all unique quiz topics whose moving score is >= 75
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM weak_areas WHERE user_id = ? AND score_percentage >= 75", (user_id,))
    healthy = cursor.fetchone()[0]
    conn.close()
    
    # Deserializing recommendation strings to lists
    parsed_weaks = []
    for w in weaks:
        w_dict = dict(w)
        try:
            w_dict['recommendations'] = json.loads(w['recommendations'])
        except Exception:
            w_dict['recommendations'] = [w['recommendations']]
        parsed_weaks.append(w_dict)

    return render_template(
        'weak_areas.html', 
        active_page='weak_areas', 
        weak_areas=parsed_weaks,
        critical_count=critical,
        warning_count=warning,
        healthy_count=healthy
    )

@app.route('/progress')
def progress_route():
    user_id = session['user_id']
    attempts = database.get_quiz_attempts(user_id)
    materials = database.get_materials(user_id)
    
    # Basic math cards
    total_attempts = len(attempts)
    total_files = len(materials)
    avg_score = 0
    if total_attempts > 0:
        avg_score = sum((att['score'] / att['total_questions']) * 100 for att in attempts) / total_attempts

    return render_template(
        'progress.html', 
        active_page='progress',
        attempts=attempts,
        total_attempts=total_attempts,
        total_files=total_files,
        avg_score=avg_score
    )

# --- BACKEND API ENDPOINTS ---

@app.route('/api/upload', methods=['POST'])
def api_upload():
    user_id = session['user_id']
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file element in request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    # Check extension
    filename = file.filename
    _, ext = os.path.splitext(filename.lower())
    if ext not in ['.pdf', '.txt']:
        return jsonify({'error': 'Only PDF and TXT documents are supported.'}), 400

    # Save to uploads folder with unique prefix
    safe_filename = f"{user_id}_{int(datetime.now().timestamp())}_{filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    file.save(file_path)
    file_size = os.path.getsize(file_path)

    # Index using RAG service
    try:
        chunks_indexed = rag_service.index_file(user_id, file_path, filename)
        if chunks_indexed == 0:
            # File was empty or unparseable
            os.remove(file_path)
            return jsonify({'error': 'Failed to extract text from file or document was empty.'}), 400
            
        # Add entry to database
        database.add_material(user_id, filename, file_path, file_size, chunks_indexed)
        return jsonify({
            'success': True,
            'filename': filename,
            'chunks_indexed': chunks_indexed
        })
    except Exception as e:
        print(f"Processing upload error: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': f'Failed to index file chunks: {str(e)}'}), 500

@app.route('/api/delete-material/<int:material_id>', methods=['DELETE'])
def api_delete_material(material_id):
    user_id = session['user_id']
    
    # Retrieve filename to delete from vector index first
    conn = database.get_db()
    row = conn.execute("SELECT filename FROM uploaded_materials WHERE id = ? AND user_id = ?", (material_id, user_id)).fetchone()
    conn.close()
    
    if not row:
        return jsonify({'error': 'File not found or unauthorized.'}), 404
        
    filename = row['filename']
    
    # Delete from database (handles disk cleanup in helper)
    database.delete_material(material_id, user_id)
    # Rebuild vector store omitting this file
    rag_service.delete_file_from_vector_store(user_id, filename)
    
    return jsonify({'success': True, 'message': f'Material {filename} removed successfully.'})

@app.route('/api/delete-study-plan/<int:plan_id>', methods=['DELETE'])
def api_delete_study_plan(plan_id):
    user_id = session['user_id']
    database.delete_study_plan(plan_id, user_id)
    return jsonify({'success': True, 'message': 'Study plan removed successfully.'})

def require_subscription_access():
    user_id = session.get('user_id')
    if not user_id:
        return None, (jsonify({'error': 'Authentication required.'}), 401)

    database.ensure_user_subscription_defaults(user_id)
    user = database.get_user_by_id(user_id)
    if not user:
        return None, (jsonify({'error': 'Account not found.'}), 404)

    plan = (user.get('plan') or 'free').lower()
    if plan in ('monthly', 'yearly'):
        return user, None

    allowed, result = database.consume_ai_attempt(user_id)
    if allowed:
        return user, None
    return None, (jsonify({'error': 'Your free AI tutor limit has been reached. Upgrade to continue.', 'redirect': '/pricing'}), 403)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    user_id = session['user_id']
    data = request.json or {}
    message = data.get('message', '').strip()
    use_rag = data.get('use_rag', False)
    history = data.get('history', [])

    if not message:
        return jsonify({'error': 'Message content is empty'}), 400

    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'Account not found.'}), 404

    if not api_key:
        return jsonify({'reply': 'Mock Mode Response: Please configure your GEMINI_API_KEY in the `.env` configuration file to activate live tutoring.', 'sources': []})

    retrieved_text = ""
    sources = []
    
    # If using RAG, query the index chunks
    if use_rag:
        try:
            results = rag_service.query_user_vector_store(user_id, message, k=4)
            if results:
                chunks = []
                for res in results:
                    chunks.append(res['chunk']['text'])
                    sources.append(res['chunk']['filename'])
                retrieved_text = "\n\n---\n\n".join(chunks)
        except Exception as e:
            print(f"RAG Retrieval failed: {e}")

    # Build Prompt
    system_prompt = (
        "You are 'Academic Coach', an adaptive, empathetic, and expert AI tutor. "
        "Your mission is to help the student understand complex terms, step-by-step concepts, and academic topics. "
        "Tailor your response to be simple but comprehensive. Utilize formatting (bolding, lists) to keep it readable.\n"
    )
    
    if retrieved_text:
        system_prompt += (
            f"You MUST prioritize answering the student's question using the following source notes retrieved from their uploaded textbooks:\n"
            f"{retrieved_text}\n\n"
            f"Make sure to reference facts accurately. If the document content doesn't fully cover the query, answer with best academic practices but indicate what was missing in the uploaded notes.\n"
        )
    else:
        system_prompt += "Explain the topic using general academic knowledge.\n"

    try:
        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=system_prompt)
        
        # Format chat history for Gemini client (Gemini uses structure [{'role': 'user', 'parts': [...]}, {'role': 'model', 'parts': [...]}]
        formatted_history = []
        for h in history[-8:]: # limit history context depth
            role = 'user' if h['role'] == 'user' else 'model'
            formatted_history.append({
                'role': role,
                'parts': [h['content']]
            })
            
        chat = model.start_chat(history=formatted_history)
        response = chat.send_message(message)
        
        return jsonify({
            'reply': response.text,
            'sources': sources
        })
    except Exception as e:
        print(f"Gemini chat completion error: {e}")
        return jsonify({'error': f'Failed to compile response: {str(e)}'}), 500

@app.route('/api/generate-plan', methods=['POST'])
def api_generate_plan():
    user_id = session['user_id']
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'Account not found.'}), 404

    username = user.get('username')
    is_admin = (username == 'tanishka253')
    is_subscribed = (user.get('plan') or 'free').lower() in ('monthly', 'yearly')

    if not is_admin and not is_subscribed:
        saved_plans = database.get_study_plans(user_id)
        if len(saved_plans) >= 2:
            return jsonify({'error': 'Your free study plan attempts are used up. Upgrade to continue.'}), 403

    data = request.json or {}
    subject = data.get('subject', '').strip()
    goal = data.get('goal', '').strip()
    deadline = data.get('deadline', '')
    hours_per_day = data.get('hours_per_day', 2)

    if not subject or not goal or not deadline:
        return jsonify({'error': 'All fields are required.'}), 400

    if not api_key:
        # Return mock JSON plan
        mock_plan = {
            "subject": subject,
            "goal": goal,
            "deadline": deadline,
            "hours_per_day": hours_per_day,
            "weekly_milestones": [
                {"week": 1, "focus": "Fundamentals", "objective": "Understand terminology", "tasks": ["Read Chapter 1", "Self-test basics"]}
            ],
            "daily_schedule": [
                {"day": "Monday", "topics": "Definitions & Core Logic", "strategy": "Active recall", "hours": hours_per_day}
            ],
            "coach_advice": "Configure a live GEMINI_API_KEY to receive custom calendars."
        }
        database.create_study_plan(user_id, subject, goal, deadline, hours_per_day, mock_plan)
        return jsonify({'plan': mock_plan})

    prompt = (
        f"Create a comprehensive, structured study plan. "
        f"Subject: '{subject}', Goal: '{goal}', Deadline: '{deadline}', Study Hours Available: {hours_per_day} hours/day. "
        "Return strictly valid JSON with the following structure. Do NOT wrap it in any HTML tags. "
        "JSON Schema:\n"
        "{\n"
        "  \"subject\": \"Subject name\",\n"
        "  \"goal\": \"Study goal\",\n"
        "  \"deadline\": \"Deadline\",\n"
        "  \"hours_per_day\": 2,\n"
        "  \"weekly_milestones\": [\n"
        "     { \"week\": 1, \"focus\": \"Focus Area\", \"objective\": \"Objective summary\", \"tasks\": [\"Task 1\", \"Task 2\"] }\n"
        "  ],\n"
        "  \"daily_schedule\": [\n"
        "     { \"day\": \"Monday\", \"topics\": \"Specific concept list\", \"strategy\": \"e.g. Feynman technique\", \"hours\": 2 }\n"
        "  ],\n"
        "  \"coach_advice\": \"Personal advice on learning strategies\"\n"
        "}"
    )

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        parsed_plan = clean_and_parse_json(response.text)
        if not parsed_plan:
            return jsonify({'error': 'AI generated invalid structure. Try again.'}), 500
            
        # Store in database
        database.create_study_plan(user_id, subject, goal, deadline, hours_per_day, parsed_plan)
        
        return jsonify({'plan': parsed_plan})
    except Exception as e:
        print(f"Generate plan error: {e}")
        return jsonify({'error': f'Failed to formulate plan: {str(e)}'}), 500

@app.route('/api/generate-quiz', methods=['POST'])
def api_generate_quiz():
    user_id = session['user_id']
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'Account not found.'}), 404

    username = user.get('username')
    is_admin = (username == 'tanishka253')
    is_subscribed = (user.get('plan') or 'free').lower() in ('monthly', 'yearly')

    if not is_admin and not is_subscribed:
        attempts = database.get_quiz_attempts(user_id)
        if len(attempts) >= FREE_QUIZ_ATTEMPTS:
            return jsonify({'error': 'Your free quiz attempts are used up. Upgrade to continue.'}), 403

    data = request.json or {}
    topic = data.get('topic', '').strip()
    material_id = data.get('material_id', '')
    num_questions = data.get('num_questions', 5)
    difficulty = data.get('difficulty', 'intermediate')

    if not topic and not material_id:
        return jsonify({'error': 'Topic or reference file selection required.'}), 400

    context_content = ""
    source_title = topic or "Study Notes Quiz"
    
    # Retrieve notes context if using a reference file
    if material_id:
        conn = database.get_db()
        row = conn.execute("SELECT filename, file_path FROM uploaded_materials WHERE id = ? AND user_id = ?", (material_id, user_id)).fetchone()
        conn.close()
        
        if row:
            source_title = f"Quiz: {row['filename']}"
            file_path = row['file_path']
            # Read snippet (first 12000 chars) for prompt framing
            try:
                if file_path.endswith('.pdf'):
                    context_content = rag_service.extract_text_from_pdf(file_path)[:12000]
                else:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        context_content = f.read()[:12000]
            except Exception as e:
                print(f"Error reading file context: {e}")

    if not api_key:
        # Mock quiz generator
        mock_quiz = {
            "title": source_title,
            "questions": [
                {
                    "question": f"Self-evaluate standard terminology on {topic or 'your notes'}. (Mock Q1)?",
                    "type": "mcq",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_answer": "Option A",
                    "explanation": "Register a valid GEMINI_API_KEY in configuration env files to compile real topic test items."
                },
                {
                    "question": "Is the sky blue? (Mock True/False Q2)",
                    "type": "tf",
                    "correct_answer": "True",
                    "explanation": "Atmospheric scattering makes it blue."
                }
            ]
        }
        return jsonify(mock_quiz)

    prompt = (
        f"Generate a customized practice quiz. Title: '{source_title}'. Difficulty: {difficulty}. Quantity: {num_questions} questions.\n"
    )
    if context_content:
        prompt += f"Construct the questions directly from this syllabus source notes text:\n--- START CONTEXT ---\n{context_content}\n--- END CONTEXT ---\n"
    else:
        prompt += f"Construct questions covering general knowledge of topic: '{topic}'.\n"

    prompt += (
        "Ensure questions contain a mix of MCQ ('mcq'), True/False ('tf'), and Short Answer ('sa') types. "
        "Return strictly valid JSON with this layout:\n"
        "{\n"
        "  \"title\": \"Quiz Title\",\n"
        "  \"questions\": [\n"
        "     { \"question\": \"Question string\", \"type\": \"mcq\", \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"], \"correct_answer\": \"Option A\", \"explanation\": \"Details...\" },\n"
        "     { \"question\": \"Question string\", \"type\": \"tf\", \"correct_answer\": \"True\", \"explanation\": \"Details...\" },\n"
        "     { \"question\": \"Question string\", \"type\": \"sa\", \"correct_answer\": \"Core keyword concepts expected in reply\", \"explanation\": \"Details...\" }\n"
        "  ]\n"
        "}"
    )

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        parsed_quiz = clean_and_parse_json(response.text)
        if not parsed_quiz or 'questions' not in parsed_quiz:
            return jsonify({'error': 'AI returned invalid quiz JSON. Re-submit.'}), 500
            
        return jsonify(parsed_quiz)
    except Exception as e:
        print(f"Generate quiz error: {e}")
        return jsonify({'error': f'Failed to formulate quiz: {str(e)}'}), 500

@app.route('/api/submit-quiz', methods=['POST'])
def api_submit_quiz():
    user_id = session['user_id']
    data = request.json or {}
    title = data.get('title', 'Practice Quiz')
    questions = data.get('questions', [])
    answers = data.get('answers', [])

    if len(questions) != len(answers):
        return jsonify({'error': 'Questions and answers mismatch size'}), 400

    evaluation_report = []
    total_score = 0
    total_questions = len(questions)

    # We evaluate answers. For SA (Short Answer), we use Gemini to grade correctness.
    for i, q in enumerate(questions):
        user_ans = answers[i].strip()
        correct_ans = q.get('correct_answer', '')
        q_type = q.get('type', 'mcq')
        
        is_correct = False
        grade_explanation = q.get('explanation', '')
        
        if q_type in ['mcq', 'tf']:
            # Normal lowercase matching
            is_correct = user_ans.lower() == correct_ans.lower()
            if is_correct:
                total_score += 1
        else:
            # Short answer - Evaluate using Gemini semantic matching
            if not user_ans:
                is_correct = False
                grade_explanation = "No response was written."
            elif not api_key:
                # Mock grading
                is_correct = "keyword" in user_ans.lower() or len(user_ans) > 10
                if is_correct:
                    total_score += 1
                grade_explanation = "Mock Grade: Configure Gemini API for semantic evaluation."
            else:
                eval_prompt = (
                    f"Evaluate the correctness of the student answer to this question.\n"
                    f"Question: {q.get('question')}\n"
                    f"Expected Core Concepts: {correct_ans}\n"
                    f"Student Response: {user_ans}\n\n"
                    f"Return strictly valid JSON with this exact layout (do not add notes/formatting):\n"
                    f"{{\"score\": 1, \"explanation\": \"Provide step-by-step feedback explaining correctness or what is missing.\"}}"
                    f"(Use score 1 if factually correct and covers major keywords, else 0)"
                )
                try:
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    res = model.generate_content(eval_prompt)
                    res_json = clean_and_parse_json(res.text)
                    
                    score = int(res_json.get('score', 0))
                    grade_explanation = res_json.get('explanation', 'Graded by AI.')
                    is_correct = score == 1
                    if is_correct:
                        total_score += 1
                except Exception as e:
                    print(f"Eval SA error: {e}")
                    is_correct = False
                    grade_explanation = f"Failed to grade answer dynamically. Model expected: {correct_ans}"

        evaluation_report.append({
            'question': q.get('question'),
            'type': q_type,
            'user_answer': user_ans,
            'correct_answer': correct_ans,
            'is_correct': is_correct,
            'explanation': grade_explanation
        })

    # Record the quiz attempt in database
    database.add_quiz_attempt(user_id, title, total_score, total_questions, questions, evaluation_report)

    # Process and diagnose weak areas (Only for incorrect answers)
    incorrect_questions = [item for item in evaluation_report if not item['is_correct']]
    if incorrect_questions and api_key:
        # Prompt Gemini to cluster incorrect topics and recommend improvements
        diagnose_prompt = (
            f"Analyze these incorrect quiz questions for a student and group them by focus topic.\n"
            f"Incorrect Questions:\n"
            + "\n".join([f"- Q: {item['question']} | Expected: {item['correct_answer']}" for item in incorrect_questions])
            + "\n\nReturn strictly valid JSON with this layout:\n"
            "[\n"
            "  {\n"
            "    \"topic\": \"Topic Name (e.g. Newton's Third Law, Photosynthesis Phase 1)\",\n"
            "    \"recommendations\": [\n"
            "       \"Read textbook Chapter X on topic detail.\",\n"
            "       \"Ask AI tutor to explain core equations step-by-step.\"\n"
            "    ]\n"
            "  }\n"
            "]"
        )
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            res = model.generate_content(diagnose_prompt)
            weaks_detected = clean_and_parse_json(res.text)
            
            if weaks_detected and isinstance(weaks_detected, list):
                for item in weaks_detected:
                    topic = item.get('topic', 'General Revision')
                    recs = item.get('recommendations', ['Review correct answers and tutorials.'])
                    # For wrong topics, assign a baseline percentage (e.g. 40%) to log as weak (<75%)
                    database.update_weak_area(user_id, topic, 40.0, recs)
        except Exception as e:
            print(f"Diagnostics logging error: {e}")

    # Fallback diagnostics if no key
    elif incorrect_questions:
        database.update_weak_area(user_id, "General Course Topics", 50.0, ["Review incorrect responses in history logs.", "Try studying files in tutor chat."])

    return jsonify({
        'score': total_score,
        'total_questions': total_questions,
        'evaluation': evaluation_report
    })

@app.route('/api/progress-data')
def api_progress_data():
    user_id = session['user_id']
    attempts = database.get_quiz_attempts(user_id)
    weaks = database.get_weak_areas(user_id)

    # 1. Timeline history log: limit to last 7 attempts in chronological order
    quiz_history = []
    for att in reversed(attempts[:7]):
        # Format date for labels
        date_str = att['created_at']
        try:
            dt = datetime.strptime(att['created_at'], "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%b %d")
        except Exception:
            pass
        pct = (att['score'] / att['total_questions']) * 100
        quiz_history.append({
            'date': date_str,
            'percentage': pct
        })

    # 2. Topic performance bar data
    topic_scores = []
    # Query all records from weak_areas to see performance
    conn = database.get_db()
    rows = conn.execute("SELECT topic, score_percentage FROM weak_areas WHERE user_id = ? LIMIT 6", (user_id,)).fetchall()
    conn.close()
    for row in rows:
        topic_scores.append({
            'topic': row['topic'],
            'score': row['score_percentage']
        })

    # Provide fallback if empty to draw pretty charts
    if not quiz_history:
        quiz_history = [{'date': 'No Data', 'percentage': 0}]
    if not topic_scores:
        topic_scores = [{'topic': 'General Practice', 'score': 70}]

    return jsonify({
        'quiz_history': quiz_history,
        'topic_scores': topic_scores
    })

@app.route('/api/create-order', methods=['POST'])
def api_create_order():
    user_id = session['user_id']
    data = request.json or {}
    plan = data.get('plan', '').strip().lower()
    if plan not in ('monthly', 'yearly'):
        return jsonify({'error': 'Invalid plan selected.'}), 400

    amount = 29900 if plan == 'monthly' else 320000
    order_id = f"order_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    payload = {
        'amount': amount,
        'currency': 'INR',
        'receipt': order_id,
        'notes': {'user_id': str(user_id), 'plan': plan},
    }
    database.activate_subscription(user_id, plan, 'pending', order_id=order_id, days=30 if plan == 'monthly' else 365)
    return jsonify({'order_id': order_id, 'amount': amount, 'currency': 'INR', 'plan': plan})

@app.route('/api/verify-payment', methods=['POST'])
def api_verify_payment():
    user_id = session['user_id']
    data = request.json or {}
    payment_id = data.get('razorpay_payment_id', '')
    order_id = data.get('razorpay_order_id', '')
    signature = data.get('razorpay_signature', '')
    plan = data.get('plan', '').strip().lower()
    if not payment_id or not order_id or not signature or plan not in ('monthly', 'yearly'):
        return jsonify({'error': 'Missing payment verification data.'}), 400

    generated_signature = hmac.new(
        os.getenv('RAZORPAY_KEY_SECRET', 'test_secret').encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256
    ).hexdigest()
    if hmac.compare_digest(generated_signature, signature):
        database.activate_subscription(user_id, plan, 'paid', payment_id=payment_id, order_id=order_id, days=30 if plan == 'monthly' else 365)
        return jsonify({'success': True, 'message': 'Subscription activated.'})
    return jsonify({'error': 'Payment verification failed.'}), 400

# Main Server Bootstrapper
if __name__ == "__main__":
    database.init_db()
    # Run locally on default port
    app.run(host="127.0.0.1", port=5000, debug=True)
