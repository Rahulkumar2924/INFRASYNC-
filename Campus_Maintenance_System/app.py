import os
import sqlite3
import random
import smtplib
import json
import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import (
    Flask, render_template, request,
    jsonify, session, send_file, send_from_directory, redirect, url_for
)
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "infrasync_production_secret_key_991")

# Environment configurations
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@campus.edu")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@2026")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "rahulkumarpandu7@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "oyan wbkv zkfs nerw")

# Use pooler URL if set, otherwise fallback to empty string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.xxouzdaavrtajpzlljjj:Campusfix2026@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
).strip()

# Adjust postgres URI prefix for psycopg2 compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Local fallback SQLite path
if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/campus.db"
    UPLOAD_FOLDER = "/tmp/uploads"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "campus.db")
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

IS_PG = bool(DATABASE_URL)

if IS_PG:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        IS_PG = False

def get_db():
    global IS_PG
    if IS_PG and DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=5)
            return conn, True
        except Exception as e:
            print(f"[DB Notice] PostgreSQL connection failed: {e}. Falling back to SQLite.")
            
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn, False

def init_db():
    try:
        conn, is_postgres = get_db()
        cursor = conn.cursor()
        if is_postgres:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    email VARCHAR(255) UNIQUE,
                    scholar_no VARCHAR(50) UNIQUE,
                    department VARCHAR(255),
                    password VARCHAR(255),
                    role VARCHAR(50) DEFAULT 'student',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS otps (
                    email VARCHAR(255) PRIMARY KEY,
                    otp VARCHAR(10),
                    payload TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    complaint_id VARCHAR(50) UNIQUE,
                    student_name VARCHAR(255),
                    student_scholar_no VARCHAR(50),
                    student_email VARCHAR(255),
                    department VARCHAR(255),
                    building VARCHAR(255),
                    room_no VARCHAR(50),
                    category VARCHAR(100),
                    priority VARCHAR(50),
                    problem TEXT,
                    image_path TEXT,
                    status VARCHAR(50) DEFAULT 'Pending',
                    rating INTEGER DEFAULT NULL,
                    feedback TEXT DEFAULT NULL,
                    date VARCHAR(50)
                );
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    email TEXT UNIQUE,
                    scholar_no TEXT UNIQUE,
                    department TEXT,
                    password TEXT,
                    role TEXT DEFAULT 'student',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS otps (
                    email TEXT PRIMARY KEY,
                    otp TEXT,
                    payload TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    complaint_id TEXT UNIQUE,
                    student_name TEXT,
                    student_scholar_no TEXT,
                    student_email TEXT,
                    department TEXT,
                    building TEXT,
                    room_no TEXT,
                    category TEXT,
                    priority TEXT,
                    problem TEXT,
                    image_path TEXT,
                    status TEXT DEFAULT 'Pending',
                    rating INTEGER DEFAULT NULL,
                    feedback TEXT DEFAULT NULL,
                    date TEXT
                )
            """)
        conn.commit()
        conn.close()
    except Exception as ex:
        print(f"[Init Error] DB Schema init failed: {ex}")

init_db()

def send_email_notification(to_email, subject, body_text):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = f"InfraSync Campus Operations <{SENDER_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=8)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Error: {e}")
        return False

# --- Core Web Routes ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    return redirect(url_for("index"))

@app.route("/signup")
def signup():
    return redirect(url_for("index"))

@app.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# --- Authentication APIs ---

@app.route("/api/auth/session")
def auth_session():
    if "user" in session:
        return jsonify({"logged_in": True, "user": session["user"]})
    return jsonify({"logged_in": False})

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json() or {}
    identifier = data.get("identifier", "").strip()
    password = data.get("password", "")
    login_type = data.get("type", "student")

    if login_type == "admin":
        if identifier.lower() == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            user_data = {
                "name": "Central Campus Admin",
                "email": ADMIN_EMAIL,
                "scholar_no": "ADMIN",
                "department": "Campus Administration",
                "role": "admin"
            }
            session["user"] = user_data
            return jsonify({"success": True, "user": user_data})
        return jsonify({"success": False, "message": "Invalid Administrator credentials."})

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"""
        SELECT * FROM users 
        WHERE (scholar_no = {ph} OR lower(email) = lower({ph})) AND password = {ph}
    """, (identifier, identifier, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        user_data = {
            "name": user["name"],
            "email": user["email"],
            "scholar_no": user["scholar_no"],
            "department": user["department"],
            "role": user["role"]
        }
        session["user"] = user_data
        return jsonify({"success": True, "user": user_data})
    
    return jsonify({"success": False, "message": "Invalid Scholar Number / Email or password."})

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"success": True})

# --- Student Registration (OTP) ---

@app.route("/api/auth/send-registration-otp", methods=["POST"])
def send_registration_otp():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    scholar = data.get("scholar_no", "").strip()

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"SELECT id FROM users WHERE lower(email) = {ph} OR scholar_no = {ph}", (email, scholar))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return jsonify({"success": False, "message": "An account with this email or Scholar Number already exists."})

    otp = str(random.randint(100000, 999999))
    payload_str = json.dumps(data)

    if is_pg:
        cursor.execute("""
            INSERT INTO otps (email, otp, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET otp = EXCLUDED.otp, payload = EXCLUDED.payload;
        """, (email, otp, payload_str))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO otps (email, otp, payload)
            VALUES (?, ?, ?)
        """, (email, otp, payload_str))

    conn.commit()
    conn.close()

    body = f"""Hello {data.get('name', 'Student')},

Your verification code for InfraSync Campus Hub registration is:

{otp}

This code expires in 10 minutes.

Campus Support & Operations Hub"""

    sent = send_email_notification(email, "InfraSync Registration OTP", body)
    if not sent:
        return jsonify({"success": False, "message": "Failed to dispatch email. Check SMTP settings."})

    return jsonify({"success": True, "message": "Verification code dispatched to your email."})

