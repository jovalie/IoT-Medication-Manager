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
        # Get today's log
        log = conn.execute(
            "SELECT * FROM medication_logs WHERE patient_id = ? AND date = ?",
            (p["id"], today),
        ).fetchone()

        status = log["status"] if log else "PENDING"
        patient_data.append({"id": p["id"], "name": p["name"], "status": status})

    conn.close()
    return render_template("caregiver.html", patients=patient_data, today=today)


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
