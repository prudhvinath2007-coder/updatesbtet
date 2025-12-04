import os
import json
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from results_service import prepare_result_context
from analytics import record_hit, get_total_hits  # Import analytics module

app = Flask(__name__)
app.secret_key = "replace_with_a_secure_random_key" 
app.config['ADMIN_PASSWORD'] = "Admin@123" 

# --- CONFIGURATION ---
UPLOAD_FOLDER = os.path.join('static', 'exam_papers')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
USERS_FILE = 'users.json'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- AUTH HELPERS ---

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please login to access this page.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTH ROUTES ---

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        mobile = request.form.get("mobile", "").strip()
        
        if not username or not password or not mobile:
            flash("All fields (Username, Password, Mobile) are required.")
            return redirect(url_for('register'))
            
        users = load_users()
        if username in users:
            flash("Username already exists.")
            return redirect(url_for('register'))
            
        users[username] = {
            "password": generate_password_hash(password),
            "mobile": mobile,
            "joined_date": datetime.date.today().strftime("%Y-%m-%d")
        }
        save_users(users)
        flash("Registration successful! Please login.")
        return redirect(url_for('login'))
        
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        users = load_users()
        
        if username in users:
            user_data = users[username]
            # Handle backward compatibility
            stored_hash = user_data if isinstance(user_data, str) else user_data.get("password")
            
            if check_password_hash(stored_hash, password):
                session['user'] = username
                flash(f"Welcome back, {username}!")
                return redirect(url_for('index'))
                
        flash("Invalid credentials.")
        return redirect(url_for('login'))
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    flash("Logged out.")
    return redirect(url_for('login'))

# --- MAIN APP ROUTES ---

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    # Record a hit every time the home page is accessed
    record_hit()
    
    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        if pin:
            return redirect(url_for("result", pin=pin))
    return render_template("index.html")

@app.route("/result/<pin>")
@login_required
def result(pin):
    try:
        ctx = prepare_result_context(pin)
        if not ctx["summary"].get("pin"):
            flash("No data found.")
            return redirect(url_for("index"))
        return render_template("result.html", pin=pin, **ctx)
    except Exception as e:
        print(e)
        flash("Error fetching result.")
        return redirect(url_for("index"))

# --- EXAM PAPERS (VIEW ONLY - LOGIN REQUIRED) ---

def get_library_data():
    branches = ['CSE', 'ECE', 'EEE', 'MECH', 'CIVIL']
    semesters = ['Sem1', 'Sem2', 'Sem3', 'Sem4', 'Sem5', 'Sem6']
    library = {}

    for branch in branches:
        library[branch] = {}
        for sem in semesters:
            path = os.path.join(app.config['UPLOAD_FOLDER'], branch, sem)
            meta_path = os.path.join(path, 'metadata.json')
            papers_by_subject = {}
            
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r') as f:
                        file_list = json.load(f)
                        for paper in file_list:
                            subj = paper.get('subject', 'General')
                            if subj not in papers_by_subject:
                                papers_by_subject[subj] = []
                            papers_by_subject[subj].append(paper)
                except:
                    pass
            library[branch][sem] = papers_by_subject
    return library, branches, semesters

@app.route("/exam-papers")
@login_required
def exam_papers():
    # This route is protected. Only logged-in students can view papers.
    library, branches, semesters = get_library_data()
    return render_template("exam_papers.html", library=library, branches=branches, semesters=semesters)

# --- PUBLIC UPLOAD ROUTES (NO LOGIN REQUIRED) ---

@app.route("/public-upload")
def public_upload():
    # Accessible by everyone
    branches = ['CSE', 'ECE', 'EEE', 'MECH', 'CIVIL']
    semesters = ['Sem1', 'Sem2', 'Sem3', 'Sem4', 'Sem5', 'Sem6']
    return render_template("public_upload.html", branches=branches, semesters=semesters)

@app.route("/upload-paper", methods=["POST"])
def upload_paper():
    # Handles uploads from the public page
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    branch = request.form.get('branch')
    semester = request.form.get('semester')
    subject = request.form.get('subject', '').strip().title()
    exam_type = request.form.get('exam_type')
    contributor = request.form.get('contributor', 'Anonymous')
    year = request.form.get('year', '2024')

    if not file.filename or not branch or not semester or not exam_type or not subject:
        flash('All fields are required.')
        return redirect(url_for('public_upload'))

    if file and allowed_file(file.filename):
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], branch, semester)
        os.makedirs(save_path, exist_ok=True)
        
        # Rename logic
        safe_subject = secure_filename(subject).replace("_", "")
        safe_type = exam_type.replace(" ", "")
        ts = datetime.datetime.now().strftime("%H%M%S")
        new_filename = f"{safe_subject}_{safe_type}_{year}_{ts}.pdf"
        
        file.save(os.path.join(save_path, new_filename))
        
        # Metadata logic
        meta_path = os.path.join(save_path, 'metadata.json')
        metadata = []
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r') as f:
                    metadata = json.load(f)
            except:
                pass
        
        metadata.append({
            "filename": new_filename,
            "subject": subject,
            "exam_type": exam_type,
            "contributor": contributor,
            "year": year,
            "upload_date": datetime.date.today().strftime("%d-%m-%Y")
        })
        
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=4)

        flash(f'Thank you! {exam_type} paper for {subject} uploaded.')
        return redirect(url_for('public_upload'))
    else:
        flash('Invalid file. PDF only.')
        return redirect(url_for('public_upload'))

# --- STRICT VIEW ROUTE (LOGIN REQUIRED) ---

@app.route("/view-paper/<branch>/<sem>/<filename>")
@login_required
def view_paper(branch, sem, filename):
    # Only logged in users can view the PDF
    file_static_path = f"exam_papers/{branch}/{sem}/{filename}"
    return render_template("view_paper.html", file_url=url_for('static', filename=file_static_path))

# --- ADMIN ROUTES ---

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            flash("Admin logged in.")
            return redirect(url_for("admin_dashboard"))
        flash("Incorrect password.")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for("admin_login"))
    
    library, branches, semesters = get_library_data()
    total_hits = get_total_hits() # Fetch hit count
    
    return render_template("admin_dashboard.html", library=library, total_hits=total_hits)

@app.route("/admin/delete", methods=["POST"])
def delete_paper():
    if not session.get('is_admin'):
        return redirect(url_for("admin_login"))
    
    branch = request.form.get('branch')
    sem = request.form.get('sem')
    filename = request.form.get('filename')
    
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], branch, sem)
    file_path = os.path.join(folder_path, filename)
    meta_path = os.path.join(folder_path, 'metadata.json')
    
    if os.path.exists(file_path):
        os.remove(file_path)
        
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r') as f:
                data = json.load(f)
            new_data = [d for d in data if d['filename'] != filename]
            with open(meta_path, 'w') as f:
                json.dump(new_data, f, indent=4)
        except:
            pass

    flash(f"Deleted {filename}")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.pop('is_admin', None)
    flash("Admin logged out.")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)