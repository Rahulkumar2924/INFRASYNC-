import os
import sqlite3
import random
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from werkzeug.utils import secure_filename
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, Response, send_from_directory

# Safe environment loading (handles missing python-dotenv gracefully)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "infrasync_secure_session_token_key")

DB_PATH = os.path.join("data", "campus.db")
UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

os.makedirs("data", exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@campus.edu")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@2026")

# --- LIVE SMTP CREDENTIALS ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "rahulkumarpandu7@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "oyan wbkv zkfs nerw")

PENDING_REGISTRATIONS = {}
PENDING_PASSWORD_RESETS = {}

def send_email_notification(target_email, subject, heading, body_text, code_badge=None):
    """Dispatches clean HTML notification emails to student inboxes."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Infrasync Campus Hub <{SENDER_EMAIL}>"
        msg["To"] = target_email

        badge_html = ""
        if code_badge:
            badge_html = f"""
            <div style="background-color: #0F172A; border: 1px solid #10B981; border-radius: 8px; padding: 18px; text-align: center; margin: 22px 0;">
                <span style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #10B981;">{code_badge}</span>
            </div>
            """

        html_content = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #090D16; color: #F8FAFC; padding: 32px; border-radius: 12px; max-width: 520px; margin: auto; border: 1px solid rgba(255,255,255,0.1);">
            <h2 style="color: #f87171; margin-top: 0; font-size: 22px;">{heading}</h2>
            <div style="color: #94A3B8; font-size: 15px; line-height: 1.6;">{body_text}</div>
            {badge_html}
            <hr style="border: none; border-top: 1px solid rgba(255,255,255,0.1); margin: 24px 0 16px 0;">
            <p style="color: #64748B; font-size: 12px; margin: 0;">Infrasync Campus Operations Dispatch System.</p>
        </div>
        """
        msg.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, target_email, msg.as_string())
        server.quit()
        print(f"[SUCCESS] Email delivered to: {target_email} | Subject: {subject}")
        return True, "Email sent successfully"
    except Exception as e:
        print(f"[SMTP WARNING] Failed to send email to {target_email}: {e}")
        return False, str(e)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            scholar_no TEXT UNIQUE,
            password TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT UNIQUE NOT NULL,
            student_scholar_no TEXT NOT NULL,
            student_name TEXT NOT NULL,
            student_email TEXT NOT NULL,
            department TEXT NOT NULL,
            building TEXT NOT NULL,
            room_no TEXT DEFAULT '',
            category TEXT NOT NULL,
            problem TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            image_path TEXT,
            date TEXT NOT NULL,
            rating INTEGER,
            feedback TEXT
        )
    ''')

    cursor.execute("PRAGMA table_info(complaints)")
    columns = [col[1] for col in cursor.fetchall()]
    if "rating" not in columns:
        cursor.execute("ALTER TABLE complaints ADD COLUMN rating INTEGER")
    if "feedback" not in columns:
        cursor.execute("ALTER TABLE complaints ADD COLUMN feedback TEXT")
    if "room_no" not in columns:
        cursor.execute("ALTER TABLE complaints ADD COLUMN room_no TEXT DEFAULT ''")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            repair_date TEXT NOT NULL,
            cost REAL NOT NULL,
            remarks TEXT NOT NULL,
            FOREIGN KEY (complaint_id) REFERENCES complaints (complaint_id)
        )
    ''')
    
    cursor.execute("SELECT * FROM users WHERE email = ?", (ADMIN_EMAIL,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (name, email, scholar_no, password, department, role)
            VALUES ('College Administrator', ?, NULL, ?, 'Campus Administration', 'admin')
        ''', (ADMIN_EMAIL, ADMIN_PASSWORD))
    
    conn.commit()
    conn.close()

# Initialize tables automatically for both local and cloud production
init_db()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# --- REGISTRATION OTP FLOW ---

@app.route("/api/auth/send-registration-otp", methods=["POST"])
def send_registration_otp():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    scholar_no = data.get("scholar_no", "").strip()
    password = data.get("password", "").strip()
    confirm_password = data.get("confirm_password", "").strip()
    dept = data.get("department", "").strip()

    if not name or not email or not scholar_no or not password or not dept:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    if not (scholar_no.isdigit() and len(scholar_no) == 6):
        return jsonify({"success": False, "message": "Scholar Number must contain exactly 6 digits."}), 400

    if email == ADMIN_EMAIL.lower():
        return jsonify({"success": False, "message": "This email address is reserved for administration."}), 403

    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email, scholar_no FROM users WHERE LOWER(email) = ? OR scholar_no = ?", (email, scholar_no))
    existing = cursor.fetchone()
    conn.close()

    if existing:
        if existing["email"].lower() == email:
            return jsonify({"success": False, "message": "This Email is already registered. Please sign in."}), 400
        if existing["scholar_no"] == scholar_no:
            return jsonify({"success": False, "message": "This Scholar Number is already registered."}), 400

    otp_code = str(random.randint(100000, 999999))
    expires_at = time.time() + 300

    PENDING_REGISTRATIONS[email] = {
        "otp": otp_code,
        "expires": expires_at,
        "data": {
            "name": name,
            "email": email,
            "scholar_no": scholar_no,
            "password": password,
            "department": dept
        }
    }

    send_email_notification(
        target_email=email,
        subject=f"Infrasync Verification Code: {otp_code}",
        heading="Student Account Verification",
        body_text=f"Hello <b>{name}</b>,<br>Use the 6-digit OTP code below to verify your student email address:",
        code_badge=otp_code
    )

    return jsonify({
        "success": True,
        "message": f"Verification code sent to {email}."
    })

@app.route("/api/auth/verify-registration-otp", methods=["POST"])
def verify_registration_otp():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email", "").strip().lower()
    otp_input = data.get("otp", "").strip()

    if not email or not otp_input:
        return jsonify({"success": False, "message": "Email and OTP code are required."}), 400

    record = PENDING_REGISTRATIONS.get(email)
    if not record:
        return jsonify({"success": False, "message": "No pending registration found. Please register again."}), 400

    if time.time() > record["expires"]:
        del PENDING_REGISTRATIONS[email]
        return jsonify({"success": False, "message": "OTP has expired. Please sign up again."}), 400

    if record["otp"] != otp_input:
        return jsonify({"success": False, "message": "Invalid OTP code. Please check your inbox."}), 400

    user_info = record["data"]
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO users (name, email, scholar_no, password, department, role)
            VALUES (?, ?, ?, ?, ?, 'student')
        ''', (user_info["name"], user_info["email"], user_info["scholar_no"], user_info["password"], user_info["department"]))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        del PENDING_REGISTRATIONS[email]

        session.clear()
        session["user_id"] = user_id
        session["user_name"] = user_info["name"]
        session["user_email"] = user_info["email"]
        session["user_scholar_no"] = user_info["scholar_no"]
        session["user_role"] = "student"
        session["user_dept"] = user_info["department"]

        return jsonify({
            "success": True,
            "message": f"Account verified! Welcome, {user_info['name']}.",
            "user": {
                "name": user_info["name"],
                "email": user_info["email"],
                "scholar_no": user_info["scholar_no"],
                "role": "student",
                "dept": user_info["department"]
            }
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "message": "Account already registered."}), 400

# --- FORGOT PASSWORD OTP FLOW ---

@app.route("/api/auth/forgot-password-otp", methods=["POST"])
def forgot_password_otp():
    data = request.get_json(force=True, silent=True) or {}
    scholar_no = data.get("scholar_no", "").strip()
    email = data.get("email", "").strip().lower()

    if not scholar_no or not email:
        return jsonify({"success": False, "message": "Scholar Number and registered Email are required."}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE scholar_no = ? AND LOWER(email) = ? AND role = 'student'", (scholar_no, email))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"success": False, "message": "No account matched that Scholar Number and Email."}), 404

    otp_code = str(random.randint(100000, 999999))
    expires_at = time.time() + 300

    PENDING_PASSWORD_RESETS[email] = {
        "otp": otp_code,
        "expires": expires_at,
        "user_id": user["id"],
        "name": user["name"],
        "scholar_no": user["scholar_no"],
        "department": user["department"]
    }

    send_email_notification(
        target_email=email,
        subject=f"Infrasync Password Reset OTP: {otp_code}",
        heading="Password Reset Verification",
        body_text=f"Hello <b>{user['name']}</b>,<br>Use the OTP below to reset your Infrasync password:",
        code_badge=otp_code
    )

    return jsonify({
        "success": True,
        "message": f"Password reset OTP sent to {email}."
    })

@app.route("/api/auth/verify-reset-password", methods=["POST"])
def verify_reset_password():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email", "").strip().lower()
    otp_input = data.get("otp", "").strip()
    new_password = data.get("new_password", "").strip()
    confirm_password = data.get("confirm_password", "").strip()

    if not email or not otp_input or not new_password:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "message": "New passwords do not match."}), 400

    record = PENDING_PASSWORD_RESETS.get(email)
    if not record:
        return jsonify({"success": False, "message": "No active reset request found. Please request an OTP again."}), 400

    if time.time() > record["expires"]:
        del PENDING_PASSWORD_RESETS[email]
        return jsonify({"success": False, "message": "OTP has expired. Please request a new code."}), 400

    if record["otp"] != otp_input:
        return jsonify({"success": False, "message": "Invalid OTP code. Please check your inbox."}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password = ? WHERE id = ?", (new_password, record["user_id"]))
    conn.commit()
    conn.close()

    session.clear()
    session["user_id"] = record["user_id"]
    session["user_name"] = record["name"]
    session["user_email"] = email
    session["user_scholar_no"] = record["scholar_no"]
    session["user_role"] = "student"
    session["user_dept"] = record["department"]

    del PENDING_PASSWORD_RESETS[email]

    return jsonify({
        "success": True,
        "message": f"Password updated! Welcome back, {record['name']}.",
        "user": {
            "name": record["name"],
            "email": email,
            "scholar_no": record["scholar_no"],
            "role": "student",
            "dept": record["department"]
        }
    })

# --- GENERAL AUTHENTICATION ---

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True, silent=True) or {}
    identifier = data.get("identifier", "").strip()
    password = data.get("password", "").strip()
    login_type = data.get("type", "student")

    if not identifier or not password:
        return jsonify({"success": False, "message": "Credentials are required."}), 400

    if login_type == "admin":
        if identifier.lower() == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session.clear()
            session["user_id"] = 1
            session["user_name"] = "College Administrator"
            session["user_email"] = ADMIN_EMAIL
            session["user_scholar_no"] = None
            session["user_role"] = "admin"
            session["user_dept"] = "Campus Administration"
            return jsonify({
                "success": True,
                "user": {
                    "name": "College Administrator",
                    "email": ADMIN_EMAIL,
                    "scholar_no": None,
                    "role": "admin",
                    "dept": "Campus Administration"
                }
            })
        return jsonify({"success": False, "message": "Invalid College Administrator credentials."}), 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM users 
        WHERE (LOWER(email) = LOWER(?) OR scholar_no = ?) 
          AND password = ? AND role = 'student'
    ''', (identifier, identifier, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["user_scholar_no"] = user["scholar_no"]
        session["user_role"] = "student"
        session["user_dept"] = user["department"]
        return jsonify({
            "success": True,
            "user": {
                "name": user["name"],
                "email": user["email"],
                "scholar_no": user["scholar_no"],
                "role": "student",
                "dept": user["department"]
            }
        })
    return jsonify({"success": False, "message": "Invalid Scholar Number/Email or Password."}), 401

@app.route("/api/auth/session")
def auth_session():
    if "user_id" in session:
        return jsonify({
            "logged_in": True,
            "user": {
                "name": session.get("user_name"),
                "email": session.get("user_email"),
                "scholar_no": session.get("user_scholar_no"),
                "role": session.get("user_role"),
                "dept": session.get("user_dept")
            }
        })
    return jsonify({"logged_in": False})

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"success": True})

# --- COMPLAINTS, DELETE & FEEDBACK ---

@app.route("/api/register", methods=["POST"])
def register():
    if "user_id" not in session or session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Please log in as a student to file a complaint."}), 401

    bld = request.form.get("building", "").strip()
    room = request.form.get("room", "").strip()
    cat = request.form.get("category", "").strip()
    pri = request.form.get("priority", "").strip()
    prob = request.form.get("problem", "").strip()

    if not prob or not bld or not room:
        return jsonify({"success": False, "message": "Campus Location, Room No., and Problem description are required."}), 400

    image_filename = None
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename != "" and allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            unique_name = f"{session.get('user_scholar_no', 'STU')}_{int(datetime.now().timestamp())}.{ext}"
            saved_name = secure_filename(unique_name)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], saved_name))
            image_filename = saved_name

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM complaints ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    next_num = 1 if row is None else row["id"] + 1
    cmp_id = f"CMP{next_num:03d}"
    today = datetime.now().strftime("%Y-%m-%d")

    student_name = session.get("user_name", "")
    student_email = session.get("user_email", "")

    try:
        cursor.execute('''
            INSERT INTO complaints (
                complaint_id,
                student_scholar_no,
                student_name,
                student_email,
                department,
                building,
                room_no,
                category,
                problem,
                priority,
                status,
                image_path,
                date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
        ''', (
            cmp_id,
            session.get("user_scholar_no", ""),
            student_name,
            student_email,
            session.get("user_dept", ""),
            bld,
            room,
            cat,
            prob,
            pri,
            image_filename,
            today
        ))
        conn.commit()
        conn.close()

        email_body = f"""
        Hello <b>{student_name}</b>,<br><br>
        Your maintenance complaint has been successfully registered in the campus support queue.
        <br><br>
        <b>Ticket Details:</b><br>
        • <b>Ticket ID:</b> <span style="color:#f87171; font-weight:bold;">{cmp_id}</span><br>
        • <b>Location:</b> {bld} (Room: {room})<br>
        • <b>Category:</b> {cat}<br>
        • <b>Priority:</b> {pri}<br>
        • <b>Description:</b> "{prob}"<br>
        • <b>Status:</b> <span style="color:#F59E0B; font-weight:bold;">Pending</span><br><br>
        Our maintenance team will inspect and resolve this issue promptly.
        """
        send_email_notification(
            target_email=student_email,
            subject=f"Complaint Registered - [{cmp_id}]",
            heading="Complaint Successfully Raised",
            body_text=email_body
        )

        return jsonify({"success": True, "complaint_id": cmp_id})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

@app.route("/api/tickets")
def get_tickets():
    if "user_id" not in session:
        return jsonify([])

    conn = get_db()
    cursor = conn.cursor()
    if session.get("user_role") == "admin":
        cursor.execute("SELECT * FROM complaints ORDER BY id DESC")
    else:
        cursor.execute("SELECT * FROM complaints WHERE student_scholar_no = ? ORDER BY id DESC", (session.get("user_scholar_no", ""),))
    
    tickets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(tickets)

@app.route("/api/update_status", methods=["POST"])
def update_status():
    if session.get("user_role") != "admin":
        return jsonify({"success": False, "message": "Unauthorized. Administrator rights required."}), 403

    data = request.get_json(force=True, silent=True) or {}
    cmp_id = data.get("complaint_id")
    new_stat = data.get("status")

    if not cmp_id or not new_stat:
        return jsonify({"success": False, "message": "Ticket ID and status are required."}), 400

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM complaints WHERE complaint_id = ?", (cmp_id,))
    ticket = cursor.fetchone()

    if not ticket:
        conn.close()
        return jsonify({"success": False, "message": "Ticket not found."}), 404

    cursor.execute("UPDATE complaints SET status = ? WHERE complaint_id = ?", (new_stat, cmp_id))
    conn.commit()
    conn.close()

    student_email = ticket["student_email"]
    student_name = ticket["student_name"]

    if new_stat == "Resolved":
        status_subject = f"Complaint Resolved - [{cmp_id}]"
        status_heading = "Your Campus Complaint Has Been Solved"
        status_color = "#34D399"
        resolution_msg = "Our campus maintenance team has inspected the area, completed repairs, and marked your ticket as <b>Resolved</b>."
    else:
        status_subject = f"Ticket Status Updated - [{cmp_id}]"
        status_heading = f"Ticket Status Changed to: {new_stat}"
        status_color = "#93c5fd"
        resolution_msg = "Our maintenance team is currently processing your reported breakdown."

    status_body = f"""
    Hello <b>{student_name}</b>,<br><br>
    {resolution_msg}
    <br><br>
    <b>Complaint Summary:</b><br>
    • <b>Ticket ID:</b> <span style="color:#f87171; font-weight:bold;">{cmp_id}</span><br>
    • <b>Location:</b> {ticket['building']} (Room: {ticket['room_no']})<br>
    • <b>Category:</b> {ticket['category']}<br>
    • <b>Issue:</b> "{ticket['problem']}"<br>
    • <b>New Status:</b> <span style="color:{status_color}; font-weight:bold;">{new_stat}</span><br><br>
    Please log in to your dashboard to rate the service received.
    """

    send_email_notification(
        target_email=student_email,
        subject=status_subject,
        heading=status_heading,
        body_text=status_body
    )

    return jsonify({"success": True})

@app.route("/api/delete_ticket/<cmp_id>", methods=["DELETE"])
def delete_ticket(cmp_id):
    if session.get("user_role") != "admin":
        return jsonify({"success": False, "message": "Unauthorized. Administrator rights required."}), 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT image_path FROM complaints WHERE complaint_id = ?", (cmp_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Ticket not found."}), 404

    if row["image_path"]:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], row["image_path"])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"[CLEANUP WARNING] Could not remove file {file_path}: {e}")

    cursor.execute("DELETE FROM complaints WHERE complaint_id = ?", (cmp_id,))
    cursor.execute("DELETE FROM maintenance WHERE complaint_id = ?", (cmp_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Ticket {cmp_id} deleted successfully."})

@app.route("/api/submit_feedback", methods=["POST"])
def submit_feedback():
    if "user_id" not in session or session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Unauthorized. Please log in."}), 401

    data = request.get_json(force=True, silent=True) or {}
    cmp_id = data.get("complaint_id")
    rating = data.get("rating")
    feedback = data.get("feedback", "").strip()

    if not cmp_id or not rating:
        return jsonify({"success": False, "message": "Ticket ID and Star Rating are required."}), 400

    try:
        rating = int(rating)
        if not (1 <= rating <= 5):
            return jsonify({"success": False, "message": "Rating must be between 1 and 5 stars."}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Invalid rating format."}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM complaints WHERE complaint_id = ? AND student_scholar_no = ?", 
                   (cmp_id, session.get("user_scholar_no")))
    ticket = cursor.fetchone()

    if not ticket:
        conn.close()
        return jsonify({"success": False, "message": "Ticket not found or unauthorized."}), 404

    if ticket["status"] != "Resolved":
        conn.close()
        return jsonify({"success": False, "message": "Feedback can only be provided on resolved tickets."}), 400

    cursor.execute("UPDATE complaints SET rating = ?, feedback = ? WHERE complaint_id = ?", 
                   (rating, feedback, cmp_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Thank you! Your feedback has been recorded."})

@app.route("/api/analytics")
def get_analytics():
    if session.get("user_role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    conn = sqlite3.connect(DB_PATH)
    df_c = pd.read_sql_query("SELECT * FROM complaints", conn)
    conn.close()

    total = len(df_c)
    pending = int((df_c["status"] == "Pending").sum()) if total > 0 else 0
    in_prog = int((df_c["status"] == "In Progress").sum()) if total > 0 else 0
    resolved = int((df_c["status"] == "Resolved").sum()) if total > 0 else 0

    top_cat = df_c["category"].mode()[0] if not df_c.empty else "None"
    top_bld = df_c["building"].mode()[0] if not df_c.empty else "None"

    cat_counts = df_c["category"].value_counts().to_dict() if not df_c.empty else {}
    bld_counts = df_c["building"].value_counts().to_dict() if not df_c.empty else {}

    if not df_c.empty and "rating" in df_c.columns:
        rated_entries = df_c["rating"].dropna()
        avg_rating = round(float(rated_entries.mean()), 1) if rated_entries.count() > 0 else "N/A"
    else:
        avg_rating = "N/A"

    if not df_c.empty:
        df_c["month"] = pd.to_datetime(df_c["date"]).dt.strftime("%Y-%m")
        month_counts = df_c["month"].value_counts().sort_index().to_dict()
    else:
        month_counts = {}

    return jsonify({
        "metrics": {
            "total": total, 
            "pending": pending, 
            "in_progress": in_prog, 
            "resolved": resolved,
            "top_category": top_cat, 
            "top_building": top_bld,
            "avg_rating": f"{avg_rating} ★" if avg_rating != "N/A" else "N/A"
        },
        "charts": {
            "categories": cat_counts,
            "buildings": bld_counts,
            "months": month_counts,
            "status": {"Pending": pending, "In Progress": in_prog, "Resolved": resolved}
        }
    })

@app.route("/api/export_csv")
def export_csv():
    if session.get("user_role") != "admin":
        return "Unauthorized", 403

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM complaints", conn)
    conn.close()
    csv_data = df.to_csv(index=False)
    return Response(csv_data, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=Infrasync_Master_Records.csv"})

if __name__ == "__main__":
    print("\n" + "="*65)
    print(" INFRASYNC: CAMPUS SUPPORT & OPERATIONS HUB")
    print(f" COLLEGE ADMIN LOGIN:  {ADMIN_EMAIL}  |  PASSWORD: {ADMIN_PASSWORD}")
    print(" RUNNING AT:          http://127.0.0.1:5000")
    print("="*65 + "\n")
    app.run(debug=True, port=5000)