@app.route("/api/auth/verify-registration-otp", methods=["POST"])
def verify_registration_otp():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    entered_otp = data.get("otp", "").strip()

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"SELECT otp, payload FROM otps WHERE lower(email) = {ph}", (email,))
    record = cursor.fetchone()

    if not record or str(record["otp"]).strip() != entered_otp:
        conn.close()
        return jsonify({"success": False, "message": "Invalid or expired OTP code."})

    p = json.loads(record["payload"])

    try:
        cursor.execute(f"""
            INSERT INTO users (name, email, scholar_no, department, password, role)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, 'student')
        """, (p["name"], p["email"], p["scholar_no"], p["department"], p["password"]))
        cursor.execute(f"DELETE FROM otps WHERE lower(email) = {ph}", (email,))
        conn.commit()
    except Exception:
        conn.close()
        return jsonify({"success": False, "message": "Account already registered."})

    conn.close()

    user_data = {
        "name": p["name"],
        "email": p["email"],
        "scholar_no": p["scholar_no"],
        "department": p["department"],
        "role": "student"
    }
    session["user"] = user_data
    return jsonify({"success": True, "message": "Account verified and registered successfully!", "user": user_data})

# --- Forgot Password Reset ---

@app.route("/api/auth/forgot-password-otp", methods=["POST"])
def forgot_password_otp():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    scholar = data.get("scholar_no", "").strip()

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"SELECT id FROM users WHERE lower(email) = {ph} AND scholar_no = {ph}", (email, scholar))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"success": False, "message": "No student record matched those credentials."})

    otp = str(random.randint(100000, 999999))
    if is_pg:
        cursor.execute("""
            INSERT INTO otps (email, otp, payload)
            VALUES (%s, %s, 'RESET')
            ON CONFLICT (email) DO UPDATE SET otp = EXCLUDED.otp, payload = 'RESET';
        """, (email, otp))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO otps (email, otp, payload)
            VALUES (?, ?, 'RESET')
        """, (email, otp))
    conn.commit()
    conn.close()

    body = f"""Hello,

Your password reset verification code for InfraSync is:

{otp}

This code will expire in 10 minutes.

