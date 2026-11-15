"""
ServiceTrack - Maintenance Request Management System
CS 388T Project

Sprint 1: PB-01 to PB-06  (register/login, submit request, photos, status
          tracking, admin dashboard, assign technician)
Sprint 2: PB-07 to PB-13 and PB-17  (technician jobs and status updates,
          notifications, overdue monitoring, after-service photo,
          confirm/reopen, technician accounts, usability refinements)

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000
"""
import hmac
import os
import secrets
import sqlite3
import struct
import uuid
import zlib
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SERVICETRACK_DB", os.path.join(BASE_DIR, "servicetrack.db"))
UPLOAD_DIR = os.environ.get("SERVICETRACK_UPLOADS", os.path.join(BASE_DIR, "uploads"))

CATEGORIES = ["Plumbing", "Electrical", "A/C", "Carpentry", "General"]
STATUSES = ["Submitted", "Assigned", "In Progress", "Completed"]
OPEN_STATUSES = ("Submitted", "Assigned", "In Progress")
# PB-08: the only status changes a technician may make, in this order
TECH_NEXT_STATUS = {"Assigned": "In Progress", "In Progress": "Completed"}
ALLOWED_EXT = {"jpg", "jpeg", "png"}
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB per photo
# PB-10: an open request is overdue after this many hours (agreed in Sprint 2 planning)
OVERDUE_HOURS = int(os.environ.get("SERVICETRACK_OVERDUE_HOURS", "48"))
TIME_FMT = "%Y-%m-%d %H:%M"

app = Flask(__name__)
app.config["SECRET_KEY"] = (os.environ.get("SERVICETRACK_SECRET_KEY")
                            or os.environ.get("SECRET_KEY") or secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # whole form
app.config["CSRF_ENABLED"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.before_request
def check_csrf():
    if request.method == "POST" and app.config.get("CSRF_ENABLED", True):
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if (not isinstance(sent, str) or not isinstance(expected, str)
                or not sent or not expected
                or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))):
            abort(400, description="The form has expired. Refresh the page and try again.")


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    phone       TEXT,
    building    TEXT,
    unit        TEXT,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('customer','technician','admin')),
    specialty   TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES users(id),
    category       TEXT NOT NULL,
    description    TEXT NOT NULL,
    building       TEXT NOT NULL,
    floor          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'Submitted',
    technician_id  INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL,
    confirmed_at   TEXT,
    reopened_at    TEXT
);
CREATE TABLE IF NOT EXISTS photos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   INTEGER NOT NULL REFERENCES requests(id),
    filename     TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'problem',
    uploaded_by  INTEGER REFERENCES users(id),
    uploaded_at  TEXT
);
CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL REFERENCES requests(id),
    status      TEXT NOT NULL,
    changed_by  INTEGER REFERENCES users(id),
    note        TEXT,
    changed_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    request_id  INTEGER NOT NULL REFERENCES requests(id),
    message     TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""

