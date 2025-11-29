from flask import Flask, render_template, jsonify, request, redirect, url_for
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
DB_NAME = "medication_manager.db"


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
        # Get all medications and their status for today
        medications = conn.execute("""
            SELECT
                m.id,
                m.medicine_name,
                m.time_due,
                ml.status
            FROM medications m
            LEFT JOIN medication_logs ml ON m.id = ml.medication_id AND ml.date = ?
            WHERE m.patient_id = ?
            ORDER BY m.time_due
        """, (today, p['id'])).fetchall()

        med_list = []
        for med in medications:
            med_list.append({
                "name": med['medicine_name'],
                "time": med['time_due'],
                "status": med['status'] if med['status'] else 'PENDING'
            })

        patient_data.append({
            "id": p['id'],
            "name": p['name'],

            "medications": med_list
        })

    conn.close()
    return render_template('caregiver.html', patients=patient_data, today=today)


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
    logs = conn.execute("""
        SELECT
            ml.status,
            ml.date,
            ml.notes,
            m.medicine_name
        FROM medication_logs ml
        JOIN medications m ON ml.medication_id = m.id
        WHERE m.patient_id = ?
    """, (patient_id,)).fetchall()
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


@app.route('/calendar/all')
def all_patients_calendar():
    """Combined calendar view for all patients."""
    return render_template('calendar_all.html')


@app.route('/api/logs/all')
def get_all_logs():
    """API to get all logs for the combined calendar."""
    conn = get_db_connection()
    logs = conn.execute("""
        SELECT
            ml.status,
            ml.date,
            ml.notes,
            p.name as patient_name,
            m.medicine_name
        FROM medication_logs ml
        JOIN medications m ON ml.medication_id = m.id
        JOIN patients p ON m.patient_id = p.id
    """).fetchall()
    conn.close()

    events = []
    for log in logs:
        color = "#gray"
        if log['status'] == 'TAKEN':
            color = "#28a745" # Green
        elif log['status'] == 'MISSED':
            color = "#dc3545" # Red
        elif log['status'] == 'PENDING':
            color = "#ffc107" # Orange

        events.append({
            "title": f"{log['patient_name']} - {log['medicine_name']}: {log['status']}",
            "start": log['date'],
            "color": color,
            "allDay": True,
            "description": log['notes'] or ""
        })

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
    import os

    if not os.path.exists(DB_NAME):
        import setup_db

        setup_db.main()

    app.run(host="0.0.0.0", port=5000, debug=True)
