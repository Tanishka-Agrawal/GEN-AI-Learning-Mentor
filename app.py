import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

import database
import rag_service

# Load env configurations
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
# Secure secret key loading
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_mentor_sec_key_2026")
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Import google-generativeai client
import google.generativeai as genai
api_key = os.getenv("GEMINI_API_KEY")
if api_key and not api_key.startswith("your_") and api_key.strip():
    genai.configure(api_key=api_key)
else:
    api_key = None

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

# Middleware to require login
@app.before_request
def require_login():
    # Endpoints that are accessible without login
    allowed_routes = ['landing_route', 'auth_route', 'login_route', 'register_route', 'static']
    if request.endpoint in allowed_routes or request.path.startswith('/static') or request.path == '/favicon.ico':
        return
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required.'}), 401
        return redirect(url_for('auth_route'))

# --- WEB PAGE ROUTING ---

@app.route('/')
def landing_route():
    if 'user_id' in session:
        return redirect(url_for('dashboard_route'))
    return render_template('landing.html')

@app.route('/auth')
def auth_route():
    if 'user_id' in session:
        return redirect(url_for('dashboard_route'))
    tab = request.args.get('tab', 'login')
    return render_template('auth.html', tab=tab)

@app.route('/login', methods=['POST'])
def login_route():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    if not username or not password:
        return render_template('auth.html', error="Username and password are required.", tab='login')
        
    user = database.authenticate_user(username, password)
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        return redirect(url_for('dashboard_route'))
    else:
        return render_template('auth.html', error="Invalid credentials. Please check details.", tab='login')

@app.route('/register', methods=['POST'])
def register_route():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    if not username or not password:
        return render_template('auth.html', error="All fields are required.", tab='register')
        
    if len(password) < 6:
        return render_template('auth.html', error="Password must be at least 6 characters.", tab='register')
        
    if password != confirm_password:
        return render_template('auth.html', error="Passwords do not match.", tab='register')
        
    user_id = database.create_user(username, password)
    if user_id:
        return render_template('auth.html', msg="Registration successful! You can login now.", tab='login')
    else:
        return render_template('auth.html', error="Username already exists. Choose another.", tab='register')

@app.route('/logout')
def logout_route():
    session.clear()
    return redirect(url_for('landing_route'))

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
    saved_plans = database.get_study_plans(user_id)
    
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
        view_id=view_id
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
    files = database.get_materials(user_id)
    return render_template(
        'quiz.html', 
        active_page='quiz', 
        files=files
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

@app.route('/api/chat', methods=['POST'])
def api_chat():
    user_id = session['user_id']
    data = request.json or {}
    message = data.get('message', '').strip()
    use_rag = data.get('use_rag', False)
    history = data.get('history', [])

    if not message:
        return jsonify({'error': 'Message content is empty'}), 400

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

# Main Server Bootstrapper
if __name__ == "__main__":
    database.init_db()
    # Run locally on default port
    app.run(host="127.0.0.1", port=5000, debug=True)
