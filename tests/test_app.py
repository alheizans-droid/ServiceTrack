"""Automated acceptance tests for ServiceTrack (Sprint 1 regression + Sprint 2 stories).

Run from the project folder:
    pip install -r requirements-dev.txt
    python -m pytest -v
"""
import importlib
import io
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "demo_photos", "sink_leak.png"), "rb") as photo:
    PNG = photo.read()


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICETRACK_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SERVICETRACK_UPLOADS", str(tmp_path / "uploads"))
    sys.path.insert(0, ROOT)
    if "app" in sys.modules:
        mod = importlib.reload(sys.modules["app"])
    else:
        mod = importlib.import_module("app")
    mod.app.config.update(TESTING=True, CSRF_ENABLED=False)
    yield mod
    sys.path.remove(ROOT)


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


def db(app_module):
    con = sqlite3.connect(app_module.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def login(client, email, password):
    client.get("/logout")
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def register_customer(client, email="sara@test.com"):
    client.post("/register", data={"name": "Sara Ahmed", "email": email, "phone": "0500000000",
                                   "building": "A", "unit": "12", "password": "secret1"})


def submit_request(client, category="Plumbing", photo=True):
    data = {"category": category, "description": "Leak under the sink", "building": "A", "floor": "3",
            "unit": "12"}
    if photo:
        data["photos"] = (io.BytesIO(PNG), "leak.png")
    r = client.post("/customer/new", data=data, content_type="multipart/form-data")
    return int(r.headers["Location"].rsplit("/", 1)[1])


def tech_id(app_module, email):
    return db(app_module).execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]


def assigned_request(client, app_module, tech="khalid@servicetrack.com"):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    rid = submit_request(client)
    login(client, "admin@servicetrack.com", "admin123")
    client.post(f"/admin/assign/{rid}", data={"technician_id": tech_id(app_module, tech)})
    return rid


def status_of(app_module, rid):
    return db(app_module).execute("SELECT status FROM requests WHERE id=?", (rid,)).fetchone()[0]


# ---------------------------------------------------------------- Sprint 1 regression
def test_rg01_register_login_submit(client, app_module):
    register_customer(client)
    r = login(client, "sara@test.com", "secret1")
    assert b"My Requests" in r.data
    rid = submit_request(client)
    assert status_of(app_module, rid) == "Submitted"


def test_rg02_assign_by_specialty(client, app_module):
    rid = assigned_request(client, app_module)
    assert status_of(app_module, rid) == "Assigned"


def test_rg03_roles_cannot_open_other_pages(client, app_module):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/technicians").status_code == 403


# ---------------------------------------------------------------- PB-07 technician job list
def test_pb07_ac1_technician_sees_only_own_jobs(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    assert f"SR-{rid:04d}".encode() in client.get("/technician").data
    login(client, "fahad@servicetrack.com", "tech123")
    assert f"SR-{rid:04d}".encode() not in client.get("/technician").data
    assert client.get(f"/request/{rid}").status_code == 403


def test_pb07_ac2_job_shows_description_location_photo_status(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    page = client.get("/technician").data
    for text in (b"Leak under the sink", b"Bldg A, F3, Unit 12", b"Problem photo", b"Assigned"):
        assert text in page


# ---------------------------------------------------------------- PB-08 status updates
def test_pb08_ac1_status_order_enforced(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})
    assert status_of(app_module, rid) == "Assigned"          # cannot skip In Progress
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    assert status_of(app_module, rid) == "In Progress"
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})
    assert status_of(app_module, rid) == "Completed"
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    assert status_of(app_module, rid) == "Completed"          # cannot go back


def test_pb08_ac1_other_technician_cannot_update(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "fahad@servicetrack.com", "tech123")
    assert client.post(f"/technician/update/{rid}", data={"status": "In Progress"}).status_code == 403
    assert status_of(app_module, rid) == "Assigned"


