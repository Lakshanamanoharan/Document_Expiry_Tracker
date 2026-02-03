import os
import re
import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, abort
import dateparser
from werkzeug.utils import secure_filename
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Text Extraction Libraries
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

TESSERACT_AVAILABLE = False
try:
    import pytesseract
    from PIL import Image
    
    # SYSTEM PATH CHECK
    # 1. Check if Tesseract is in the system PATH
    try:
        pytesseract.get_tesseract_version()
        TESSERACT_AVAILABLE = True
    except:
        # 2. If not in PATH, try common Windows installation paths
        common_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Users\laksh\AppData\Local\Programs\Tesseract-OCR\tesseract.exe' 
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                TESSERACT_AVAILABLE = True
                print(f"Found Tesseract at: {path}")
                break
        
        if not TESSERACT_AVAILABLE:
            print("Tesseract not found in PATH or common locations.")

except ImportError:
    pytesseract = None
    Image = None

app = Flask(__name__)
app.secret_key = 'supersecretkey' # Required for flashing messages

# =========================
# CONFIG
# =========================
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx', 'png', 'jpg', 'jpeg', 'tiff', 'bmp'}
DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Flask-Login Context
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    db.close()
    if user_row:
        return User(id=user_row['id'], username=user_row['username'])
    return None

# =========================
# DATABASE CONNECTION
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Create documents table with user_id
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            type TEXT,
            expiry_date DATE,
            filename TEXT,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Migration: Add user_id to documents if it doesn't exist
    try:
        cursor.execute("ALTER TABLE documents ADD COLUMN user_id INTEGER REFERENCES users (id)")
    except sqlite3.OperationalError:
        pass
        
    # Migration: Add tags to documents if it doesn't exist
    try:
        cursor.execute("ALTER TABLE documents ADD COLUMN tags TEXT")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

# Initialize DB on start
init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

# =========================
# DATE EXTRACTION FROM FILENAME
# =========================


# =========================
# TEXT EXTRACION
# =========================
def extract_text_from_file(filepath):
    """
    Extracts text from PDF, DOCX, or Image files.
    """
    ext = os.path.splitext(filepath)[1].lower()
    text = ""

    try:
        if ext == '.pdf':
            if pypdf:
                reader = pypdf.PdfReader(filepath)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
        elif ext == '.docx':
            if DocxDocument:
                doc = DocxDocument(filepath)
                for para in doc.paragraphs:
                    text += para.text + "\n"
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            if pytesseract and Image:
                text = pytesseract.image_to_string(Image.open(filepath))
    except Exception as e:
        print(f"Error extracting text from {filepath}: {e}")

    return text

def extract_date(text):
    """
    Extracts the document expiry date from text.
    Prioritizes dates following keywords like 'To', 'Expires', 'Until'.
    If no clear context, prefers the later date in a range.
    """
    if not text:
        return None

    # Normalization for easier regex matching
    normalized_text = text.replace('\n', ' ')

    # Common date patterns (regex)
    date_patterns = [
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',       # 12/10/2025 or 12-10-2025
        r'\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}\b',  # 10th Jan 2025
        r'\b[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?\s+\d{4}\b',  # Jan 10th 2025
        r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b'          # 2025-12-31
    ]

    all_matches = []
    for pattern in date_patterns:
        for match in re.finditer(pattern, normalized_text):
            date_str = match.group()
            # Use dateparser to convert to date object
            date_obj = dateparser.parse(date_str)
            if date_obj:
                all_matches.append({
                    'date': date_obj.date(),
                    'start': match.start(),
                    'end': match.end()
                })

    if not all_matches:
        return None

    # Expiry keywords to look for in the text preceding the date
    expiry_keywords = ['to', 'expir', 'until', 'end', 'thru', 'through', 'valid']
    start_keywords = ['from', 'issue', 'start', 'begin', 'on']
    
    scored_matches = []
    for match in all_matches:
        score = 0
        # Look at ~30 characters before the date for context
        lookback = normalized_text[max(0, match['start']-30):match['start']].lower()
        
        # Bonus for expiry keywords
        if any(keyword in lookback for keyword in expiry_keywords):
            score += 10
            
        # Penalty for start keywords (to avoid issue dates)
        if any(keyword in lookback for keyword in start_keywords):
            score -= 5
            
        # Preference for dates in a reasonable range (2000 - 2050)
        current_year = date.today().year
        if 2000 <= match['date'].year <= 2050:
            score += 2
        elif match['date'].year < current_year - 5 or match['date'].year > 2060:
            # Harsh penalty for very old or very future dates unless keyword match is strong
            score -= 8
            
        scored_matches.append((score, match['date']))

    # Sort by score descending, then by date descending (prefer later date)
    scored_matches.sort(key=lambda x: (x[0], x[1]), reverse=True)

    return scored_matches[0][1]

