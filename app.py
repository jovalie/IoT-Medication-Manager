from flask import Flask, render_template, jsonify, request, redirect, url_for
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
DB_NAME = "medication_manager.db"

# --- Database Setup (Merged from setup_db.py) ---
def setup_database():
    print("--- Running Database Setup for Flask App ---")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Create tables
    c.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            medicine TEXT,
            time_due TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS medication_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time_taken TEXT,
            status TEXT NOT NULL CHECK(status IN ('TAKEN', 'MISSED', 'PENDING')),
            notes TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            UNIQUE(patient_id, date)
        )
    """)
    
    # Check if we already have patients
    c.execute("SELECT count(*) FROM patients")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    # Seed data
    patients = [
        ("Grandpa Albert", "Adderall", "08:00"),      # Student Persona
        ("Grandpa Hamad", "Lisinopril", "20:00"),       # Senior Care Persona
        ("Auntie Joan", "Fish Oil", "12:00"),        # Athlete Persona
    ]
    c.executemany("INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)", patients)
    
    c.execute("SELECT id, name FROM patients")
    patient_list = c.fetchall()
    
    year = 2025
    month = 11
    num_days = 30
    
    for pid, name in patient_list:
        for day in range(1, num_days + 1):
            log_date = f"{year}-{month:02d}-{day:02d}"
            log_date_obj = datetime.strptime(log_date, "%Y-%m-%d").date()
            today_date = datetime.now().date()

            if log_date_obj > today_date: continue

            if (pid + day) % 5 == 0: status = "MISSED"
            elif (pid + day) % 13 == 0: status = "PENDING"
            else: status = "TAKEN"

            if log_date_obj < today_date and status == "PENDING": status = "MISSED"
            if log_date_obj == today_date: status = "PENDING"

            time_taken = "09:00:00" if status == "TAKEN" else None
            
            c.execute(
                "INSERT OR IGNORE INTO medication_logs (patient_id, date, time_taken, status, notes) VALUES (?, ?, ?, ?, ?)",
                (pid, log_date, time_taken, status, "Seeded data")
            )
            
    conn.commit()
    conn.close()
    print("--- Flask DB Setup Complete ---")


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return redirect(url_for("caregiver_dashboard"))


@app.route("/caregiver")
def caregiver_dashboard():
    """Overview of all patients and their status for TODAY."""
    conn = get_db_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    # Get all patients
    patients = conn.execute("SELECT * FROM patients").fetchall()

    patient_data = []
    for p in patients:
        # Get today's log
        log = conn.execute(
            "SELECT * FROM medication_logs WHERE patient_id = ? AND date = ?",
            (p["id"], today),
        ).fetchone()

        status = log["status"] if log else "PENDING"
        patient_data.append(
            {
                "id": p["id"],
                "name": p["name"],
                "status": status,
                "medicine": p["medicine"],
                "time_due": p["time_due"],
            }
        )

    conn.close()
    return render_template("caregiver.html", patients=patient_data, today=today)


@app.route("/patient/new")
def new_patient_form():
    """Display a form to add a new patient."""
    return render_template("new_patient.html")


@app.route("/patient/create", methods=["POST"])
def create_patient():
    """Handle the new patient form submission."""
    name = request.form["name"]
    medicine = request.form["medicine"]
    time_due = request.form["time_due"]

    if name and medicine and time_due:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)",
            (name, medicine, time_due),
        )
        conn.commit()
        conn.close()

    return redirect(url_for("caregiver_dashboard"))


@app.route("/patient/<int:patient_id>")
def patient_calendar(patient_id):
    """Calendar view for a specific patient."""
    conn = get_db_connection()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()
    conn.close()

    if not patient:
        return "Patient not found", 404

    return render_template("calendar.html", patient=patient)


@app.route("/api/patient/<int:patient_id>/logs")
def get_patient_logs(patient_id):
    """API to get logs for the calendar."""
    conn = get_db_connection()
    logs = conn.execute(
        "SELECT * FROM medication_logs WHERE patient_id = ?", (patient_id,)
    ).fetchall()
    conn.close()

    events = []
    for log in logs:
        color = "#gray"
        if log["status"] == "TAKEN":
            color = "#28a745"  # Green
        elif log["status"] == "MISSED":
            color = "#dc3545"  # Red
        elif log["status"] == "PENDING":
            color = "#ffc107"  # Orange

        events.append(
            {
                "title": log["status"],
                "start": log["date"],
                "color": color,
                "allDay": True,
                "description": log["notes"] or "",
            }
        )

    return jsonify(events)


@app.route("/calendar/all")
def all_patients_calendar():
    """Combined calendar view for all patients."""
    return render_template("calendar_all.html")


@app.route("/api/logs/all")
def get_all_logs():
    """API to get all logs for the combined calendar."""
    conn = get_db_connection()
    logs = conn.execute(
        """
        SELECT 
            ml.status, 
            ml.date, 
            ml.notes, 
            p.name as patient_name 
        FROM medication_logs ml
        JOIN patients p ON ml.patient_id = p.id
    """
    ).fetchall()
    conn.close()

    events = []
    for log in logs:
        color = "#gray"
        if log["status"] == "TAKEN":
            color = "#28a745"  # Green
        elif log["status"] == "MISSED":
            color = "#dc3545"  # Red
        elif log["status"] == "PENDING":
            color = "#ffc107"  # Orange

        events.append(
            {
                "title": f"{log['patient_name']}: {log['status']}",
                "start": log["date"],
                "color": color,
                "allDay": True,
                "description": log["notes"] or "",
            }
        )

    return jsonify(events)


@app.route("/admin/reset_status", methods=["POST"])
def reset_status():
    """Reset everyone's status for TODAY to PENDING (useful for demos/testing)."""
    conn = get_db_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    # Delete today's logs so they revert to "PENDING" (which is the absence of a log)
    conn.execute("DELETE FROM medication_logs WHERE date = ?", (today,))
    conn.commit()
    conn.close()

    return redirect(url_for("caregiver_dashboard"))


if __name__ == "__main__":
    # Initialize DB if not exists
    setup_database()
        
    app.run(host="0.0.0.0", port=8080, debug=True)
