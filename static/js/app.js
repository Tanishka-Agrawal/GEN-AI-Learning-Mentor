// GenAI Learning Mentor - Core Frontend Logic

document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Theme (Dark Mode Default)
    initTheme();

    // 2. Refresh Lucide Icons (if Lucide script is loaded in base.html)
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});

// Theme Management
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeToggleBtn(savedTheme);

    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeToggleBtn(newTheme);
        });
    }
}

function updateThemeToggleBtn(theme) {
    const iconSpan = document.getElementById('theme-toggle-icon');
    const textSpan = document.getElementById('theme-toggle-text');
    if (iconSpan && textSpan) {
        if (theme === 'light') {
            iconSpan.innerHTML = '<i data-lucide="moon"></i>';
            textSpan.textContent = 'Dark Mode';
        } else {
            iconSpan.innerHTML = '<i data-lucide="sun"></i>';
            textSpan.textContent = 'Light Mode';
        }
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

// Toast Notification Helper
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fade-in glass-card`;
    toast.style.position = 'fixed';
    toast.style.bottom = '2rem';
    toast.style.right = '2rem';
    toast.style.zIndex = '1000';
    toast.style.display = 'flex';
    toast.style.alignItems = 'center';
    toast.style.gap = '0.75rem';
    toast.style.padding = '1rem 1.5rem';
    
    let color = 'var(--success)';
    let icon = 'check-circle';
    if (type === 'error') {
        color = 'var(--danger)';
        icon = 'alert-triangle';
    } else if (type === 'info') {
        color = 'var(--secondary)';
        icon = 'info';
    }
    
    toast.style.borderLeft = `4px solid ${color}`;
    toast.innerHTML = `
        <span style="color: ${color}"><i data-lucide="${icon}"></i></span>
        <span style="font-size: 0.9rem; font-weight: 500;">${message}</span>
    `;
    
    document.body.appendChild(toast);
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Notes Upload Handlers
function setupUploadPage() {
    const dropzone = document.getElementById('upload-dropzone');
    const fileInput = document.getElementById('file-input');
    const fileListContainer = document.getElementById('file-list-container');

    if (!dropzone || !fileInput) return;

    // Trigger click on input
    dropzone.addEventListener('click', () => fileInput.click());

    // Drag-over styling
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFileUpload(fileInput.files[0]);
        }
    });

    // Delete handler delegator
    if (fileListContainer) {
        fileListContainer.addEventListener('click', async (e) => {
            const deleteBtn = e.target.closest('.delete-file-btn');
            if (deleteBtn) {
                const materialId = deleteBtn.getAttribute('data-id');
                const filename = deleteBtn.getAttribute('data-name');
                if (confirm(`Are you sure you want to delete ${filename}? This removes it from the AI Tutor context.`)) {
                    try {
                        const response = await fetch(`/api/delete-material/${materialId}`, { method: 'DELETE' });
                        const data = await response.json();
                        if (response.ok) {
                            showToast(data.message || 'File deleted');
                            // Reload index list
                            window.location.reload();
                        } else {
                            showToast(data.error || 'Failed to delete file', 'error');
                        }
                    } catch (err) {
                        console.error(err);
                        showToast('Error connection to server', 'error');
                    }
                }
            }
        });
    }
}

async function handleFileUpload(file) {
    const allowedExtensions = ['.pdf', '.txt'];
    const fileExt = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!allowedExtensions.includes(fileExt)) {
        showToast('Only .pdf and .txt files are supported currently.', 'error');
        return;
    }

    if (file.size > 15 * 1024 * 1024) { // 15MB limit
        showToast('Maximum file size is 15MB.', 'error');
        return;
    }

    showToast(`Uploading and indexing "${file.name}"... This might take a moment.`, 'info');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        });

        if (response.redirected || response.status === 302 || response.status === 401) {
            showToast('Session expired or login required. Redirecting to login...', 'error');
            setTimeout(() => window.location.href = '/auth', 1200);
            return;
        }

        const contentType = response.headers.get('content-type') || '';
        let data = null;
        if (contentType.includes('application/json')) {
            data = await response.json();
        } else {
            const text = await response.text();
            throw new Error(text || 'Unexpected server response.');
        }

        if (response.ok) {
            showToast(`Success! Chunks indexed: ${data.chunks_indexed}`);
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.error || 'File upload failed.', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast(err.message || 'Error uploading file.', 'error');
    }
}

// AI Tutor Chat Handlers
let chatHistory = [];
function setupChatPage() {
    const chatHistoryBox = document.getElementById('chat-history-box');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-chat-btn');
    const ragToggle = document.getElementById('use-rag-context');

    if (!chatHistoryBox || !chatInput || !sendBtn) return;

    const sendMessage = async () => {
        const text = chatInput.value.trim();
        if (!text) return;

        // Append User Bubble
        appendChatBubble('user', text);
        chatInput.value = '';
        chatInput.style.height = 'auto'; // Reset text-area height
        
        // Append AI Thinking Bubble
        const thinkingId = appendChatBubble('ai', '<span class="tutor-indicator"></span> AI Coach is synthesizing...', true);
        chatHistoryBox.scrollTop = chatHistoryBox.scrollHeight;

        const useRag = ragToggle ? ragToggle.checked : false;

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, use_rag: useRag, history: chatHistory })
            });
            const data = await response.json();

            // Remove thinking bubble
            document.getElementById(thinkingId).remove();

            if (response.ok) {
                // Save context history
                chatHistory.push({ role: 'user', content: text });
                chatHistory.push({ role: 'model', content: data.reply });
                
                // Keep history size reasonable
                if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);

                // Append AI Response
                appendChatBubble('ai', data.reply, false, data.sources);
            } else {
                appendChatBubble('ai', `<span style="color:var(--danger)">Error: ${data.error || 'AI Tutor encountered an error.'}</span>`);
            }
        } catch (err) {
            console.error(err);
            document.getElementById(thinkingId).remove();
            appendChatBubble('ai', '<span style="color:var(--danger)">Network error connecting to Gemini API.</span>');
        }
        chatHistoryBox.scrollTop = chatHistoryBox.scrollHeight;
    };

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
}

function appendChatBubble(role, content, isHtml = false, sources = []) {
    const box = document.getElementById('chat-history-box');
    const bubble = document.createElement('div');
    const id = 'bubble_' + Math.random().toString(36).substr(2, 9);
    bubble.id = id;
    bubble.className = `chat-bubble ${role}`;

    // Format content: Simple markdown-to-html conversion for clean list items and bold text
    let formattedText = content;
    if (!isHtml) {
        // Basic Markdown parser for code snippets, lists, and bold text
        formattedText = content
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code style="background:rgba(0,0,0,0.2);padding:2px 4px;border-radius:4px;font-family:monospace;">$1</code>')
            .replace(/```(.*?)\n(.*?)```/gs, '<pre style="background:rgba(0,0,0,0.3);padding:10px;border-radius:8px;font-family:monospace;overflow-x:auto;margin:8px 0;">$2</pre>');
    }

    bubble.innerHTML = formattedText;

    // If RAG sources are returned
    if (sources && sources.length > 0) {
        const sourceRow = document.createElement('div');
        sourceRow.className = 'source-badges';
        sourceRow.innerHTML = `<strong>Retrieved Context Source:</strong> `;
        const uniqueSources = [...new Set(sources)];
        uniqueSources.forEach(src => {
            const badge = document.createElement('span');
            badge.className = 'source-badge';
            badge.innerHTML = `<i data-lucide="file-text" style="width:12px;height:12px;"></i> ${src}`;
            sourceRow.appendChild(badge);
        });
        bubble.appendChild(sourceRow);
    }

    box.appendChild(bubble);
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    box.scrollTop = box.scrollHeight;
    return id;
}

// Study Plan Generator Handlers
function setupStudyPlanPage() {
    const form = document.getElementById('study-plan-form');
    const outputContainer = document.getElementById('study-plan-output-container');
    const calendarView = document.getElementById('study-plan-calendar');

    if (!form || !outputContainer) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const subject = document.getElementById('subject-input').value.trim();
        const goal = document.getElementById('goal-input').value.trim();
        const deadline = document.getElementById('deadline-input').value;
        const hours = document.getElementById('hours-input').value;

        if (!subject || !goal || !deadline || !hours) {
            showToast('All form fields are required.', 'error');
            return;
        }

        outputContainer.style.display = 'block';
        calendarView.innerHTML = `
            <div style="text-align:center; padding: 3rem 0;">
                <span class="tutor-indicator" style="animation: pulseGlow 1.5s infinite"></span>
                <p style="margin-top: 1rem; color: var(--text-secondary)">Generating personalized study milestones and weekly schedules with AI...</p>
            </div>
        `;
        
        // Scroll to output
        outputContainer.scrollIntoView({ behavior: 'smooth' });

        try {
            const response = await fetch('/api/generate-plan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ subject, goal, deadline, hours_per_day: parseInt(hours) })
            });
            const data = await response.json();

            if (response.ok) {
                showToast('Study Plan generated and saved!');
                renderStudyPlan(data.plan);
            } else {
                calendarView.innerHTML = `<div style="color:var(--danger)">Error: ${data.error || 'Failed to construct study plan.'}</div>`;
            }
        } catch (err) {
            console.error(err);
            calendarView.innerHTML = `<div style="color:var(--danger)">Network error generating plan. Check API connectivity.</div>`;
        }
    });
}

function renderStudyPlan(plan) {
    const container = document.getElementById('study-plan-calendar');
    if (!container) return;

    let html = `
        <div class="glass-card fade-in" style="margin-bottom:1.5rem; background: linear-gradient(135deg, rgba(99, 102, 241, 0.05), transparent)">
            <h3 style="color:var(--primary); font-size:1.4rem; margin-bottom:0.5rem;"><i data-lucide="award"></i> Master Study Plan: ${plan.subject}</h3>
            <p><strong>Goal:</strong> ${plan.goal}</p>
            <p><strong>Weekly Commitment:</strong> ${plan.hours_per_day} hrs/day until ${plan.deadline}</p>
        </div>
    `;

    // Weekly Milestones
    html += `<h4 style="margin: 2rem 0 1rem; font-size: 1.25rem;"><i data-lucide="compass"></i> Roadmap & Milestones</h4>`;
    html += `<div class="study-plan-container">`;
    if (plan.weekly_milestones && plan.weekly_milestones.length > 0) {
        plan.weekly_milestones.forEach((milestone, idx) => {
            html += `
                <div class="timeline-milestone fade-in" style="animation-delay: ${idx * 0.1}s">
                    <div class="milestone-title">Week ${milestone.week}: ${milestone.focus}</div>
                    <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom: 0.5rem;">Objective: ${milestone.objective}</p>
                    <ul class="milestone-tasks">
            `;
            if (milestone.tasks && milestone.tasks.length > 0) {
                milestone.tasks.forEach(task => {
                    html += `<li class="task-item"><i data-lucide="check-circle" style="width:14px; height:14px; color:var(--success)"></i> ${task}</li>`;
                });
            }
            html += `
                    </ul>
                </div>
            `;
        });
    } else {
        html += `<p>No milestones generated.</p>`;
    }
    html += `</div>`;

    // Daily Schedule Table
    html += `<h4 style="margin: 2.5rem 0 1rem; font-size: 1.25rem;"><i data-lucide="calendar"></i> Daily Timetable Layout</h4>`;
    html += `<div class="glass-card table-responsive fade-in" style="overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="border-bottom: 2px solid var(--border-color); color:var(--text-secondary)">
                    <th style="padding: 10px;">Day</th>
                    <th style="padding: 10px;">Focus Topics</th>
                    <th style="padding: 10px;">Study Strategy & Method</th>
                    <th style="padding: 10px;">Est. Hours</th>
                </tr>
            </thead>
            <tbody>
    `;
    if (plan.daily_schedule && plan.daily_schedule.length > 0) {
        plan.daily_schedule.forEach(day => {
            html += `
                <tr style="border-bottom: 1px solid var(--border-color); hover:background:var(--bg-surface-hover)">
                    <td style="padding: 12px; font-weight:600;">${day.day}</td>
                    <td style="padding: 12px;">${day.topics}</td>
                    <td style="padding: 12px;"><span class="source-badge" style="display:inline-block; background:var(--primary-glow)">${day.strategy}</span></td>
                    <td style="padding: 12px; font-weight:500;">${day.hours} hrs</td>
                </tr>
            `;
        });
    } else {
        html += `<tr><td colspan="4" style="text-align:center; padding:10px;">No daily schedule generated.</td></tr>`;
    }
    html += `
            </tbody>
        </table>
    </div>`;

    // Revision and strategy notes
    html += `
        <div class="glass-card fade-in" style="margin-top:2rem; border-left:4px solid var(--secondary); background:rgba(6, 182, 212, 0.03)">
            <h5 style="margin-bottom:0.5rem; font-size:1.1rem; color:var(--secondary)"><i data-lucide="info"></i> Intelligent Coach Advice</h5>
            <p style="font-size:0.9rem; line-height:1.5;">${plan.coach_advice || "Stay consistent! Follow the active recall techniques listed in your daily schedule to retain maximum concepts."}</p>
        </div>
    `;

    container.innerHTML = html;
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Quiz Generation and Player Logic
let activeQuizQuestions = [];
let quizTitle = "";
function setupQuizPage() {
    const generatorForm = document.getElementById('quiz-generator-form');
    const quizPlayer = document.getElementById('quiz-player-container');
    const quizWorkspace = document.getElementById('quiz-workspace');

    if (!generatorForm || !quizPlayer) return;

    generatorForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const topic = document.getElementById('quiz-topic-input').value.trim();
        const materialId = document.getElementById('quiz-material-select').value;
        const qCount = document.getElementById('quiz-count-select').value;
        const difficulty = document.getElementById('quiz-difficulty-select').value;

        if (!topic && !materialId) {
            showToast('Please enter a topic or select a course material.', 'error');
            return;
        }

        quizPlayer.style.display = 'block';
        quizWorkspace.innerHTML = `
            <div style="text-align:center; padding: 4rem 0;">
                <span class="tutor-indicator" style="animation: pulseGlow 1.5s infinite"></span>
                <p style="margin-top: 1rem; color: var(--text-secondary)">Extracting knowledge chunks and engineering questions with Gemini...</p>
            </div>
        `;
        quizPlayer.scrollIntoView({ behavior: 'smooth' });

        try {
            const response = await fetch('/api/generate-quiz', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic, material_id: materialId, num_questions: parseInt(qCount), difficulty })
            });
            const data = await response.json();

            if (response.ok) {
                showToast('Quiz compiled successfully!');
                activeQuizQuestions = data.questions;
                quizTitle = data.title;
                startQuizPlayer();
            } else {
                quizWorkspace.innerHTML = `<div style="color:var(--danger)">Error: ${data.error || 'Failed to construct quiz questions.'}</div>`;
            }
        } catch (err) {
            console.error(err);
            quizWorkspace.innerHTML = `<div style="color:var(--danger)">Network error generating quiz. Check internet connection.</div>`;
        }
    });
}

function startQuizPlayer() {
    const workspace = document.getElementById('quiz-workspace');
    if (!activeQuizQuestions || activeQuizQuestions.length === 0) {
        workspace.innerHTML = `<p>No questions generated.</p>`;
        return;
    }

    let html = `
        <div class="glass-card fade-in">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; padding-bottom:0.75rem; border-bottom:1px solid var(--border-color);">
                <h3 style="font-size:1.25rem;"><i data-lucide="check-square"></i> ${quizTitle}</h3>
                <span id="question-progress-indicator" style="font-weight:600; color:var(--primary);">Question 1 of ${activeQuizQuestions.length}</span>
            </div>
            
            <form id="active-quiz-run-form">
    `;

    activeQuizQuestions.forEach((q, idx) => {
        const isFirst = idx === 0;
        html += `
            <div class="question-container" id="question-wrapper-${idx}" style="display: ${isFirst ? 'block' : 'none'}">
                <div class="question-text">${idx + 1}. ${q.question}</div>
                <div class="options-list">
        `;

        if (q.type === 'mcq' && q.options) {
            q.options.forEach((opt, optIdx) => {
                html += `
                    <label class="option-item" for="q-${idx}-opt-${optIdx}" id="label-q-${idx}-opt-${optIdx}">
                        <input type="radio" name="q-${idx}-ans" id="q-${idx}-opt-${optIdx}" value="${opt}" style="margin-right:8px;">
                        <span>${opt}</span>
                    </label>
                `;
            });
        } else if (q.type === 'tf') {
            html += `
                <label class="option-item" for="q-${idx}-opt-t" id="label-q-${idx}-opt-t">
                    <input type="radio" name="q-${idx}-ans" id="q-${idx}-opt-t" value="True" style="margin-right:8px;">
                    <span>True</span>
                </label>
                <label class="option-item" for="q-${idx}-opt-f" id="label-q-${idx}-opt-f">
                    <input type="radio" name="q-${idx}-ans" id="q-${idx}-opt-f" value="False" style="margin-right:8px;">
                    <span>False</span>
                </label>
            `;
        } else {
            // Short Answer
            html += `
                <div class="form-group">
                    <textarea class="form-textarea" name="q-${idx}-ans" rows="3" placeholder="Type your structured explanation here..."></textarea>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;
    });

    html += `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:2rem; padding-top:1rem; border-top:1px solid var(--border-color);">
                <button type="button" class="btn btn-secondary" id="quiz-prev-btn" style="visibility:hidden;"><i data-lucide="arrow-left"></i> Previous</button>
                <button type="button" class="btn btn-primary" id="quiz-next-btn">Next <i data-lucide="arrow-right"></i></button>
                <button type="submit" class="btn btn-primary" id="quiz-submit-btn" style="display:none;"><i data-lucide="check"></i> Submit Answers</button>
            </div>
        </form>
    </div>
    `;

    workspace.innerHTML = html;
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }

    // Player State Variables
    let currentIdx = 0;
    const prevBtn = document.getElementById('quiz-prev-btn');
    const nextBtn = document.getElementById('quiz-next-btn');
    const submitBtn = document.getElementById('quiz-submit-btn');
    const progressInd = document.getElementById('question-progress-indicator');
    const activeForm = document.getElementById('active-quiz-run-form');

    // Radios selection styles helper
    const optionLabels = workspace.querySelectorAll('.option-item');
    optionLabels.forEach(lbl => {
        lbl.addEventListener('click', (e) => {
            const radio = lbl.querySelector('input[type="radio"]');
            if (radio) {
                // Clear sibling selections
                const name = radio.getAttribute('name');
                const siblings = workspace.querySelectorAll(`input[name="${name}"]`);
                siblings.forEach(s => {
                    const siblingLabel = s.closest('.option-item');
                    if (siblingLabel) siblingLabel.classList.remove('selected');
                });
                lbl.classList.add('selected');
            }
        });
    });

    const updateControls = () => {
        // Show/hide wrappers
        for (let i = 0; i < activeQuizQuestions.length; i++) {
            document.getElementById(`question-wrapper-${i}`).style.display = i === currentIdx ? 'block' : 'none';
        }
        
        // Navigation states
        prevBtn.style.visibility = currentIdx === 0 ? 'hidden' : 'visible';
        if (currentIdx === activeQuizQuestions.length - 1) {
            nextBtn.style.display = 'none';
            submitBtn.style.display = 'inline-flex';
        } else {
            nextBtn.style.display = 'inline-flex';
            submitBtn.style.display = 'none';
        }
        progressInd.textContent = `Question ${currentIdx + 1} of ${activeQuizQuestions.length}`;
    };

    nextBtn.addEventListener('click', () => {
        if (currentIdx < activeQuizQuestions.length - 1) {
            currentIdx++;
            updateControls();
        }
    });

    prevBtn.addEventListener('click', () => {
        if (currentIdx > 0) {
            currentIdx--;
            updateControls();
        }
    });

    activeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        // Gather responses
        const answers = [];
        for (let i = 0; i < activeQuizQuestions.length; i++) {
            const questionType = activeQuizQuestions[i].type;
            let val = "";
            if (questionType === 'sa') {
                const textarea = activeForm.querySelector(`textarea[name="q-${i}-ans"]`);
                val = textarea ? textarea.value.trim() : "";
            } else {
                const selectedRadio = activeForm.querySelector(`input[name="q-${i}-ans"]:checked`);
                val = selectedRadio ? selectedRadio.value : "";
            }
            answers.push(val);
        }

        // Validate complete
        const emptyCount = answers.filter(a => !a).length;
        if (emptyCount > 0) {
            if (!confirm(`You have left ${emptyCount} questions unanswered. Do you want to submit anyway?`)) {
                return;
            }
        }

        workspace.innerHTML = `
            <div style="text-align:center; padding: 4rem 0;">
                <span class="tutor-indicator" style="animation: pulseGlow 1.5s infinite"></span>
                <p style="margin-top: 1rem; color: var(--text-secondary)">Evaluating performance and computing weak areas reports...</p>
            </div>
        `;

        try {
            const response = await fetch('/api/submit-quiz', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: quizTitle,
                    questions: activeQuizQuestions,
                    answers: answers
                })
            });
            const data = await response.json();

            if (response.ok) {
                showToast('Quiz evaluated!');
                renderQuizResults(data);
            } else {
                workspace.innerHTML = `<div style="color:var(--danger)">Error: ${data.error || 'Evaluation failed.'}</div>`;
            }
        } catch (err) {
            console.error(err);
            workspace.innerHTML = `<div style="color:var(--danger)">Network error evaluating quiz.</div>`;
        }
    });
}