# Columns added in Sprint 2. A database created by the Sprint 1 version is
# upgraded automatically the first time this version starts.
SPRINT2_COLUMNS = [
    ("users", "active", "INTEGER NOT NULL DEFAULT 1"),
    ("requests", "confirmed_at", "TEXT"),
    ("requests", "reopened_at", "TEXT"),
    ("photos", "kind", "TEXT NOT NULL DEFAULT 'problem'"),
    ("photos", "uploaded_by", "INTEGER"),
    ("photos", "uploaded_at", "TEXT"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now():
    return datetime.now().strftime(TIME_FMT)


def parse_time(value):
    """Read both the original minute timestamps and second-resolution timestamps."""
    return datetime.fromisoformat(value)


def init_db():
    """Create/upgrade tables and add the starting admin and technician accounts."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    for table, column, decl in SPRINT2_COLUMNS:
        existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        staff = [
            ("Building Admin", "admin@servicetrack.com", "admin123", "admin", None),
            ("Khalid Alomari", "khalid@servicetrack.com", "tech123", "technician", "Plumbing"),
            ("Fahad Alqahtani", "fahad@servicetrack.com", "tech123", "technician", "Electrical"),
            ("Saad Alharbi", "saad@servicetrack.com", "tech123", "technician", "A/C"),
            ("Majed Alzahrani", "majed@servicetrack.com", "tech123", "technician", "Carpentry"),
            ("Omar Alshehri", "omar@servicetrack.com", "tech123", "technician", "General"),
        ]
        for name, email, pw, role, spec in staff:
            db.execute(
                "INSERT INTO users (name,email,password,role,specialty,created_at) VALUES (?,?,?,?,?,?)",
                (name, email, generate_password_hash(pw), role, spec, now()))
    db.commit()
    db.close()


def request_number(req_id):
    return f"SR-{req_id:04d}"


# ---------------------------------------------------------------- PB-10 overdue rule
def overdue_since(req):
    """Time from which the overdue clock runs: creation, or the latest reopening."""
    return req["reopened_at"] or req["created_at"]


def is_overdue(req, at=None):
    """An open request is overdue when more than OVERDUE_HOURS have passed since
    it was created (or last reopened). Completed requests are never overdue."""
    if req["status"] not in OPEN_STATUSES:
        return False
    start = parse_time(overdue_since(req))
    return (at or datetime.now()) - start > timedelta(hours=OVERDUE_HOURS)


def hours_open(req):
    start = parse_time(overdue_since(req))
    return int((datetime.now() - start).total_seconds() // 3600)


app.jinja_env.globals.update(request_number=request_number, STATUSES=STATUSES,
                             is_overdue=is_overdue, hours_open=hours_open,
                             OVERDUE_HOURS=OVERDUE_HOURS)


# ---------------------------------------------------------------- auth helpers
def current_user():
    if "current_user" not in g:
        uid = session.get("user_id")
        g.current_user = None
        if uid is not None:
            g.current_user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return g.current_user


@app.context_processor
def inject_user():
    user = current_user()
    unread = 0
    if user is not None and user["role"] == "customer":
        unread = get_db().execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
    return {"user": user, "unread_count": unread, "csrf_token": csrf_token}


def login_required(*roles):
    """Allow the page only for logged-in, active users with one of the given roles."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in first.", "error")
                return redirect(url_for("login"))
            if not user["active"]:  # PB-13: a deactivated account is signed out
                session.clear()
                flash("Your account has been deactivated. Please contact the building administrator.", "error")
                return redirect(url_for("login"))
            if roles and user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def home_for(role):
    return {"customer": "customer_home", "admin": "admin_dashboard",
            "technician": "technician_home"}[role]


def add_history(db, req_id, status, note):
    db.execute(
        "INSERT INTO status_history (request_id,status,changed_by,note,changed_at) VALUES (?,?,?,?,?)",
        (req_id, status, session.get("user_id"), note, now()))


def notify_customer(db, req, message):
    """PB-09: in-app notification for the owner of the request."""
    db.execute(
        "INSERT INTO notifications (user_id,request_id,message,created_at) VALUES (?,?,?,?)",
        (req["customer_id"], req["id"], message, now()))


def valid_png(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    pos, header, image_data = 8, False, False
    while pos + 12 <= len(data):
        length = struct.unpack('>I',data[pos:pos+4])[0]
        if pos + 12 + length > len(data):
            return False
        kind, payload = data[pos+4:pos+8], data[pos+8:pos+8+length]
        crc = struct.unpack('>I',data[pos+8+length:pos+12+length])[0]
        if (zlib.crc32(kind+payload) & 0xffffffff) != crc:
            return False
        if not header:
            if kind != b'IHDR' or length != 13:
                return False
            width,height = struct.unpack('>II',payload[:8])
            if width < 1 or height < 1:
                return False
            header = True
        if kind == b'IDAT':
            image_data = True
        pos += length + 12
        if kind == b'IEND':
            return length == 0 and header and image_data and pos == len(data)
    return False

def valid_jpeg(data):
    # Some phones and photo editors add extra data after the end-of-image marker
    # (for example Samsung motion photos), so the marker must exist but may not be last.
    if len(data) < 12 or not data.startswith(b'\xff\xd8') or b'\xff\xd9' not in data[2:]:
        return False
    pos, frame = 2, False
    frames = {0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf}
    while pos + 3 < len(data):
        if data[pos] != 0xff:
            return False
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            return False
        marker = data[pos]
        pos += 1
        if marker in {0xd8,0xd9} or 0xd0 <= marker <= 0xd7:
            continue
        if pos + 2 > len(data):
            return False
        length = int.from_bytes(data[pos:pos+2],'big')
        if length < 2 or pos + length > len(data):
            return False
        if marker in frames:
            if length < 8 or int.from_bytes(data[pos+3:pos+5],'big') < 1 or int.from_bytes(data[pos+5:pos+7],'big') < 1:
                return False
            frame = True
        if marker == 0xda:
            return frame and length >= 6
        pos += length
    return False

def read_photo_uploads(field):
    """Validate a nonempty JPG/PNG image, reading at most 5 MB plus one byte."""
    photos, errors = [], []
    for f in request.files.getlist(field):
        if not f or not f.filename:
            continue
        data = f.stream.read(MAX_PHOTO_SIZE + 1)
        if not allowed_photo(f.filename):
            errors.append(f'"{f.filename}" was not uploaded: only JPG and PNG photos are accepted. '
                          'Please choose a .jpg or .png file.')
        elif len(data) > MAX_PHOTO_SIZE:
            errors.append(f'"{f.filename}" was not uploaded: it is larger than 5 MB. '
                          'Please choose a smaller photo.')
        elif not data:
            errors.append(f'"{f.filename}" was not uploaded: the file is empty. Please choose the original photo.')
        else:
            ext = f.filename.rsplit(".", 1)[1].lower()
            if not (valid_png(data) if ext == "png" else valid_jpeg(data)):
                errors.append(f'"{f.filename}" was not uploaded: it is not a valid image. '
                              'Please choose the original JPG or PNG photo file.')
            else:
                photos.append((ext, data))
    return photos, errors


def save_photos(db, req_id, photos, kind):
    for ext, data in photos:
        name = f"{req_id}_{kind}_{uuid.uuid4().hex[:10]}.{ext}"
        with open(os.path.join(UPLOAD_DIR, name), "wb") as out:
            out.write(data)
        db.execute("INSERT INTO photos (request_id, filename, kind, uploaded_by, uploaded_at) "
                   "VALUES (?,?,?,?,?)", (req_id, name, kind, session.get("user_id"), now()))


def load_request(req_id):
    req = get_db().execute("SELECT * FROM requests WHERE id=?", (req_id,)).fetchone()
    if req is None:
        abort(404)
    return req


# ---------------------------------------------------------------- PB-01 register / login
@app.route("/")
def index():
    user = current_user()
    if user and user["active"]:
        return redirect(url_for(home_for(user["role"])))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("name", "email", "phone", "building", "unit", "password")}
        form["email"] = form["email"].lower()
        labels = {"name": "Full name", "email": "Email", "phone": "Phone", "building": "Building",
                  "unit": "Unit", "password": "Password"}
        missing = [labels[k] for k, v in form.items() if not v]
        db = get_db()
        if missing:
            flash("Please fill in: " + ", ".join(missing) + ".", "error")
        elif len(form["password"]) < 6:
            flash("Password is too short. Please use at least 6 characters.", "error")
        elif db.execute("SELECT 1 FROM users WHERE email=?", (form["email"],)).fetchone():
            flash("This email is already registered. Please log in, or register with another email.", "error")
        else:
            db.execute(
                "INSERT INTO users (name,email,phone,building,unit,password,role,created_at) "
                "VALUES (?,?,?,?,?,?, 'customer', ?)",
                (form["name"], form["email"], form["phone"], form["building"], form["unit"],
                 generate_password_hash(form["password"]), now()))
            db.commit()
            flash("Your account was created. Please log in with your email and password.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password"], password):
            flash("Incorrect email or password. Please check them and try again.", "error")
        elif not user["active"]:
            flash("This account has been deactivated. Please contact the building administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for(home_for(user["role"])))
    return render_template("login.html", email=email)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- PB-02 / PB-03 customer requests
@app.route("/customer")
@login_required("customer")
def customer_home():
    rows = get_db().execute(
        "SELECT r.*, t.name AS technician_name FROM requests r "
        "LEFT JOIN users t ON t.id = r.technician_id "
        "WHERE r.customer_id=? ORDER BY r.created_at DESC, r.id DESC",
        (session["user_id"],)).fetchall()
    return render_template("customer_home.html", requests=rows)


def allowed_photo(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/customer/new", methods=["GET", "POST"])
@login_required("customer")
def new_request():
    user = current_user()
    form = {"building": user["building"] or "", "unit": user["unit"] or ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("category", "description", "building", "floor", "unit")}
        labels = {"category": "Category", "description": "Description", "building": "Building",
                  "floor": "Floor", "unit": "Unit"}
        errors = []
        missing = [labels[k] for k, v in form.items() if not v]
        if missing:
            errors.append("Please fill in: " + ", ".join(missing) + ".")
        if form["category"] and form["category"] not in CATEGORIES:
            errors.append("Please choose a category from the list.")
        photos, photo_errors = read_photo_uploads("photos")
        errors += photo_errors

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            db = get_db()
            cur = db.execute(
                "INSERT INTO requests (customer_id,category,description,building,floor,unit,status,created_at) "
                "VALUES (?,?,?,?,?,?, 'Submitted', ?)",
                (user["id"], form["category"], form["description"], form["building"],
                 form["floor"], form["unit"], now()))
            req_id = cur.lastrowid
            save_photos(db, req_id, photos, "problem")
            add_history(db, req_id, "Submitted", "Request submitted by the customer")
            db.commit()
            flash(f"Your request {request_number(req_id)} was submitted. "
                  "You will be notified when a technician is assigned.", "success")
            return redirect(url_for("request_detail", req_id=req_id))
    return render_template("new_request.html", form=form, categories=CATEGORIES)


@app.route("/uploads/<path:filename>")
@login_required()
def uploaded_photo(filename):
    req = get_db().execute(
        "SELECT r.* FROM photos p JOIN requests r ON r.id=p.request_id WHERE p.filename=?",
        (filename,)).fetchone()
    if req is None:
        abort(404)
    user = current_user()
    if user["role"] == "customer" and req["customer_id"] != user["id"]:
        abort(403)
    if user["role"] == "technician" and req["technician_id"] != user["id"]:
        abort(403)
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------- PB-04 request details + status timeline
@app.route("/request/<int:req_id>")
@login_required()
def request_detail(req_id):
    db = get_db()
    user = current_user()
    req = db.execute(
        "SELECT r.*, c.name AS customer_name, c.phone AS customer_phone, t.name AS technician_name, "
        "t.specialty AS technician_specialty "
        "FROM requests r JOIN users c ON c.id = r.customer_id "
        "LEFT JOIN users t ON t.id = r.technician_id WHERE r.id=?", (req_id,)).fetchone()
    if req is None:
        abort(404)
    # each role only sees what it is allowed to see
    if user["role"] == "customer" and req["customer_id"] != user["id"]:
        abort(403)
    if user["role"] == "technician" and req["technician_id"] != user["id"]:
        abort(403)
    photos = db.execute("SELECT * FROM photos WHERE request_id=? ORDER BY id", (req_id,)).fetchall()
    history = db.execute(
        "SELECT h.*, u.name AS by_name FROM status_history h "
        "LEFT JOIN users u ON u.id = h.changed_by WHERE h.request_id=? ORDER BY h.id",
        (req_id,)).fetchall()
    reassign_options = []
    if user["role"] == "admin" and req["status"] in ("Assigned", "In Progress"):
        reassign_options = db.execute(
            "SELECT id, name, specialty FROM users WHERE role='technician' AND active=1 AND id != ? "
            "AND specialty=? ORDER BY name", (req["technician_id"] or 0, req["category"])).fetchall()
    return render_template(
        "request_detail.html", req=req, history=history,
        problem_photos=[p for p in photos if p["kind"] == "problem"],
        after_photos=[p for p in photos if p["kind"] == "after"],
        next_status=TECH_NEXT_STATUS.get(req["status"]),
        reassign_options=reassign_options)


# ---------------------------------------------------------------- PB-05 / PB-10 admin dashboard
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    sort = request.args.get("sort", "newest")
    overdue_only = request.args.get("overdue") == "1"

    sql = ("SELECT r.*, c.name AS customer_name, t.name AS technician_name FROM requests r "
           "JOIN users c ON c.id = r.customer_id LEFT JOIN users t ON t.id = r.technician_id WHERE 1=1")
    params = []
    if status in STATUSES:
        sql += " AND r.status=?"
        params.append(status)
    if category in CATEGORIES:
        sql += " AND r.category=?"
        params.append(category)
    sql += " ORDER BY r.created_at " + ("ASC, r.id ASC" if sort == "oldest" else "DESC, r.id DESC")

    db = get_db()
    rows = db.execute(sql, params).fetchall()
    if overdue_only:
        rows = [r for r in rows if is_overdue(r)]
    technicians = db.execute(
        "SELECT id, name, specialty FROM users WHERE role='technician' AND active=1 ORDER BY name").fetchall()
    counts = {s: db.execute("SELECT COUNT(*) FROM requests WHERE status=?", (s,)).fetchone()[0]
              for s in STATUSES}
    all_open = db.execute("SELECT * FROM requests WHERE status IN (?,?,?)", OPEN_STATUSES).fetchall()
    overdue_count = sum(1 for r in all_open if is_overdue(r))
    filtered = bool(status in STATUSES or category in CATEGORIES or overdue_only or sort == "oldest")
    return render_template("admin_dashboard.html", requests=rows, technicians=technicians,
                           counts=counts, overdue_count=overdue_count, categories=CATEGORIES,
                           f_status=status, f_category=category, f_sort=sort,
                           f_overdue=overdue_only, filtered=filtered)


# ---------------------------------------------------------------- PB-06 assign technician
@app.route("/admin/assign/<int:req_id>", methods=["POST"])
@login_required("admin")
def assign_technician(req_id):
    db = get_db()
    req = load_request(req_id)
    tech_id = request.form.get("technician_id", type=int)
    tech = db.execute("SELECT * FROM users WHERE id=? AND role='technician' AND active=1",
                      (tech_id,)).fetchone()
    if tech is None:
        flash(f"{request_number(req_id)} was not assigned: please choose an active technician from the list.",
              "error")
    elif tech["specialty"] != req["category"]:
        flash("Please choose an active technician whose specialty matches the request category.", "error")
    elif req["status"] != "Submitted":
        flash(f"{request_number(req_id)} is already {req['status']}; it cannot be assigned again.", "error")
    else:
        db.execute("UPDATE requests SET technician_id=?, status='Assigned' WHERE id=?", (tech_id, req_id))
        add_history(db, req_id, "Assigned", f"Assigned to {tech['name']} ({tech['specialty']})")
        notify_customer(db, req, f"{request_number(req_id)} was assigned to technician {tech['name']}.")
        db.commit()
        flash(f"Done: {request_number(req_id)} was assigned to {tech['name']} ({tech['specialty']}). "
              "Its status is now Assigned.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/reassign/<int:req_id>", methods=["POST"])
@login_required("admin")
def reassign_technician(req_id):
    """Move an open job to another active technician (needed before deactivating a technician, PB-13)."""
    db = get_db()
    req = load_request(req_id)
    tech_id = request.form.get("technician_id", type=int)
    tech = db.execute("SELECT * FROM users WHERE id=? AND role='technician' AND active=1",
                      (tech_id,)).fetchone()
    if req["status"] not in ("Assigned", "In Progress"):
        flash("Only Assigned or In Progress requests can be reassigned.", "error")
    elif tech is None or tech_id == req["technician_id"]:
        flash("Please choose a different, active technician.", "error")
    elif tech["specialty"] != req["category"]:
        flash("Please choose an active technician whose specialty matches the request category.", "error")
    else:
        db.execute("UPDATE requests SET technician_id=? WHERE id=?", (tech_id, req_id))
        add_history(db, req_id, req["status"], f"Reassigned to {tech['name']} ({tech['specialty']})")
        notify_customer(db, req, f"{request_number(req_id)} was reassigned to technician {tech['name']}.")
        db.commit()
        flash(f"Done: {request_number(req_id)} was reassigned to {tech['name']}.", "success")
    return redirect(url_for("request_detail", req_id=req_id))


# ---------------------------------------------------------------- PB-07 technician job list
@app.route("/technician")
@login_required("technician")
def technician_home():
    show = request.args.get("show", "open")
    sql = ("SELECT r.*, c.name AS customer_name, "
           "(SELECT COUNT(*) FROM photos p WHERE p.request_id=r.id AND p.kind='problem') AS photo_count, "
           "(SELECT filename FROM photos p WHERE p.request_id=r.id AND p.kind='problem' ORDER BY p.id LIMIT 1) "
           "AS first_photo "
           "FROM requests r JOIN users c ON c.id = r.customer_id WHERE r.technician_id=?")
    if show != "all":
        sql += " AND r.status != 'Completed'"
    sql += " ORDER BY r.created_at DESC, r.id DESC"
    rows = get_db().execute(sql, (session["user_id"],)).fetchall()
    return render_template("technician_home.html", requests=rows, show=show)


# ---------------------------------------------------------------- PB-08 / PB-11 technician updates
@app.route("/technician/update/<int:req_id>", methods=["POST"])
@login_required("technician")
def update_status(req_id):
    db = get_db()
    req = load_request(req_id)
    if req["technician_id"] != session["user_id"]:
        abort(403)
    new_status = request.form.get("status", "")
    note = request.form.get("note", "").strip()
    allowed = TECH_NEXT_STATUS.get(req["status"])
    if allowed is None or new_status != allowed:
        flash(f"Status cannot change from {req['status']} to {new_status or 'nothing'}. "
              "Statuses must follow the order Assigned → In Progress → Completed.", "error")
        return redirect(url_for("request_detail", req_id=req_id))
    photos, errors = read_photo_uploads("after_photos") if new_status == "Completed" else ([], [])
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("request_detail", req_id=req_id))
    db.execute("UPDATE requests SET status=? WHERE id=?", (new_status, req_id))
    add_history(db, req_id, new_status, note or None)
    save_photos(db, req_id, photos, "after")
    msg = f"{request_number(req_id)} is now {new_status}."
    if new_status == "Completed":
        msg += " Please confirm the fix or reopen the request if the problem is still there."
    notify_customer(db, req, msg)
    db.commit()
    flash(f"Done: {request_number(req_id)} is now {new_status}.", "success")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/technician/after-photo/<int:req_id>", methods=["POST"])
@login_required("technician")
def add_after_photo(req_id):
    db = get_db()
    req = load_request(req_id)
    if req["technician_id"] != session["user_id"]:
        abort(403)
    if req["status"] not in ("In Progress", "Completed"):
        flash("After-service photos can be added once the job is In Progress or Completed.", "error")
        return redirect(url_for("request_detail", req_id=req_id))
    photos, errors = read_photo_uploads("after_photos")
    if not photos and not errors:
        errors.append("Please choose a photo to upload.")
    if errors:
        for e in errors:
            flash(e, "error")
    else:
        save_photos(db, req_id, photos, "after")
        db.commit()
        flash(f"Done: after-service photo added to {request_number(req_id)}.", "success")
    return redirect(url_for("request_detail", req_id=req_id))


# ---------------------------------------------------------------- PB-12 confirm / reopen
@app.route("/customer/decision/<int:req_id>", methods=["POST"])
@login_required("customer")
def customer_decision(req_id):
    db = get_db()
    req = load_request(req_id)
    if req["customer_id"] != session["user_id"]:
        abort(403)
    if req["status"] != "Completed" or req["confirmed_at"]:
        flash("Only a completed request that has not been confirmed yet can be confirmed or reopened.", "error")
        return redirect(url_for("request_detail", req_id=req_id))
    decision = request.form.get("decision")
    if decision == "confirm":
        db.execute("UPDATE requests SET confirmed_at=? WHERE id=?", (now(), req_id))
        add_history(db, req_id, "Completed", "Customer confirmed that the problem was fixed")
        db.commit()
        flash(f"Thank you. {request_number(req_id)} is confirmed and closed.", "success")
    elif decision == "reopen":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Please write the reason for reopening, so the technician knows what is still wrong.", "error")
            return redirect(url_for("request_detail", req_id=req_id))
        db.execute("UPDATE requests SET status='In Progress', reopened_at=? WHERE id=?", (now(), req_id))
        add_history(db, req_id, "In Progress", f"Reopened by the customer: {reason}")
        notify_customer(db, req, f"{request_number(req_id)} was reopened and is In Progress again.")
        db.commit()
        flash(f"{request_number(req_id)} was reopened and sent back to the same technician.", "success")
    else:
        flash("Please choose Confirm or Reopen.", "error")
    return redirect(url_for("request_detail", req_id=req_id))


# ---------------------------------------------------------------- PB-09 notifications
@app.route("/notifications")
@login_required("customer")
def notifications():
    rows = get_db().execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY is_read ASC, id DESC",
        (session["user_id"],)).fetchall()
    return render_template("notifications.html", notifications=rows)


