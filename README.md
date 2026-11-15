# ServiceTrack – Maintenance Request Management System

CS 388T (Agile Software Development) – Scrum team project.

ServiceTrack replaces phone calls and WhatsApp messages with a trackable maintenance
process: residents submit requests with photos, the administrator assigns them to a
technician by specialty, technicians update the job until it is fixed, and the resident
confirms the fix or reopens the request.

**Team:** Shahad Adel Alheizan (Product Owner) · Nouf Nasser Alzoman (Scrum Master) ·
Yara Alharbi (Developer) · Raghad Abdullah Alotaibi (Developer / QA)

Built with Python (Flask) and SQLite.

## How to run on macOS using PyCharm

Use Python 3.10 or newer. Extract the ZIP, then use **File > Open** in PyCharm
and open the `servicetrack` folder containing `app.py`, `requirements.txt`,
`templates` and `static`.

Open PyCharm's **Terminal** in that folder and run these commands one at a time:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m flask --app app run --port 5001
```

Open **http://127.0.0.1:5001** in Safari or Chrome. Keep the terminal running;
press **Control+C** to stop the server. Port 5001 avoids the macOS AirPlay
Receiver service that can occupy port 5000.

For the PyCharm Run button, select the project's `.venv/bin/python` as its
Python Interpreter, then right-click `app.py` and choose **Run**. This direct
startup uses **http://127.0.0.1:5000**. If 5000 is busy, use the Terminal command
above with port 5001.

The app uses **Python, Flask and SQLite**. The SQLite database file
`servicetrack.db` and the uploads directory are created automatically.
MySQL, PHP and XAMPP are not required to run this project.

An original Sprint 1 database is upgraded while preserving its records.
Stop the app and back up any existing database and uploaded photos before
replacing source files; keep that data when upgrading.

On Windows, create a virtual environment with `python -m venv .venv`, then use
`.venv\Scripts\python.exe -m pip install -r requirements.txt` and
`.venv\Scripts\python.exe app.py`.

### Optional presentation data

For a fresh project with no requests, stop the server and run:

```bash
.venv/bin/python seed_demo.py
```

Then start the server again. The script adds six demonstration requests,
photos and two demo customers; it dates two demonstration records earlier
so that the overdue filter can be shown.

`seed_demo.py --reset` deletes the selected database and uploaded photos.
Use it only when you intentionally want to discard existing demonstration
data. Normal startup does not need this command.

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

## Validation and permissions

Uploaded files must contain a valid, nonempty JPG/JPEG or PNG image and be at most
5 MB each. Photo access follows the same request-owner and assigned-technician
permissions as the request details. Assignments and reassignments use active
technicians with the matching specialty; a technician with open jobs cannot be
deactivated or moved to a different specialty until those jobs are reassigned.
POST forms include CSRF protection. Local startup uses a generated session secret
unless SECRET_KEY or SERVICETRACK_SECRET_KEY is set in the environment.

## Automated tests

    .venv/bin/python -m pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -v

33 automated tests cover the Sprint 2 features, important rejected actions and a regression of the Sprint 1 flow.
The tests use a temporary database and do not touch `servicetrack.db`.

## Demo scenario (for the Sprint Review)

After loading demo data into a fresh project with `seed_demo.py`:

1. **Technician** (fahad@servicetrack.com): My Jobs shows SR-0002 with its photo. Open it,
   add a note and mark it In Progress.
2. **Customer** (sara@demo.com): Notifications shows the new update. Open SR-0001
   (Completed, with an after-service photo) and confirm it, or reopen it with a reason.
3. **Admin** (admin@servicetrack.com): the dashboard shows 2 overdue requests
   (SR-0004 and SR-0005). Use "Overdue only", assign SR-0005, then go to Technicians.
4. **Admin**: try to deactivate Saad (blocked: SR-0004 is still open). Create another active A/C technician, reassign SR-0004 to that technician from its details page, then deactivate Saad. Saad can no longer log in.

## Project structure

    app.py               routes, database and business logic
    templates/           HTML pages (Jinja templates)
    static/style.css     styles
    tests/test_app.py    automated acceptance tests (pytest)
    seed_demo.py         demo data for presentations
    demo_photos/         sample photos used by seed_demo.py
    uploads/             uploaded photos (not stored in Git)
    servicetrack.db      SQLite database (created on first run, not stored in Git)