function renderQuizResults(results) {
    const workspace = document.getElementById('quiz-workspace');
    if (!workspace) return;

    let scoreColor = 'var(--danger)';
    const pct = (results.score / results.total_questions) * 100;
    if (pct >= 75) scoreColor = 'var(--success)';
    else if (pct >= 50) scoreColor = 'var(--warning)';

    let html = `
        <div class="glass-card fade-in">
            <div style="text-align:center; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 style="font-size:1.5rem; margin-bottom:0.5rem;"><i data-lucide="award"></i> Performance Score</h3>
                <span style="font-size: 3rem; font-weight: 800; color: ${scoreColor};">${results.score}</span>
                <span style="font-size: 1.5rem; color: var(--text-secondary)">/ ${results.total_questions}</span>
                <p style="font-weight: 500; color: var(--text-secondary); margin-top: 0.5rem;">Percentage: ${pct.toFixed(1)}%</p>
            </div>
            
            <h4 style="margin-bottom:1rem;"><i data-lucide="file-text"></i> Detailed Evaluation</h4>
    `;

    results.evaluation.forEach((ev, idx) => {
        const isCorrect = ev.is_correct;
        const color = isCorrect ? 'var(--success)' : 'var(--danger)';
        const icon = isCorrect ? 'check-circle' : 'x-circle';
        
        html += `
            <div class="glass-card" style="margin-bottom: 1.25rem; border-left: 4px solid ${color};">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap: 0.5rem; margin-bottom: 0.75rem;">
                    <strong style="font-size:0.95rem;">Question ${idx + 1}: ${ev.question}</strong>
                    <span style="color: ${color}; display:flex; align-items:center; gap:0.25rem; font-size:0.85rem; font-weight:600;">
                        <i data-lucide="${icon}" style="width:16px; height:16px;"></i> ${isCorrect ? 'Correct' : 'Incorrect'}
                    </span>
                </div>
                <div style="font-size:0.9rem; margin-bottom:0.5rem; color:var(--text-secondary);">
                    <p><strong>Your Answer:</strong> ${ev.user_answer || '<em style="color:var(--text-muted)">None</em>'}</p>
                    ${!isCorrect ? `<p><strong>Correct Answer:</strong> ${ev.correct_answer}</p>` : ''}
                </div>
                <div class="quiz-explanation">
                    <strong>Tutor Explanation:</strong> ${ev.explanation}
                </div>
            </div>
        `;
    });

    html += `
            <div style="text-align:center; margin-top: 2rem;">
                <a href="/weak-areas" class="btn btn-primary"><i data-lucide="trending-up"></i> Review Weak Areas Report</a>
                <a href="/quiz" class="btn btn-secondary" style="margin-left: 10px;"><i data-lucide="refresh-cw"></i> Try Another Quiz</a>
            </div>
        </div>
    `;

    workspace.innerHTML = html;
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Analytics and Progress Dashboard Handlers
async function setupProgressDashboard() {
    const ctxQuiz = document.getElementById('quizHistoryChart');
    const ctxTopics = document.getElementById('topicPerformanceChart');

    if (!ctxQuiz && !ctxTopics) return;

    try {
        const response = await fetch('/api/progress-data');
        const data = await response.json();

        if (!response.ok) {
            console.error('Failed to load chart analytics data');
            return;
        }

        // 1. History Line Chart
        if (ctxQuiz) {
            const labels = data.quiz_history.map(q => q.date);
            const scores = data.quiz_history.map(q => q.percentage);
            
            new Chart(ctxQuiz, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Quiz Scores (%)',
                        data: scores,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        borderWidth: 3,
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#9ca3af' } },
                        x: { grid: { display: false }, ticks: { color: '#9ca3af' } }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }

        // 2. Bar Chart of Topic Scores
        if (ctxTopics) {
            const labels = data.topic_scores.map(t => t.topic);
            const scores = data.topic_scores.map(t => t.score);
            
            new Chart(ctxTopics, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Avg. Score (%)',
                        data: scores,
                        backgroundColor: '#06b6d4',
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#9ca3af' } },
                        x: { grid: { display: false }, ticks: { color: '#9ca3af' } }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }

    } catch (err) {
        console.error("Error drawing analytics charts: ", err);
    }
}