@app.route("/notifications/<int:note_id>/open")
@login_required("customer")
def open_notification(note_id):
    db = get_db()
    note = db.execute("SELECT * FROM notifications WHERE id=?", (note_id,)).fetchone()
    if note is None or note["user_id"] != session["user_id"]:
        abort(404)
    db.execute("UPDATE notifications SET is_read=1 WHERE id=?", (note_id,))
    db.commit()
    return redirect(url_for("request_detail", req_id=note["request_id"]))


@app.route("/notifications/read-all", methods=["POST"])
@login_required("customer")
def read_all_notifications():
    db = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    db.commit()
    flash("All notifications were marked as read.", "success")
    return redirect(url_for("notifications"))


# ---------------------------------------------------------------- PB-13 technician accounts
def technician_form():
    return {k: request.form.get(k, "").strip() for k in ("name", "email", "phone", "specialty", "password")}


@app.route("/admin/technicians")
@login_required("admin")
def technicians():
    rows = get_db().execute(
        "SELECT u.*, (SELECT COUNT(*) FROM requests r WHERE r.technician_id=u.id "
        "AND r.status IN ('Assigned','In Progress')) AS open_jobs "
        "FROM users u WHERE role='technician' ORDER BY active DESC, name").fetchall()
    return render_template("technicians.html", technicians=rows)