def test_pb08_ac2_ac3_note_and_timestamp_visible(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress", "note": "Arriving at 4 pm"})
    row = db(app_module).execute("SELECT * FROM status_history WHERE request_id=? AND status='In Progress'",
                                 (rid,)).fetchone()
    assert row["note"] == "Arriving at 4 pm" and row["changed_at"]
    login(client, "sara@test.com", "secret1")
    assert b"Arriving at 4 pm" in client.get(f"/request/{rid}").data
    login(client, "admin@servicetrack.com", "admin123")
    assert b"Arriving at 4 pm" in client.get(f"/request/{rid}").data


# ---------------------------------------------------------------- PB-09 notifications
def test_pb09_ac1_notification_created_on_status_change(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    msgs = [r["message"] for r in db(app_module).execute("SELECT message FROM notifications")]
    assert any("assigned" in m for m in msgs) and any("In Progress" in m for m in msgs)


def test_pb09_ac2_view_open_and_mark_read(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "sara@test.com", "secret1")
    page = client.get("/notifications").data
    assert b"was assigned to technician Khalid Alomari" in page
    nid = db(app_module).execute("SELECT id FROM notifications").fetchone()[0]
    r = client.get(f"/notifications/{nid}/open")
    assert r.headers["Location"].endswith(f"/request/{rid}")
    assert db(app_module).execute("SELECT is_read FROM notifications WHERE id=?", (nid,)).fetchone()[0] == 1


def test_pb09_ac3_only_owner_and_no_notification_on_rejected_update(client, app_module):
    rid = assigned_request(client, app_module)
    before = db(app_module).execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})   # invalid jump
    assert db(app_module).execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == before
    register_customer(client, "other@test.com")
    login(client, "other@test.com", "secret1")
    nid = db(app_module).execute("SELECT id FROM notifications").fetchone()[0]
    assert client.get(f"/notifications/{nid}/open").status_code == 404
    assert b"Khalid" not in client.get("/notifications").data


# ---------------------------------------------------------------- PB-10 overdue
def set_created(app_module, rid, hours_ago):
    t = (datetime.now() - timedelta(hours=hours_ago)).strftime(app_module.TIME_FMT)
    con = db(app_module)
    con.execute("UPDATE requests SET created_at=? WHERE id=?", (t, rid))
    con.commit()


def test_pb10_ac1_threshold_is_48_hours(app_module):
    assert app_module.OVERDUE_HOURS == 48


def test_pb10_ac2_open_request_flagged_completed_not(client, app_module):
    rid = assigned_request(client, app_module)
    set_created(app_module, rid, 50)
    login(client, "admin@servicetrack.com", "admin123")
    page = client.get("/admin?overdue=1").data
    assert f"SR-{rid:04d}".encode() in page and b"Overdue" in page
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})
    login(client, "admin@servicetrack.com", "admin123")
    assert f"SR-{rid:04d}".encode() not in client.get("/admin?overdue=1").data


def test_pb10_ac3_boundary_and_reopen(client, app_module):
    rid = assigned_request(client, app_module)
    set_created(app_module, rid, 47)
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert not app_module.is_overdue(row)
    set_created(app_module, rid, 49)
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert app_module.is_overdue(row)
    # a reopened request restarts the clock from reopened_at
    con = db(app_module)
    con.execute("UPDATE requests SET reopened_at=? WHERE id=?",
                (datetime.now().strftime(app_module.TIME_FMT), rid))
    con.commit()
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert not app_module.is_overdue(row)


