"""
Fill ServiceTrack with demo data for the Sprint Review / project discussion.

    python seed_demo.py          # only works on an empty system
    python seed_demo.py --reset  # deletes servicetrack.db and uploads first

Demo accounts created (in addition to the admin and technicians in README.md):
    sara@demo.com  / demo123   (customer)
    noura@demo.com / demo123   (customer)

The data goes through the real application routes, so status history and
notifications are created exactly as they would be by real users. Two requests
are then dated back so that the overdue flag (PB-10) can be demonstrated.
"""
import glob
import os
import sqlite3
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS = os.path.join(BASE_DIR, "demo_photos")

if "--reset" in sys.argv:
    db_file = os.environ.get("SERVICETRACK_DB", os.path.join(BASE_DIR, "servicetrack.db"))
    if os.path.exists(db_file):
        os.remove(db_file)
    for f in glob.glob(os.path.join(os.environ.get("SERVICETRACK_UPLOADS", os.path.join(BASE_DIR, "uploads")), "*")):
        if not f.endswith(".keep"):
            os.remove(f)

import app as st  # noqa: E402  (import after the optional reset)

client = st.app.test_client()
con = sqlite3.connect(st.DB_PATH)
if con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
    sys.exit("The system already has requests. Run: python seed_demo.py --reset")


def login(email, password):
    client.get("/logout")
    client.post("/login", data={"email": email, "password": password})


def register(name, email, building, unit):
    client.post("/register", data={"name": name, "email": email, "phone": "0501234567",
                                   "building": building, "unit": unit, "password": "demo123"})


def submit(category, description, building, floor, unit, photo=None):
    data = {"category": category, "description": description, "building": building,
            "floor": floor, "unit": unit}
    if photo:
        data["photos"] = (open(os.path.join(PHOTOS, photo), "rb"), photo)
    r = client.post("/customer/new", data=data, content_type="multipart/form-data")
    return int(r.headers["Location"].rsplit("/", 1)[1])


def tech(email):
    return con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]


def assign(rid, email):
    client.post(f"/admin/assign/{rid}", data={"technician_id": tech(email)})


def update(rid, status, note="", after=None):
    data = {"status": status, "note": note}
    if after:
        data["after_photos"] = (open(os.path.join(PHOTOS, after), "rb"), after)
    client.post(f"/technician/update/{rid}", data=data, content_type="multipart/form-data")


def age(rid, hours):
    """Move a request (and its history) back in time to demonstrate the overdue flag."""
    t = (datetime.now() - timedelta(hours=hours)).strftime(st.TIME_FMT)
    con.execute("UPDATE requests SET created_at=? WHERE id=?", (t, rid))
    con.execute("UPDATE status_history SET changed_at=? WHERE request_id=? AND status='Submitted'", (t, rid))
    con.commit()


register("Sara Ahmed", "sara@demo.com", "A", "12")
register("Noura Alqahtani", "noura@demo.com", "B", "4")

login("sara@demo.com", "demo123")
r1 = submit("Plumbing", "Water is leaking under the kitchen sink.", "A", "3", "12", "sink_leak.png")
r3 = submit("Electrical", "The wall socket in the living room is broken and sparks.", "A", "3", "12", "socket.png")
r5 = submit("Plumbing", "The bathroom tap is dripping all the time.", "A", "3", "12")
login("noura@demo.com", "demo123")
r2 = submit("A/C", "The A/C in the bedroom is running but not cooling.", "B", "1", "4", "ac_unit.png")
r4 = submit("Carpentry", "The kitchen cabinet door is broken and does not close.", "B", "1", "4")
r6 = submit("General", "A ceiling light in the corridor is not working.", "B", "1", "4")

login("admin@servicetrack.com", "admin123")
assign(r1, "khalid@servicetrack.com")
assign(r2, "saad@servicetrack.com")
assign(r3, "fahad@servicetrack.com")
assign(r5, "khalid@servicetrack.com")

login("khalid@servicetrack.com", "tech123")
update(r1, "In Progress", "On my way, I will arrive at 4 pm.")
update(r1, "Completed", "Replaced the leaking pipe under the sink.", after="sink_fixed.png")
update(r5, "In Progress", "Checking the tap.")
update(r5, "Completed", "Replaced the tap washer.")
login("saad@servicetrack.com", "tech123")
update(r2, "In Progress", "Waiting for a spare part for the A/C unit.")

login("sara@demo.com", "demo123")
client.post(f"/customer/decision/{r5}", data={"decision": "confirm"})

age(r2, 72)   # In Progress for 3 days  -> overdue
age(r4, 60)   # still Submitted after 60 hours -> overdue
con.close()
print("Demo data created: 6 requests (SR-0001 to SR-0006).")
print("Customers: sara@demo.com / demo123, noura@demo.com / demo123")