@app.route("/admin/technicians/new", methods=["GET", "POST"])
@login_required("admin")
def new_technician():
    form = {}
    if request.method == "POST":
        form = technician_form()
        form["email"] = form["email"].lower()
        db = get_db()
        error = validate_technician(form, db, require_password=True)
        if error:
            flash(error, "error")
        else:
            db.execute("INSERT INTO users (name,email,phone,password,role,specialty,created_at) "
                       "VALUES (?,?,?,?, 'technician', ?, ?)",
                       (form["name"], form["email"], form["phone"],
                        generate_password_hash(form["password"]), form["specialty"], now()))
            db.commit()
            flash(f"Done: technician account for {form['name']} ({form['specialty']}) was created.", "success")
            return redirect(url_for("technicians"))
    return render_template("technician_form.html", form=form, categories=CATEGORIES, editing=None)


def validate_technician(form, db, require_password, editing_id=None):
    missing = [lbl for k, lbl in (("name", "Full name"), ("email", "Email"), ("specialty", "Specialty"))
               if not form[k]]
    if require_password and not form["password"]:
        missing.append("Password")
    if missing:
        return "Please fill in: " + ", ".join(missing) + "."
    if form["specialty"] not in CATEGORIES:
        return "Please choose a specialty from the list."
    if form["password"] and len(form["password"]) < 6:
        return "Password is too short. Please use at least 6 characters."
    dup = db.execute("SELECT id FROM users WHERE email=? AND id != ?", (form["email"], editing_id or 0)).fetchone()
    if dup:
        return "This email is already used by another account. Please use a different email."
    return None