# ---------------------------------------------------------------- PB-11 after-service photo
def test_pb11_ac1_ac3_assigned_technician_adds_after_photo(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    client.post(f"/technician/update/{rid}", data={"status": "Completed",
                                                    "after_photos": (io.BytesIO(PNG), "fixed.png")},
                content_type="multipart/form-data")
    kinds = [r["kind"] for r in db(app_module).execute("SELECT kind FROM photos WHERE request_id=?", (rid,))]
    assert kinds.count("problem") == 1 and kinds.count("after") == 1
    login(client, "sara@test.com", "secret1")
    assert b"After-service photos" in client.get(f"/request/{rid}").data
    login(client, "fahad@servicetrack.com", "tech123")
    r = client.post(f"/technician/after-photo/{rid}", data={"after_photos": (io.BytesIO(PNG), "x.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 403


def test_pb11_ac2_invalid_and_oversized_files_rejected(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    r = client.post(f"/technician/after-photo/{rid}", data={"after_photos": (io.BytesIO(b"x"), "a.gif")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"only JPG and PNG photos are accepted" in r.data
    big = io.BytesIO(PNG + b"0" * (5 * 1024 * 1024))
    r = client.post(f"/technician/after-photo/{rid}", data={"after_photos": (big, "big.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"larger than 5 MB" in r.data
    assert db(app_module).execute("SELECT COUNT(*) FROM photos WHERE kind='after'").fetchone()[0] == 0


# ---------------------------------------------------------------- PB-12 confirm / reopen
def completed_request(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})
    return rid


def test_pb12_ac1_only_owner_and_only_completed(client, app_module):
    rid = assigned_request(client, app_module)
    login(client, "sara@test.com", "secret1")
    client.post(f"/customer/decision/{rid}", data={"decision": "confirm"})
    assert db(app_module).execute("SELECT confirmed_at FROM requests WHERE id=?", (rid,)).fetchone()[0] is None
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    client.post(f"/technician/update/{rid}", data={"status": "Completed"})
    register_customer(client, "other@test.com")
    login(client, "other@test.com", "secret1")
    assert client.post(f"/customer/decision/{rid}", data={"decision": "confirm"}).status_code == 403


def test_pb12_ac2_confirm_keeps_history(client, app_module):
    rid = completed_request(client, app_module)
    before = db(app_module).execute("SELECT COUNT(*) FROM status_history WHERE request_id=?", (rid,)).fetchone()[0]
    login(client, "sara@test.com", "secret1")
    client.post(f"/customer/decision/{rid}", data={"decision": "confirm"})
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["confirmed_at"] and row["status"] == "Completed"
    after = db(app_module).execute("SELECT COUNT(*) FROM status_history WHERE request_id=?", (rid,)).fetchone()[0]
    assert after == before + 1


def test_pb12_ac3_reopen_requires_reason_and_returns_to_same_technician(client, app_module):
    rid = completed_request(client, app_module)
    login(client, "sara@test.com", "secret1")
    client.post(f"/customer/decision/{rid}", data={"decision": "reopen", "reason": ""})
    assert status_of(app_module, rid) == "Completed"
    client.post(f"/customer/decision/{rid}", data={"decision": "reopen", "reason": "Still leaking"})
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["status"] == "In Progress" and row["reopened_at"]
    assert row["technician_id"] == tech_id(app_module, "khalid@servicetrack.com")
    h = db(app_module).execute("SELECT * FROM status_history WHERE request_id=? ORDER BY id DESC",
                               (rid,)).fetchone()
    assert "Still leaking" in h["note"] and h["changed_by"] and h["changed_at"]


# ---------------------------------------------------------------- PB-13 technician accounts
def test_pb13_ac1_add_edit_and_duplicate_email(client, app_module):
    login(client, "admin@servicetrack.com", "admin123")
    client.post("/admin/technicians/new", data={"name": "Ali Saleh", "email": "ali@servicetrack.com",
                                                  "phone": "0555", "specialty": "Electrical",
                                                  "password": "tech123"})
    tid = tech_id(app_module, "ali@servicetrack.com")
    r = client.post("/admin/technicians/new", data={"name": "Copy", "email": "ali@servicetrack.com",
                                                      "specialty": "General", "password": "tech123"},
                    follow_redirects=True)
    assert b"already used by another account" in r.data
    client.post(f"/admin/technicians/{tid}/edit", data={"name": "Ali Saleh", "email": "ali@servicetrack.com",
                                                          "phone": "0555", "specialty": "A/C", "password": ""})
    assert db(app_module).execute("SELECT specialty FROM users WHERE id=?", (tid,)).fetchone()[0] == "A/C"


def test_pb13_ac2_deactivated_cannot_login_or_be_assigned(client, app_module):
    rid = assigned_request(client, app_module)
    khalid = tech_id(app_module, "khalid@servicetrack.com")
    login(client, "admin@servicetrack.com", "admin123")
    r = client.post(f"/admin/technicians/{khalid}/active", data={"active": "0"}, follow_redirects=True)
    assert b"reassign the open job" in r.data                      # open job blocks deactivation
    client.post("/admin/technicians/new", data={"name": "Backup Plumber", "email": "backup@test.com",
                 "phone": "0555", "specialty": "Plumbing", "password": "tech123"})
    omar = tech_id(app_module, "backup@test.com")
    client.post(f"/admin/reassign/{rid}", data={"technician_id": omar})
    client.post(f"/admin/technicians/{khalid}/active", data={"active": "0"})
    assert db(app_module).execute("SELECT active FROM users WHERE id=?", (khalid,)).fetchone()[0] == 0
    r = login(client, "khalid@servicetrack.com", "tech123")
    assert b"deactivated" in r.data
    # cannot receive new assignments; history kept
    login(client, "sara@test.com", "secret1")
    rid2 = submit_request(client)
    login(client, "admin@servicetrack.com", "admin123")
    client.post(f"/admin/assign/{rid2}", data={"technician_id": khalid})
    assert status_of(app_module, rid2) == "Submitted"
    assert db(app_module).execute("SELECT COUNT(*) FROM status_history WHERE note LIKE '%Khalid%'").fetchone()[0] >= 1


def test_pb13_ac3_non_admin_blocked(client, app_module):
    login(client, "khalid@servicetrack.com", "tech123")
    assert client.get("/admin/technicians").status_code == 403
    assert client.post("/admin/technicians/new", data={}).status_code == 403


# ---------------------------------------------------------------- PB-17 usability
def test_pb17_ac1_clear_error_messages(client, app_module):
    r = client.post("/login", data={"email": "x@x.com", "password": "bad"})
    assert b"Please check them and try again" in r.data
    r = client.post("/register", data={"name": "", "email": "", "phone": "", "building": "", "unit": "",
                                       "password": ""})
    assert b"Please fill in: Full name, Email" in r.data


def test_pb17_ac2_form_labels_and_prominent_status(client, app_module):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    assert b"are required" in client.get("/customer/new").data
    rid = submit_request(client)
    assert b"Current status: <b>Submitted</b>" in client.get(f"/request/{rid}").data


def test_pb17_ac3_filter_reset_and_assign_confirmation(client, app_module):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    rid = submit_request(client)
    login(client, "admin@servicetrack.com", "admin123")
    page = client.get("/admin?status=Submitted&category=Plumbing").data
    assert b"Reset filters" in page and b"Status: Submitted" in page
    r = client.post(f"/admin/assign/{rid}", data={"technician_id": tech_id(app_module, "khalid@servicetrack.com")},
                    follow_redirects=True)
    assert b"Its status is now Assigned" in r.data


def test_sprint1_database_is_upgraded(tmp_path, monkeypatch):
    """A database created by the Sprint 1 version gets the new Sprint 2 columns automatically."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, phone TEXT,
        building TEXT, unit TEXT, password TEXT, role TEXT, specialty TEXT, created_at TEXT);
        CREATE TABLE requests (id INTEGER PRIMARY KEY, customer_id INT, category TEXT, description TEXT,
        building TEXT, floor TEXT, unit TEXT, status TEXT, technician_id INT, created_at TEXT);
        CREATE TABLE photos (id INTEGER PRIMARY KEY, request_id INT, filename TEXT);""")
    con.close()
    monkeypatch.setenv("SERVICETRACK_DB", str(path))
    monkeypatch.setenv("SERVICETRACK_UPLOADS", str(tmp_path / "u"))
    sys.path.insert(0, ROOT)
    importlib.reload(sys.modules["app"]) if "app" in sys.modules else importlib.import_module("app")
    sys.path.remove(ROOT)
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(requests)")}
    assert {"confirmed_at", "reopened_at"} <= cols


# ---------------------------------------------------------------- Security and validation regressions from archive review
def test_pb06_rejects_wrong_specialty_assignment_and_reassignment(client, app_module):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    rid = submit_request(client)
    login(client, "admin@servicetrack.com", "admin123")
    wrong = tech_id(app_module, "fahad@servicetrack.com")
    correct = tech_id(app_module, "khalid@servicetrack.com")
    client.post(f"/admin/assign/{rid}", data={"technician_id": wrong})
    assert status_of(app_module, rid) == "Submitted"
    client.post(f"/admin/assign/{rid}", data={"technician_id": correct})
    client.post(f"/admin/reassign/{rid}", data={"technician_id": wrong})
    row = db(app_module).execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["technician_id"] == correct and row["status"] == "Assigned"


def test_photo_urls_restricted_to_owner_admin_and_assigned_technician(client, app_module):
    rid = assigned_request(client, app_module)
    filename = db(app_module).execute("SELECT filename FROM photos WHERE request_id=?", (rid,)).fetchone()[0]
    path = "/uploads/" + filename
    assert client.get(path).status_code == 200  # administrator
    login(client, "sara@test.com", "secret1")
    assert client.get(path).status_code == 200
    login(client, "khalid@servicetrack.com", "tech123")
    assert client.get(path).status_code == 200
    login(client, "fahad@servicetrack.com", "tech123")
    assert client.get(path).status_code in (403, 404)
    register_customer(client, "other@test.com")
    login(client, "other@test.com", "secret1")
    assert client.get(path).status_code in (403, 404)
    assert client.get("/uploads/does-not-exist.png").status_code == 404


def test_fake_image_content_rejected_without_partial_mutations(client, app_module):
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    data = {"category": "Plumbing", "description": "Leak", "building": "A", "floor": "3",
            "unit": "12", "photos": (io.BytesIO(b"not an image"), "spoof.png")}
    client.post("/customer/new", data=data, content_type="multipart/form-data")
    assert db(app_module).execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    assert db(app_module).execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
    rid = submit_request(client)
    login(client, "admin@servicetrack.com", "admin123")
    client.post(f"/admin/assign/{rid}", data={"technician_id": tech_id(app_module, "khalid@servicetrack.com")})
    login(client, "khalid@servicetrack.com", "tech123")
    client.post(f"/technician/update/{rid}", data={"status": "In Progress"})
    history_before = db(app_module).execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
    notifications_before = db(app_module).execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    for path in (f"/technician/after-photo/{rid}", f"/technician/update/{rid}"):
        client.post(path, data={"status": "Completed", "note": "Must not persist",
                               "after_photos": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 80), "spoof.png")},
                    content_type="multipart/form-data")
    assert status_of(app_module, rid) == "In Progress"
    assert db(app_module).execute("SELECT COUNT(*) FROM photos WHERE kind='after'").fetchone()[0] == 0
    assert db(app_module).execute("SELECT COUNT(*) FROM status_history").fetchone()[0] == history_before
    assert db(app_module).execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == notifications_before


def test_open_job_blocks_technician_specialty_change(client, app_module):
    rid = assigned_request(client, app_module)
    tid = tech_id(app_module, "khalid@servicetrack.com")
    login(client, "admin@servicetrack.com", "admin123")
    client.post(f"/admin/technicians/{tid}/edit", data={"name": "Khalid Alomari",
                "email": "khalid@servicetrack.com", "phone": "0500000000",
                "specialty": "Electrical", "password": ""})
    assert db(app_module).execute("SELECT specialty FROM users WHERE id=?", (tid,)).fetchone()[0] == "Plumbing"
    assert db(app_module).execute("SELECT technician_id FROM requests WHERE id=?", (rid,)).fetchone()[0] == tid


def csrf_post(client, path, data=None):
    html = client.get("/login").get_data(as_text=True)
    import re
    token = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)', html)
    assert token, "CSRF token must be present in the login form"
    return client.post(path, data=dict(data or {}, csrf_token=token.group(1)))


def test_csrf_rejects_missing_invalid_and_unicode_tokens(client, app_module):
    app_module.app.config["CSRF_ENABLED"] = True
    before = db(app_module).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    for data in ({}, {"csrf_token": "invalid"}, {"csrf_token": "é"}):
        r = client.post("/register", data=dict(name="No Token", email="no@test.com", phone="05",
                        building="A", unit="1", password="secret1", **data))
        assert r.status_code == 400
    assert db(app_module).execute("SELECT COUNT(*) FROM users").fetchone()[0] == before
    r = csrf_post(client, "/login", {"email": "admin@servicetrack.com", "password": "admin123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
    data = dict(name="CSRF Valid", email="csrf.valid@test.com", specialty="Plumbing", password="secret1")
    assert client.post("/admin/technicians/new", data=data).status_code == 400
    assert db(app_module).execute("SELECT COUNT(*) FROM users WHERE email=?", (data["email"],)).fetchone()[0] == 0
    assert csrf_post(client, "/admin/technicians/new", data).status_code == 302
    assert db(app_module).execute("SELECT COUNT(*) FROM users WHERE email=?", (data["email"],)).fetchone()[0] == 1


def test_all_role_post_forms_include_csrf_token(client, app_module):
    rid = assigned_request(client, app_module)
    completed_rid = completed_request(client, app_module)
    app_module.app.config["CSRF_ENABLED"] = True
    from html.parser import HTMLParser
    class Forms(HTMLParser):
        def __init__(self):
            super().__init__(); self.forms = []; self.current = None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.current = {"post": attrs.get("method", "get").lower() == "post", "token": False}
            if tag == "input" and self.current is not None and attrs.get("name") == "csrf_token":
                self.current["token"] = bool(attrs.get("value"))
        def handle_endtag(self, tag):
            if tag == "form" and self.current is not None:
                self.forms.append(self.current); self.current = None
    def check(path):
        r = client.get(path); assert r.status_code == 200, path
        parser = Forms(); parser.feed(r.get_data(as_text=True))
        assert all(f["token"] for f in parser.forms if f["post"]), path
    for email, password, paths in [
        ("admin@servicetrack.com", "admin123", ["/admin", "/admin/technicians", "/admin/technicians/new",
                                             f"/admin/technicians/{tech_id(app_module, 'khalid@servicetrack.com')}/edit",
                                             f"/request/{rid}"]),
        ("khalid@servicetrack.com", "tech123", ["/technician", f"/request/{rid}", f"/request/{completed_rid}"]),
        ("sara@test.com", "secret1", ["/customer", "/customer/new", "/notifications", f"/request/{rid}", f"/request/{completed_rid}"])]:
        client.get("/logout"); csrf_post(client, "/login", {"email": email, "password": password})
        for path in paths: check(path)
    client.get("/logout"); check("/login"); check("/register")


# A real 16x12 JPEG photo (generated once with Pillow) used to test JPEG uploads.
REAL_JPEG = __import__("base64").b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAMABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDoaKKK988U/9k=")


def test_jpeg_with_extra_data_after_image_is_accepted(client, app_module):
    """Photos from some phones (e.g. motion photos) have extra bytes after the image end marker."""
    register_customer(client)
    login(client, "sara@test.com", "secret1")
    for name, payload in (("normal.jpg", REAL_JPEG), ("phone.jpg", REAL_JPEG + b"MotionPhoto_Data" + b"x" * 64)):
        data = {"category": "Plumbing", "description": "Leak", "building": "A", "floor": "3",
                "unit": "12", "photos": (io.BytesIO(payload), name)}
        client.post("/customer/new", data=data, content_type="multipart/form-data")
    assert db(app_module).execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 2
    # a file that only starts like a JPEG is still rejected
    data = {"category": "Plumbing", "description": "Leak", "building": "A", "floor": "3",
            "unit": "12", "photos": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"x" * 80 + b"\xff\xd9"), "fake.jpg")}
    client.post("/customer/new", data=data, content_type="multipart/form-data")
    assert db(app_module).execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 2