# =========================
# FILE VIEW
# =========================
@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    # Security: Verify ownership before serving
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM documents WHERE user_id = ? AND filename = ?", (current_user.id, filename))
    doc = cursor.fetchone()
    db.close()
    
    if not doc:
        abort(403) # Forbidden
        
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# =========================
# DASHBOARD
# =========================
@app.route('/')
@login_required
def dashboard():
    search_query = request.args.get('search', '')
    
    db = get_db()
    cursor = db.cursor()
    
    if search_query:
        cursor.execute("""
            SELECT * FROM documents 
            WHERE user_id = ? AND (name LIKE ? OR type LIKE ?)
        """, (current_user.id, f'%{search_query}%', f'%{search_query}%'))
    else:
        cursor.execute("SELECT * FROM documents WHERE user_id = ?", (current_user.id,))
        
    docs = cursor.fetchall()
    today = date.today()

    expired = expiring = 0
    processed_docs = []

    for row in docs:
        d = dict(row) # Convert to dict
        status = "No Expiry"
        expiry_str = d['expiry_date']

        # Convert expiry string to date object
        expiry_date = None
        if expiry_str:
            try:
                # SQLite returns dates as strings e.g. '2025-01-01'
                expiry_date = datetime.strptime(str(expiry_str), '%Y-%m-%d').date()
            except:
                expiry_date = None

        if expiry_date:
            days = (expiry_date - today).days
            if days < 0:
                status = "Expired"
                expired += 1
            elif days <= 15:
                status = "Expiring Soon"
                expiring += 1
            else:
                status = "Valid"

        d['status'] = status
        processed_docs.append(d)

    total = len(processed_docs)
    compliance = 0 if total == 0 else int(((total - expired) / total) * 100)

    return render_template(
        'dashboard.html',
        docs=processed_docs,
        total=total,
        expired=expired,
        expiring=expiring,
        compliance=compliance,
        search_query=search_query
    )

# =========================
# AUTHENTICATION ROUTES
# =========================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        cursor = db.cursor()
        
        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            flash("Username already exists", "error")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed_pw))
        db.commit()
        db.close()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        db.close()
        
        if user_row and check_password_hash(user_row['password_hash'], password):
            user_obj = User(id=user_row['id'], username=user_row['username'])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password", "error")
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

# =========================
# ADD DOCUMENT
# =========================
@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_document():
    if request.method == 'POST':
        doc_type = request.form['type']
        manual_expiry = request.form.get('expiry')

        files = request.files.getlist('files')
        db = get_db()
        cursor = db.cursor()

        for file in files:
            if not file or not allowed_file(file.filename):
                continue
                
            filename = secure_filename(file.filename)
            
            # Ensure unique filename to prevent overwrite
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1

            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Try to extract date from filename first, then content
            expiry_date = extract_date(filename)
            
            if not expiry_date:
                # Check for image type and missing tesseract
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.png', '.jpg', '.jpeg'] and not TESSERACT_AVAILABLE:
                    flash(f"Warning: Could not scan '{filename}' for dates because Tesseract OCR is not installed/found on server.", "warning")
                
                # Extract text content and search for date
                file_text = extract_text_from_file(file_path)
                expiry_date = extract_date(file_text)

            # If still no date, use manual entry if provided
            if not expiry_date and manual_expiry:
                try:
                    expiry_date = datetime.strptime(manual_expiry, '%Y-%m-%d').date()
                except:
                    expiry_date = None
            
            if not expiry_date and not manual_expiry:
                flash(f"Note: No date detected for '{filename}'. Please edit to add manually.", "info")

            tags = request.form.get('tags', '')

            cursor.execute(
                "INSERT INTO documents (user_id, name, type, expiry_date, filename, tags) VALUES (?,?,?,?,?,?)",
                (current_user.id, filename, doc_type, expiry_date, filename, tags)
            )

        db.commit()
        db.close()
        return redirect(url_for('dashboard'))

    return render_template('add_document.html')