Campus Support & Operations Hub"""

    sent = send_email_notification(email, "InfraSync Password Reset OTP", body)
    if not sent:
        return jsonify({"success": False, "message": "Failed to dispatch reset OTP."})

    return jsonify({"success": True, "message": "Reset code sent to your registered email address."})

@app.route("/api/auth/verify-reset-password", methods=["POST"])
def verify_reset_password():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    entered_otp = data.get("otp", "").strip()
    new_pwd = data.get("new_password", "")

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"SELECT otp FROM otps WHERE lower(email) = {ph}", (email,))
    record = cursor.fetchone()

    if not record or str(record["otp"]).strip() != entered_otp:
        conn.close()
        return jsonify({"success": False, "message": "Invalid or expired OTP code."})

    cursor.execute(f"UPDATE users SET password = {ph} WHERE lower(email) = {ph}", (new_pwd, email))
    cursor.execute(f"DELETE FROM otps WHERE lower(email) = {ph}", (email,))
    cursor.execute(f"SELECT * FROM users WHERE lower(email) = {ph}", (email,))
    user = cursor.fetchone()
    conn.commit()
    conn.close()

    user_data = {
        "name": user["name"],
        "email": user["email"],
        "scholar_no": user["scholar_no"],
        "department": user["department"],
        "role": user["role"]
    }
    session["user"] = user_data
    return jsonify({"success": True, "message": "Password updated successfully!", "user": user_data})

# --- Ticket Operations (Sequential CMP Numbers & Base64 Images) ---

@app.route("/api/register", methods=["POST"])
def register_complaint():
    if "user" not in session:
        return jsonify({"success": False, "message": "You must be logged in to file a complaint."})

    u = session["user"]
    building = request.form.get("building")
    room = request.form.get("room", "")
    category = request.form.get("category")
    priority = request.form.get("priority")
    problem = request.form.get("problem")

    image_file = request.files.get("image")
    image_data_uri = ""
    if image_file and image_file.filename:
        file_bytes = image_file.read()
        if file_bytes:
            b64_encoded = base64.b64encode(file_bytes).decode("utf-8")
            mime_type = image_file.mimetype or "image/jpeg"
            image_data_uri = f"data:{mime_type};base64,{b64_encoded}"

    conn, is_pg = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT complaint_id FROM tickets WHERE complaint_id LIKE 'CMP%' ORDER BY id DESC LIMIT 1")
    last_row = cursor.fetchone()

    next_num = 1
    if last_row and last_row["complaint_id"]:
        try:
            raw_id = str(last_row["complaint_id"]).replace("CMP", "")
            next_num = int(raw_id) + 1
        except ValueError:
            cursor.execute("SELECT COUNT(*) as cnt FROM tickets")
            next_num = cursor.fetchone()["cnt"] + 1

    complaint_id = f"CMP{next_num:03d}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    ph = "%s" if is_pg else "?"
    cursor.execute(f"""
        INSERT INTO tickets (
            complaint_id, student_name, student_scholar_no, student_email,
            department, building, room_no, category, priority,
            problem, image_path, status, date
        ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'Pending', {ph})
    """, (
        complaint_id, u["name"], u["scholar_no"], u["email"],
        u["department"], building, room, category, priority,
        problem, image_data_uri, now_str
    ))
    conn.commit()
    conn.close()

    confirm_body = f"""Dear {u['name']},

Your maintenance incident report has been registered successfully.

Ticket ID: {complaint_id}
Location: {building} - Room {room}
Category: {category}
Priority: {priority}
Current Status: Pending

Campus Support & Operations Hub"""
    send_email_notification(u["email"], f"Complaint Logged: {complaint_id}", confirm_body)

    return jsonify({"success": True, "complaint_id": complaint_id})

@app.route("/api/tickets")
def get_tickets():
    if "user" not in session:
        return jsonify([])

    conn, is_pg = get_db()
    cursor = conn.cursor()
    u = session["user"]
    ph = "%s" if is_pg else "?"

    if u.get("role") == "admin":
        cursor.execute("SELECT * FROM tickets ORDER BY id DESC")
    else:
        cursor.execute(f"SELECT * FROM tickets WHERE student_scholar_no = {ph} ORDER BY id DESC", (u["scholar_no"],))

    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route("/api/update_status", methods=["POST"])
def update_status():
    if "user" not in session or session["user"].get("role") != "admin":
        return jsonify({"success": False, "message": "Admin authorization required."})

    data = request.get_json() or {}
    cmp_id = data.get("complaint_id")
    status = data.get("status")

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"SELECT * FROM tickets WHERE complaint_id = {ph}", (cmp_id,))
    ticket = cursor.fetchone()

    if not ticket:
        conn.close()
        return jsonify({"success": False, "message": "Ticket not found."})

    cursor.execute(f"UPDATE tickets SET status = {ph} WHERE complaint_id = {ph}", (status, cmp_id))
    conn.commit()
    conn.close()

    update_body = f"""Dear {ticket['student_name']},

