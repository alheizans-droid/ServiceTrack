# ServiceTrack – Maintenance Request Management System

CS 388T (Agile Software Development) – Scrum team project.

ServiceTrack replaces phone calls and WhatsApp messages with a trackable maintenance
process: residents submit requests with photos, the administrator assigns them to a
technician by specialty, technicians update the job until it is fixed, and the resident
confirms the fix or reopens the request.

**Team:** Shahad Adel Alheizan (Product Owner) · Nouf Nasser Alzoman (Scrum Master) ·
Yara Alharbi (Developer) · Raghad Abdullah Alotaibi (Developer / QA)

Built with Python (Flask) and SQLite.

## How to run

1. Install Python 3.10 or newer (https://www.python.org/downloads/).
   On Windows, tick "Add Python to PATH" during installation.
2. Download the project:

       git clone <repository-url>
       cd servicetrack

3. Install the requirements (one time only):

       pip install -r requirements.txt

4. (Optional) Load demo data for a presentation:

       python seed_demo.py --reset

5. Start the app:

       python app.py

6. Open http://127.0.0.1:5000 in your browser.

The database file `servicetrack.db` is created automatically the first time.
A database created by the Sprint 1 version is upgraded automatically.
To start again with an empty system, run `python seed_demo.py --reset`, or stop the
app and delete `servicetrack.db` and the photos inside `uploads/`.

## Ready accounts

| Role                    | Email                   | Password |
|-------------------------|-------------------------|----------|
| Admin                   | admin@servicetrack.com  | admin123 |
| Technician (Plumbing)   | khalid@servicetrack.com | tech123  |
| Technician (Electrical) | fahad@servicetrack.com  | tech123  |
| Technician (A/C)        | saad@servicetrack.com   | tech123  |
| Technician (Carpentry)  | majed@servicetrack.com  | tech123  |
| Technician (General)    | omar@servicetrack.com   | tech123  |
| Customer (demo data)    | sara@demo.com           | demo123  |
| Customer (demo data)    | noura@demo.com          | demo123  |

Customers can also create their own account from the "Create an account" page.
The two demo customers exist only after running `seed_demo.py`.

## Features

### Sprint 1

| PBI   | Feature | Where |
|-------|---------|-------|
| PB-01 | Customer registration and login, role-based access | /register, /login |
| PB-02 | Submit a request (category, description, building/floor/unit), unique number SR-xxxx, status "Submitted" | Customer > New Request |
| PB-03 | Attach JPG/PNG photos (max 5 MB each) | New Request form, request details |
| PB-04 | Status steps + status history timeline, technician name | Request details page |
| PB-05 | Admin dashboard with filters (status, category) and sort by date | Admin > Dashboard |
| PB-06 | Assign a technician filtered by specialty; status changes to "Assigned" | Admin > Dashboard |

### Sprint 2

| PBI   | Feature | Where |
|-------|---------|-------|
| PB-07 | Technician job list: only own jobs, with description, location, photo and status; open / all jobs | Technician > My Jobs |
| PB-08 | Technician updates status Assigned → In Progress → Completed (only in this order) with a note; every change saved with date and time | Request details (technician) |
| PB-09 | In-app notifications for the customer on every status change; unread count, open request, mark as read | Customer > Notifications |
| PB-10 | Open requests older than 48 hours (from creation or last reopening) are flagged as overdue; overdue count and "Overdue only" filter | Admin > Dashboard |
| PB-11 | After-service photo uploaded by the assigned technician (JPG/PNG, max 5 MB), shown separately from the problem photos | Request details (technician) |
| PB-12 | Customer confirms the fix, or reopens a completed request with a reason (goes back to In Progress with the same technician) | Request details (customer) |
| PB-13 | Admin adds, edits, deactivates and reactivates technician accounts; deactivated technicians cannot log in or be assigned; open jobs must be reassigned first | Admin > Technicians, request details (Reassign) |
| PB-17 | Usability: clearer error and confirmation messages, grouped request form with hints, prominent current status, filter summary and reset | All pages |

The overdue threshold can be changed with the environment variable
`SERVICETRACK_OVERDUE_HOURS` (default 48).

## Automated tests

    pip install -r requirements-dev.txt
    python -m pytest -v

26 tests cover every Sprint 2 acceptance criterion and a regression of the Sprint 1 flow.
The tests use a temporary database and do not touch `servicetrack.db`.

## Demo scenario (for the Sprint Review)

After `python seed_demo.py --reset`:

1. **Technician** (fahad@servicetrack.com): My Jobs shows SR-0002 with its photo. Open it,
   add a note and mark it In Progress.
2. **Customer** (sara@demo.com): Notifications shows the new update. Open SR-0001
   (Completed, with an after-service photo) and confirm it, or reopen it with a reason.
3. **Admin** (admin@servicetrack.com): the dashboard shows 2 overdue requests
   (SR-0004 and SR-0005). Use "Overdue only", assign SR-0005, then go to Technicians.
4. **Admin**: try to deactivate Saad (blocked: SR-0004 is still open), reassign SR-0004
   from its details page, then deactivate Saad. Saad can no longer log in.

## Project structure

    app.py               routes, database and business logic
    templates/           HTML pages (Jinja templates)
    static/style.css     styles
    tests/test_app.py    automated acceptance tests (pytest)
    seed_demo.py         demo data for presentations
    demo_photos/         sample photos used by seed_demo.py
    uploads/             uploaded photos (not stored in Git)
    servicetrack.db      SQLite database (created on first run, not stored in Git)