# =========================
# FILTERS
# =========================
@app.route('/expired')
@login_required
def expired_documents():
    db = get_db()
    cursor = db.cursor()
    # SQLite uses DATE('now')
    cursor.execute("SELECT * FROM documents WHERE user_id = ? AND expiry_date < DATE('now')", (current_user.id,))
    docs = [dict(row) for row in cursor.fetchall()]
    for d in docs:
        d['status'] = "Expired"
    return render_template('dashboard.html', docs=docs,
                           total=len(docs), expired=len(docs),
                           expiring=0, compliance=0)

@app.route('/expiring')
@login_required
def expiring_documents():
    db = get_db()
    cursor = db.cursor()
    # SQLite date logic
    cursor.execute("""
        SELECT * FROM documents
        WHERE user_id = ? AND expiry_date BETWEEN DATE('now') AND DATE('now', '+15 days')
    """, (current_user.id,))
    docs = [dict(row) for row in cursor.fetchall()]
    for d in docs:
        d['status'] = "Expiring Soon"
    return render_template('dashboard.html', docs=docs,
                           total=len(docs), expired=0,
                           expiring=len(docs), compliance=0)

# =========================
# VIEW ALL DOCUMENTS
# =========================
@app.route('/documents')
@login_required
def documents():
    # Redirect to dashboard essentially, or could be a separate list view
    # Reusing dashboard logic for consistency with new dict conversion
    return dashboard()

# =========================
# DELETE DOCUMENT
# =========================
# EDIT DOCUMENT
# =========================
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_document(id):
    db = get_db()
    cursor = db.cursor()
    
    # Ensure user owns the document
    cursor.execute("SELECT * FROM documents WHERE id = ? AND user_id = ?", (id, current_user.id))
    doc = cursor.fetchone()
    
    if not doc:
        db.close()
        flash("Document not found or access denied.", "error")
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        doc_type = request.form.get('type')
        expiry_date = request.form.get('expiry')
        tags = request.form.get('tags', '')
        
        cursor.execute("""
            UPDATE documents 
            SET name = ?, type = ?, expiry_date = ?, tags = ?
            WHERE id = ? AND user_id = ?
        """, (name, doc_type, expiry_date, tags, id, current_user.id))
        
        db.commit()
        db.close()
        flash("Document updated successfully!", "success")
        return redirect(url_for('dashboard'))
        
    db.close()
    return render_template('edit_document.html', doc=dict(doc))

# =========================
@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_document(id):
    db = get_db()
    cursor = db.cursor()
    # Ensure user owns the document before deleting
    cursor.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (id, current_user.id))
    db.commit()
    db.close()
    flash("Document deleted.", "success")
    return redirect(url_for('dashboard'))

# =========================
# BULK ACTIONS
# =========================
@app.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    doc_ids = request.form.getlist('doc_ids')
    if not doc_ids:
        flash("No documents selected.", "warning")
        return redirect(url_for('dashboard'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Securely delete only if owned by current user
    placeholders = ','.join(['?'] * len(doc_ids))
    query = f"DELETE FROM documents WHERE user_id = ? AND id IN ({placeholders})"
    cursor.execute(query, [current_user.id] + doc_ids)
    
    db.commit()
    db.close()
    flash(f"Deleted {len(doc_ids)} documents.", "success")
    return redirect(url_for('dashboard'))

# =========================
# EXPORT
# =========================
@app.route('/export')
@login_required
def export_csv():
    import csv
    import io
    from flask import make_response

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name, type, expiry_date, tags, created_at FROM documents WHERE user_id = ?", (current_user.id,))
    rows = cursor.fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Document Name', 'Type', 'Expiry Date', 'Tags', 'Created At'])
    for row in rows:
        writer.writerow(list(row))

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=documents_export.csv"
    response.headers["Content-type"] = "text/csv"
    return response

# =========================
if __name__ == '__main__':
    app.run(debug=True)
