import os
import json
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from results_service import prepare_result_context
from analytics import record_hit, get_total_hits
import traceback
from flask import send_file
import secrets

# --- APP INITIALIZATION ---
app = Flask(__name__)
app.secret_key = "replace_with_a_secure_random_key"
app.config['ADMIN_PASSWORD'] = "Admin@123"

# --- CONFIGURATION ---
UPLOAD_FOLDER = os.path.join('static', 'exam_papers')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
USERS_FILE = 'users.json'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- AUTH HELPERS ---
def load_users():
    if not os.path.exists(USERS_FILE): return {}
    try:
        with open(USERS_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f: json.dump(users, f, indent=4)

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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        mobile = request.form.get("mobile", "").strip()
        pin = request.form.get("pin", "").strip()  # Capture PIN from form

        # Validate all fields
        if not username or not password or not mobile or not pin:
            flash("All fields (Username, Password, Mobile, PIN) are required.")
            return redirect(url_for('register'))

        users = load_users()
        if username in users:
            flash("Username already exists.")
            return redirect(url_for('register'))

        users[username] = {
            "password": generate_password_hash(password),
            "mobile": mobile,
            "pin": pin,
            "joined": datetime.date.today().strftime("%Y-%m-%d")
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
            stored = users[username] if isinstance(users[username], str) else users[username].get("password")
            if check_password_hash(stored, password):
                session['user'] = username
                return redirect(url_for('index'))
        flash("Invalid credentials.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    return redirect(url_for('login'))

# --- MAIN APP ROUTES ---
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    try: record_hit()
    except NameError: pass

    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        # ensure consent is checked client-side; server-side cannot see localStorage,
        # but you can optionally send a value to enforce on server as well.
        if pin:
            return redirect(url_for("result", pin=pin))
    return render_template("index.html")

@app.route("/result/<pin>")
@login_required
def result(pin):
    try:
        ctx = prepare_result_context(pin)

        if not ctx or not ctx.get("summary", {}).get("pin"):
            flash("No result data found for this PIN. Please check the number or try again.")
            return redirect(url_for("index"))

        return render_template("result.html", pin=pin, **ctx)

    except Exception as e:
        # LOG THE ERROR for debugging the server
        print("--- RESULT FETCH ERROR ---")
        print(f"PIN: {pin}")
        traceback.print_exc()
        print("--------------------------")

        flash(f"Failed to fetch results due to a system error. Please check the terminal logs for details.")
        return redirect(url_for("index"))

# --- EXAM PAPERS (VIEW ONLY - LOGIN REQUIRED) ---
def get_library_data():
    branches = ['CSE', 'ECE', 'EEE', 'MECH', 'CIVIL']
    semesters = ['Sem1', 'Sem2', 'Sem3', 'Sem4', 'Sem5', 'Sem6']
    library = {}
    for branch in branches:
        library[branch] = {}
        for sem in semesters:
            meta_path = os.path.join(app.config['UPLOAD_FOLDER'], branch, sem, 'metadata.json')
            papers = []
            if os.path.exists(meta_path):
                try:
                    with open(meta_path) as f: papers = json.load(f)
                except: pass

            grouped = {}
            for p in papers:
                sub = p.get('subject', 'General')
                if sub not in grouped: grouped[sub] = []
                grouped[sub].append(p)
            library[branch][sem] = grouped

    return library, branches, semesters

@app.route("/exam-papers")
@login_required
def exam_papers():
    library, branches, semesters = get_library_data()
    return render_template("exam_papers.html", library=library, branches=branches, semesters=semesters)

# --- PUBLIC UPLOAD ROUTES (NO LOGIN REQUIRED) ---
@app.route("/public-upload")
def public_upload():
    branches = ['CSE', 'ECE', 'EEE', 'MECH', 'CIVIL']
    semesters = ['Sem1', 'Sem2', 'Sem3', 'Sem4', 'Sem5', 'Sem6']
    return render_template("public_upload.html", branches=branches, semesters=semesters)

@app.route("/upload-paper", methods=["POST"])
def upload_paper():
    if 'file' not in request.files: return redirect(request.url)
    file = request.files['file']
    branch = request.form.get('branch')
    semester = request.form.get('semester')
    subject = request.form.get('subject', '').strip().title()
    exam_type = request.form.get('exam_type')
    contributor = request.form.get('contributor', 'Anonymous')
    year = request.form.get('year', '2024')

    if file and allowed_file(file.filename):
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], branch, semester)
        os.makedirs(save_path, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H%M%S")
        safe_sub = secure_filename(subject).replace("_", "")
        new_filename = f"{safe_sub}_{exam_type.replace(' ', '')}_{year}_{ts}.pdf"
        file.save(os.path.join(save_path, new_filename))

        # Metadata
        meta_path = os.path.join(save_path, 'metadata.json')
        data = []
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f: data = json.load(f)
            except: pass

        data.append({
            "filename": new_filename, "subject": subject, "exam_type": exam_type,
            "contributor": contributor, "year": year,
            "upload_date": datetime.date.today().strftime("%d-%m-%Y")
        })
        with open(meta_path, 'w') as f: json.dump(data, f, indent=4)
        flash("Uploaded successfully!")
        return redirect(url_for('public_upload'))
    flash("Invalid file.")
    return redirect(url_for('public_upload'))

@app.route("/secure-get-pdf/<branch>/<sem>/<filename>")
@login_required
def secure_get_pdf(branch, sem, filename):
    token = request.headers.get('X-Viewer-Token')
    if not token or token != session.get('viewer_token'):
        print("DEBUG: secure-get-pdf denied - missing or invalid token", "token:", token, "session:", session.get('viewer_token'))
        return "Forbidden", 403

    local_path = os.path.join(app.config['UPLOAD_FOLDER'], branch, sem, filename)
    print("DEBUG: Looking for file", local_path, "exists?", os.path.exists(local_path))
    if not os.path.exists(local_path):
        return "File not found", 404

    response = send_file(local_path, mimetype='application/pdf', as_attachment=False)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.route("/view-paper/<branch>/<sem>/<filename>")
@login_required
def view_paper(branch, sem, filename):
    token = secrets.token_urlsafe(24)
    session['viewer_token'] = token

    viewer = session.get('user')
    viewer_meta = {}
    try:
        users = load_users()
        if viewer and viewer in users and isinstance(users[viewer], dict):
            viewer_meta = users[viewer]
    except Exception:
        viewer_meta = {}

    return render_template(
        "view_paper.html",
        branch=branch, sem=sem, filename=filename,
        viewer=viewer, viewer_meta=viewer_meta, viewer_token=token
    )

# --- CSP nonce before each request ---
@app.before_request
def add_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)

@app.context_processor
def inject_nonce():
    return dict(csp_nonce=getattr(g, 'csp_nonce', ''))

# --- single after_request CSP that allows AdSense + Chart.js + safe Google subdomains ---
@app.after_request
def set_security_headers(response):
    nonce = getattr(g, 'csp_nonce', '')

    # Comprehensive allowed domains for ads + analytics + CDN (adjust if you see additional blocked domains)
    csp = (
        "default-src 'self'; "

        # script sources: allow self, jsdelivr (Chart.js), and Google ad endpoints
        f"script-src 'self' https://cdn.jsdelivr.net "
        "https://pagead2.googlesyndication.com "
        "https://googleads.g.doubleclick.net "
        "https://adservice.google.com "
        "https://tpc.googlesyndication.com "
        "https://www.google.com "
        f"'nonce-{nonce}'; "

        # styles (allow inline for small UI tweaks)
        "style-src 'self' 'unsafe-inline'; "

        # images: allow common google ad image endpoints + adtrafficquality subdomains (ep1/ep2/ep3)
        "img-src 'self' data: "
        "https://pagead2.googlesyndication.com "
        "https://googleads.g.doubleclick.net "
        "https://tpc.googlesyndication.com "
        "https://www.google.com "
        "https://ep1.adtrafficquality.google "
        "https://ep2.adtrafficquality.google "
        "https://ep3.adtrafficquality.google; "

        # frames: allow ad frames and adtrafficquality frames
        "frame-src "
        "https://googleads.g.doubleclick.net "
        "https://pagead2.googlesyndication.com "
        "https://adservice.google.com "
        "https://tpc.googlesyndication.com "
        "https://www.google.com "
        "https://ep1.adtrafficquality.google "
        "https://ep2.adtrafficquality.google "
        "https://ep3.adtrafficquality.google; "

        # connections: allow ad endpoints & google services used by ads
        "connect-src 'self' "
        "https://googleads.g.doubleclick.net "
        "https://pagead2.googlesyndication.com "
        "https://adservice.google.com "
        "https://tpc.googlesyndication.com "
        "https://www.google.com https:; "

        # block everything else that shouldn't run
        "object-src 'none'; "
        "frame-ancestors 'none'; "
    )

    response.headers['Content-Security-Policy'] = csp
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

# --- ADMIN ROUTES ---
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            return redirect(url_for("admin_dashboard"))
        flash("Wrong password.")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get('is_admin'): return redirect(url_for("admin_login"))
    try: total_hits = get_total_hits()
    except NameError: total_hits = 0

    library, branches, semesters = get_library_data()

    return render_template("admin_dashboard.html", library=library, total_hits=total_hits)

@app.route("/admin/delete", methods=["POST"])
def delete_paper():
    if not session.get('is_admin'): return redirect(url_for("admin_login"))
    branch = request.form.get('branch')
    sem = request.form.get('sem')
    filename = request.form.get('filename')

    path = os.path.join(app.config['UPLOAD_FOLDER'], branch, sem)
    try: os.remove(os.path.join(path, filename))
    except: pass

    meta_path = os.path.join(path, 'metadata.json')
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f: data = json.load(f)
            data = [d for d in data if d['filename'] != filename]
            with open(meta_path, 'w') as f: json.dump(data, f, indent=4)
        except: pass

    flash("Deleted.")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.pop('is_admin', None)
    flash("Admin logged out.")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