@app.route("/admin/technicians/<int:tech_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def edit_technician(tech_id):
    db = get_db()
    tech = db.execute("SELECT * FROM users WHERE id=? AND role='technician'", (tech_id,)).fetchone()
    if tech is None:
        abort(404)
    form = dict(tech)
    form["password"] = ""
    if request.method == "POST":
        form = technician_form()
        form["email"] = form["email"].lower()
        error = validate_technician(form, db, require_password=False, editing_id=tech_id)
        if (not error and form["specialty"] != tech["specialty"]
                and db.execute("SELECT 1 FROM requests WHERE technician_id=? "
                               "AND status IN ('Assigned','In Progress') LIMIT 1", (tech_id,)).fetchone()):
            error = "Please reassign this technician's open jobs before changing the specialty."
        if error:
            flash(error, "error")
        else:
            db.execute("UPDATE users SET name=?, email=?, phone=?, specialty=? WHERE id=?",
                       (form["name"], form["email"], form["phone"], form["specialty"], tech_id))
            if form["password"]:
                db.execute("UPDATE users SET password=? WHERE id=?",
                           (generate_password_hash(form["password"]), tech_id))
            db.commit()
            flash(f"Done: {form['name']}'s account was updated.", "success")
            return redirect(url_for("technicians"))
    return render_template("technician_form.html", form=form, categories=CATEGORIES, editing=tech)


@app.route("/admin/technicians/<int:tech_id>/active", methods=["POST"])
@login_required("admin")
def set_technician_active(tech_id):
    db = get_db()
    tech = db.execute("SELECT * FROM users WHERE id=? AND role='technician'", (tech_id,)).fetchone()
    if tech is None:
        abort(404)
    make_active = request.form.get("active") == "1"
    if not make_active:
        open_jobs = db.execute(
            "SELECT id FROM requests WHERE technician_id=? AND status IN ('Assigned','In Progress')",
            (tech_id,)).fetchall()
        if open_jobs:
            nums = ", ".join(request_number(r["id"]) for r in open_jobs)
            flash(f"{tech['name']} cannot be deactivated yet: please reassign the open job(s) {nums} first.",
                  "error")
            return redirect(url_for("technicians"))
    db.execute("UPDATE users SET active=? WHERE id=?", (1 if make_active else 0, tech_id))
    db.commit()
    flash(f"Done: {tech['name']} was {'reactivated' if make_active else 'deactivated'}.", "success")
    return redirect(url_for("technicians"))


# ---------------------------------------------------------------- errors
@app.errorhandler(400)
def bad_request(error):
    return render_template("message.html", title="Please try again", text=error.description), 400


@app.errorhandler(403)
def forbidden(_e):
    return render_template("message.html", title="Access denied",
                           text="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Not found",
                           text="The page or request you are looking for does not exist."), 404


@app.errorhandler(413)
def too_large(_e):
    flash("The uploaded files are too large. Each photo must be 5 MB or less.", "error")
    return redirect(request.url)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