The status of your maintenance request {cmp_id} has been updated to: {status}.

Location: {ticket['building']} (Room: {ticket['room_no']})
Category: {ticket['category']}

Campus Support & Operations Hub"""
    send_email_notification(ticket["student_email"], f"Ticket Update: {cmp_id} is now {status}", update_body)

    return jsonify({"success": True, "message": f"Ticket {cmp_id} updated."})

@app.route("/api/delete_ticket/<cmp_id>", methods=["DELETE"])
def delete_ticket(cmp_id):
    if "user" not in session or session["user"].get("role") != "admin":
        return jsonify({"success": False, "message": "Admin authorization required."})

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"DELETE FROM tickets WHERE complaint_id = {ph}", (cmp_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Ticket {cmp_id} deleted."})

@app.route("/api/submit_feedback", methods=["POST"])
def submit_feedback():
    if "user" not in session:
        return jsonify({"success": False, "message": "Login required."})

    data = request.get_json() or {}
    cmp_id = data.get("complaint_id")
    rating = data.get("rating")
    feedback = data.get("feedback", "")

    conn, is_pg = get_db()
    cursor = conn.cursor()
    ph = "%s" if is_pg else "?"
    cursor.execute(f"""
        UPDATE tickets SET rating = {ph}, feedback = {ph} 
        WHERE complaint_id = {ph} AND student_scholar_no = {ph}
    """, (rating, feedback, cmp_id, session["user"]["scholar_no"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Thank you for your rating!"})

# --- Central Analytics & Master Export ---

@app.route("/api/analytics")
def analytics():
    if "user" not in session or session["user"].get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403

    conn, is_pg = get_db()
    try:
        if is_pg:
            from sqlalchemy import create_engine
            engine = create_engine(DATABASE_URL)
            df = pd.read_sql_table("tickets", con=engine)
        else:
            df = pd.read_sql_query("SELECT * FROM tickets", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()

    if df.empty:
        return jsonify({
            "metrics": {
                "total": 0, "pending": 0, "in_progress": 0,
                "resolved": 0, "avg_rating": "N/A", "top_category": "None"
            },
            "charts": {
                "categories": {},
                "status": {"Pending": 0, "In Progress": 0, "Resolved": 0},
                "buildings": {},
                "months": {}
            }
        })

    total = len(df)
    pending = int((df["status"] == "Pending").sum())
    in_prog = int((df["status"] == "In Progress").sum())
    resolved = int((df["status"] == "Resolved").sum())

    rated_df = df[df["rating"].notnull()]
    avg_rating = f"{rated_df['rating'].mean():.1f} / 5" if not rated_df.empty else "N/A"
    top_cat = df["category"].mode()[0] if not df["category"].empty else "None"

    cat_counts = df["category"].value_counts().to_dict()
    bld_counts = df["building"].value_counts().to_dict()
    
    try:
        df["month"] = pd.to_datetime(df["date"]).dt.strftime("%b %Y")
        month_counts = df["month"].value_counts().to_dict()
    except Exception:
        month_counts = {}

    return jsonify({
        "metrics": {
            "total": total,
            "pending": pending,
            "in_progress": in_prog,
            "resolved": resolved,
            "avg_rating": avg_rating,
            "top_category": top_cat
        },
        "charts": {
            "categories": cat_counts,
            "status": {
                "Pending": pending,
                "In Progress": in_prog,
                "Resolved": resolved
            },
            "buildings": bld_counts,
            "months": month_counts
        }
    })

@app.route("/api/export_csv")
def export_csv():
    if "user" not in session or session["user"].get("role") != "admin":
        return "Admin access required", 403

    conn, is_pg = get_db()
    try:
        if is_pg:
            from sqlalchemy import create_engine
            engine = create_engine(DATABASE_URL)
            df = pd.read_sql_table("tickets", con=engine)
        else:
            df = pd.read_sql_query("SELECT * FROM tickets", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()

    csv_path = "/tmp/campus_tickets_master.csv" if os.environ.get("VERCEL") else "campus_tickets_master.csv"
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True, download_name="Campus_Maintenance_Report.csv")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
