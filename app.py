from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
from datetime import datetime, timedelta
import os
import sys
import time
import wave
import json
import random
import argparse
import pyaudio
import audioop
import requests
import threading
import serial
from threading import Lock
from dotenv import load_dotenv
import urllib.parse
import atexit
from google.cloud import speech
from google.cloud import texttospeech
import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), "interfaces"))

parser = argparse.ArgumentParser(description="Medication Manager Voice Assistant")
parser.add_argument(
    "--no-pi",
    action="store_true",
    help="Run in local test mode without Pi-specific hardware (LEDs) or Arduino.",
)
args = parser.parse_args()

if args.no_pi:
    print("--- RUNNING IN AUDIO-ENABLED LOCAL TEST MODE (--no-pi) ---")

    class MockPixels:
        def listen(self):
            print("\n[LED: LISTENING]")

        def think(self):
            print("[LED: THINKING]")

        def speak(self):
            print("[LED: SPEAKING]")

        def off(self):
            print("[LED: OFF]")

    pixels = MockPixels()
else:
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), "interfaces"))
        from pixels import pixels
    except ImportError as e:
        print(f"FATAL: Raspberry Pi hardware library import failed: {e}")
        sys.exit(1)


app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
DB_NAME = "medication_manager.db"
CREDENTIALS_FILE = "google_credentials.json"
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 1
RESPEAKER_WIDTH = 2
CHUNK = 1024
INPUT_FILENAME = "input_request.wav"
OUTPUT_FILENAME = "output_response.wav"
ALERT_FILENAME = "alert_response.wav"
GEMINI_MODEL_NAME = "gemini-2.5-flash"
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 2.0
MAX_RECORD_SECONDS = 10
SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 9600

DAY_MAPPING = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}

CURRENT_PATIENT_ID = None
MEDICATION_TAKEN_EVENT = threading.Event()
audio_lock = Lock()
pyaudio_instance = None  # Global instance for PyAudio
global_alerts = []  # List to store active alerts for the frontend

if args.no_pi:
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    RESPEAKER_INDEX = -1
    for i in range(0, numdevices):
        if (
            p.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")
        ) > 0:
            RESPEAKER_INDEX = i
            break
    if RESPEAKER_INDEX == -1:
        print("FATAL: No audio input device found.")
        sys.exit(1)
    p.terminate()
else:
    RESPEAKER_INDEX = 2
    pyaudio_instance = pyaudio.PyAudio()

    def terminate_audio():
        """Ensures PyAudio is terminated properly on exit."""
        if pyaudio_instance:
            pyaudio_instance.terminate()
            print("PyAudio terminated.")

    atexit.register(terminate_audio)


# --- Database Setup (Merged from setup_db.py) ---
def setup_database():
    print("--- Running Database Setup for Flask App ---")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Create tables
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            medicine TEXT,
            time_due TEXT
        )
    """
    )
    c.execute(
        """
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
    """
    )

    # Check if we already have patients
    c.execute("SELECT count(*) FROM patients")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    # Seed data
    # Order: Student Hamad, Athlete Joan, Grandpa Albert
    patients = [
        ("Student Hamad", "Vitamin B", "10:00"),  # Student Persona
        ("Athlete Joan", "Iron Supplement", "12:00"),  # Athlete Persona
        ("Grandpa Albert", "Lisinopril", "08:00"),  # Senior Care Persona
    ]
    c.executemany(
        "INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)", patients
    )

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

            if log_date_obj > today_date:
                continue

            if (pid + day) % 5 == 0:
                status = "MISSED"
            elif (pid + day) % 13 == 0:
                status = "PENDING"
            else:
                status = "TAKEN"

            if log_date_obj < today_date and status == "PENDING":
                status = "MISSED"
            if log_date_obj == today_date:
                status = "PENDING"

            time_taken = "09:00:00" if status == "TAKEN" else None

            c.execute(
                "INSERT OR IGNORE INTO medication_logs (patient_id, date, time_taken, status, notes) VALUES (?, ?, ?, ?, ?)",
                (pid, log_date, time_taken, status, "Seeded data"),
            )

    conn.commit()
    conn.close()
    print("--- Flask DB Setup Complete ---")


if not os.path.exists(CREDENTIALS_FILE):
    print(f"Error: {CREDENTIALS_FILE} not found!")
    sys.exit(1)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE

try:
    with open(CREDENTIALS_FILE, "r") as f:
        creds_data = json.load(f)
    vertexai.init(project=creds_data.get("project_id"), location="us-central1")
    model = GenerativeModel(
        GEMINI_MODEL_NAME,
        system_instruction=[
            "You are a helpful medication manager assistant.",
            "Return ONLY a JSON object.",
            "Possible intents: 'MEDICATION_LOG', 'NEW_PATIENT', 'INTRODUCTION', 'DELAY', 'CONFIRMATION', 'UNKNOWN'.",
            "If user says 'Yes' or 'I took it', return intent: CONFIRMATION value: YES.",
            "If user says 'No' or 'Not yet', return intent: CONFIRMATION value: NO.",
            "If user says 'Give me 5 minutes', return intent: DELAY.",
        ],
    )
    print(f"* Vertex AI Initialized: {GEMINI_MODEL_NAME}")
except Exception as e:
    print(f"Error initializing Vertex AI: {e}")
    sys.exit(1)


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def log_medication(patient_name, status, notes=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM patients WHERE name LIKE ?", (f"%{patient_name}%",))
        patient = c.fetchone()
        if not patient:
            conn.close()
            return False, "Patient not found."

        patient_id = patient["id"]
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M:%S")

        c.execute(
            """INSERT INTO medication_logs (patient_id, date, time_taken, status, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, date) DO UPDATE SET
            status=excluded.status, time_taken=excluded.time_taken, notes=excluded.notes""",
            (patient_id, date_str, time_str, status, notes),
        )
        conn.commit()
        conn.close()

        # Emit real-time update
        socketio.emit(
            "status_update",
            {
                "patient_id": patient_id,
                "patient_name": patient_name,
                "status": status,
                "time_taken": time_str,
            },
        )
        return True, "Success"
    except Exception as e:
        print(f"DB Error: {e}")
        return False, str(e)


def record_audio():
    if args.no_pi:
        pixels.listen()
        text_input = input("🎤 YOU (type response): ")
        pixels.off()
        return text_input

    print(f"* Recording...")
    pixels.listen()
    p = pyaudio_instance  # Use the global instance

    # Use lock to prevent conflict with play_audio
    with audio_lock:
        try:
            stream = p.open(
                rate=RESPEAKER_RATE,
                format=p.get_format_from_width(RESPEAKER_WIDTH),
                channels=RESPEAKER_CHANNELS,
                input=True,
                input_device_index=RESPEAKER_INDEX,
            )
            frames = []
            silent_chunks = 0
            chunks_per_second = RESPEAKER_RATE / CHUNK
            max_silent = int(chunks_per_second * SILENCE_DURATION)
            max_total = int(chunks_per_second * MAX_RECORD_SECONDS)
            count = 0

            while True:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                count += 1
                rms = audioop.rms(data, 2)
                if rms < SILENCE_THRESHOLD:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                if silent_chunks > max_silent or count > max_total:
                    break

            stream.stop_stream()
            stream.close()
            time.sleep(0.1)  # Allow hardware to reset
        except Exception as e:
            print(f"Error recording: {e}")
            pixels.off()
            return INPUT_FILENAME

        try:
            silence = b"\x00" * int(RESPEAKER_RATE * RESPEAKER_WIDTH * 0.5)
            wf = wave.open(INPUT_FILENAME, "wb")
            wf.setnchannels(RESPEAKER_CHANNELS)
            wf.setsampwidth(p.get_sample_size(p.get_format_from_width(RESPEAKER_WIDTH)))
            wf.setframerate(RESPEAKER_RATE)
            wf.writeframes(silence + b"".join(frames))
            wf.close()
        except Exception as e:
            print(f"Error saving wav: {e}")

    pixels.off()
    return INPUT_FILENAME


def speech_to_text(audio_or_text):
    if args.no_pi:
        return audio_or_text
    print("* STT Processing...")
    pixels.think()
    client = speech.SpeechClient()
    with open(audio_or_text, "rb") as audio:
        content = audio.read()
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RESPEAKER_RATE,
        language_code="en-US",
        audio_channel_count=RESPEAKER_CHANNELS,
    )
    try:
        response = client.recognize(config=config, audio=audio)
        pixels.off()
        for result in response.results:
            text = result.alternatives[0].transcript
            print(f"You said: {text}")
            return text
    except Exception as e:
        print(f"STT Error: {e}")
    pixels.off()
    return None


def text_to_speech(text, filename=OUTPUT_FILENAME):
    """
    Synthesizes speech.
    Accepts a filename so the Pillbox thread can use a different file
    than the main thread to avoid collisions.
    """
    if args.no_pi:
        print(f"🔊 ASSISTANT: {text}")
        return True

    print(f"* Synthesizing: '{text}'")
    pixels.think()
    client = texttospeech.TextToSpeechClient()
    ssml_text = f'<speak><break time="250ms"/>{text}</speak>'
    synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US", ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16, sample_rate_hertz=16000
    )

    try:
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        with open(filename, "wb") as out:
            out.write(response.audio_content)
        pixels.off()
        return True
    except Exception as e:
        print(f"TTS Error: {e}")
        pixels.off()
        return False


def play_audio(audio_file):
    if args.no_pi:
        return

    # --- CRITICAL: THREAD LOCK ---
    # This ensures the Pillbox and the Assistant don't speak over each other
    with audio_lock:
        print(f"* Playing {audio_file}...")
        pixels.speak()
        wf = wave.open(audio_file, "rb")
        p = pyaudio_instance  # Use the global instance
        try:
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )
            data = wf.readframes(CHUNK)
            while data:
                stream.write(data)
                data = wf.readframes(CHUNK)
            stream.stop_stream()
            stream.close()
            time.sleep(0.1)  # Allow hardware to reset
        finally:
            pixels.off()
            wf.close()


def process_intent(text):
    print(f"* Gemini Analysis: '{text}'")
    pixels.think()
    try:
        conn = get_db_connection()
        patients = conn.execute("SELECT name, time_due FROM patients").fetchall()
        conn.close()
        patient_context = ", ".join(
            [f"{p['name']} ({p['time_due']})" for p in patients]
        )

        full_prompt = f"Context: {patient_context}. User says: '{text}'"
        response = model.generate_content(full_prompt)
        cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"intent": "UNKNOWN"}


def trigger_caregiver_alert(patient_name, reason):
    """Triggers a visual alert on the Flask dashboard."""
    alert_msg = f"ALERT: {patient_name} - {reason}"
    print(f"🚨 {alert_msg}")
    
    # Add to global list
    timestamp = datetime.now().strftime("%H:%M:%S")
    alert_data = {"message": alert_msg, "timestamp": timestamp}
    global_alerts.append(alert_data)
    
    # Emit socket event for immediate popup
    socketio.emit("new_alert", alert_data)


def monitor_pillbox():
    """
    Background thread that listens to the Arduino via USB Serial.
    It specifically looks for the 'OPENEVENT:' tag defined in your Arduino code.
    """
    if args.no_pi:
        print("--- No Pi Mode: Skipping Serial Monitor ---")
        return

    print(f"--- Connecting to Arduino on {SERIAL_PORT} ---")

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        ser.flush()
    except Exception as e:
        print(f"⚠️ Error connecting to Arduino: {e}")
        return

    while True:
        try:
            if ser.in_waiting > 0:
                line = ser.readline().decode("utf-8").strip()

                if line.startswith("OPENEVENT:"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        short_day = parts[1].strip()
                        full_day = DAY_MAPPING.get(short_day, "Unknown Day")
                        today_short_day = datetime.now().strftime("%a")

                        if short_day == today_short_day:
                            if CURRENT_PATIENT_ID is not None:
                                conn = get_db_connection()
                                patient = conn.execute(
                                    "SELECT name FROM patients WHERE id = ?",
                                    (CURRENT_PATIENT_ID,),
                                ).fetchone()

                                if patient:
                                    log_medication(
                                        patient["name"],
                                        "TAKEN",
                                        notes="Taken via pillbox.",
                                    )
                                    print(
                                        f"💊 Pillbox event logged as TAKEN for {patient['name']}"
                                    )
                                    MEDICATION_TAKEN_EVENT.set()  # Signal main thread
                                    message = "Thank you for taking your medication."
                                else:
                                    message = "Pillbox opened, but could not find the current patient."
                                conn.close()
                            else:
                                print(
                                    "💊 Pillbox opened, but no active patient reminder."
                                )
                                message = "Pillbox opened."

                            if text_to_speech(message, filename=ALERT_FILENAME):
                                play_audio(ALERT_FILENAME)
                        else:
                            print(f"💊 PILLBOX EVENT DETECTED for {full_day}")
                            today_full_day = DAY_MAPPING.get(
                                today_short_day, today_short_day
                            )
                            message = f"The pillbox for {full_day} has been opened. Today is {today_full_day}."
                            if text_to_speech(message, filename=ALERT_FILENAME):
                                play_audio(ALERT_FILENAME)

        except Exception as e:
            print(f"Serial Error: {e}")
            time.sleep(1)


def run_reminder_flow(patient_id, patient_name, medicine, time_due):
    print(f"\n--- Reminder for {patient_name} ---")
    reminders_count = 0
    max_reminders = 3
    delays_count = 0
    max_delays = 3

    # --- NEW: Check status before starting flow ---
    conn = get_db_connection()
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    log = conn.execute(
        "SELECT status FROM medication_logs WHERE patient_id = ? AND date = ?",
        (patient_id, today_date_str),
    ).fetchone()
    conn.close()

    if log and log["status"] == "TAKEN":
        print(f"Medication already taken for {patient_name}. Skipping flow.")
        return

    text_to_speech(f"Hello {patient_name}. It's {time_due}, time for your {medicine}.")
    play_audio(OUTPUT_FILENAME)

    while reminders_count < max_reminders:
        # --- NEW: Check status at the start of each loop ---
        conn = get_db_connection()
        log = conn.execute(
            "SELECT status FROM medication_logs WHERE patient_id = ? AND date = ?",
            (patient_id, today_date_str),
        ).fetchone()
        conn.close()
        if log and log["status"] == "TAKEN":
            print(
                f"Medication for {patient_name} was logged as TAKEN. Stopping reminder."
            )
            return

        audio_file = record_audio()
        text = speech_to_text(audio_file)

        if not text:
            print("* No response. Waiting...")
            time.sleep(5)
            reminders_count += 1
            continue

        intent_data = process_intent(text)

        if (
            intent_data.get("intent") == "CONFIRMATION"
            and intent_data.get("value") == "YES"
        ):
            log_medication(patient_name, "TAKEN")
            text_to_speech("Thank you. Recorded.")
            play_audio(OUTPUT_FILENAME)
            return

        elif intent_data.get("intent") == "DELAY":
            if delays_count >= max_delays:
                text_to_speech("You have delayed too many times. I am notifying your caregiver.")
                play_audio(OUTPUT_FILENAME)
                trigger_caregiver_alert(patient_name, "Exceeded max delays")
                log_medication(patient_name, "MISSED")
                return

            delays_count += 1
            text_to_speech("Okay, waiting 5 minutes.")
            play_audio(OUTPUT_FILENAME)

            # Wait for 5 seconds (demo) OR until medication is taken
            # We clear the event first to ensure we catch a *new* event
            MEDICATION_TAKEN_EVENT.clear()

            print("DEBUG: Waiting for medication taken event or 5s timeout...")
            if MEDICATION_TAKEN_EVENT.wait(timeout=5):
                print(
                    f"Medication taken during delay for {patient_name}. Stopping wait."
                )
                return

            text_to_speech("Time is up. Did you take it?")
            play_audio(OUTPUT_FILENAME)
            continue  # Restart loop

        else:
            reminders_count += 1
            if reminders_count < max_reminders:
                text_to_speech(
                    "Let's time to take your medicine. Please take your medicine."
                )
                play_audio(OUTPUT_FILENAME)

    trigger_caregiver_alert(patient_name, "Missed medication after reminders")
    text_to_speech("Max reminders reached. Sending alert.")
    play_audio(OUTPUT_FILENAME)
    log_medication(patient_name, "MISSED")


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


def start_voice_assistant():
    global CURRENT_PATIENT_ID
    # 1. Start the Pillbox Monitor in a background thread
    #    daemon=True means this thread dies when the main program exits
    pillbox_thread = threading.Thread(target=monitor_pillbox, daemon=True)
    pillbox_thread.start()

    try:
        conn = get_db_connection()
        patients = conn.execute(
            "SELECT id, name, medicine, time_due FROM patients"
        ).fetchall()
        conn.close()
        
        # Sort patients for demo order: Student Hamad, Athlete Joan, Grandpa Albert
        def sort_key(p):
            if "Hamad" in p["name"]: return 1
            if "Joan" in p["name"]: return 2
            if "Albert" in p["name"]: return 3
            return 99
            
        patients.sort(key=sort_key)

        # Infinite loop to keep the program alive so the pillbox monitor keeps working
        # even after reminders are done (or you can remove the while True to run once)
        print("\n--- Press ENTER to start the demo flow ---")
        input()
        
        while True:
            for patient in patients:
                # Demo Mode: Reset status to PENDING for each patient before starting
                # This allows the pillbox interaction to be demoed for every patient in sequence
                conn = get_db_connection()
                today_date_str = datetime.now().strftime("%Y-%m-%d")
                
                # Insert PENDING if not exists, or update to PENDING if exists
                conn.execute(
                    """INSERT INTO medication_logs (patient_id, date, status) 
                       VALUES (?, ?, 'PENDING')
                       ON CONFLICT(patient_id, date) DO UPDATE SET 
                       status='PENDING', time_taken=NULL, notes=NULL""",
                    (patient["id"], today_date_str),
                )
                conn.commit()
                conn.close()
                
                # Emit socket update to refresh UI to PENDING
                socketio.emit(
                    "status_update",
                    {
                        "patient_id": patient["id"],
                        "patient_name": patient["name"],
                        "status": "PENDING",
                        "time_taken": None,
                    },
                )

                CURRENT_PATIENT_ID = patient["id"]
                run_reminder_flow(
                    patient["id"],
                    patient["name"],
                    patient["medicine"],
                    patient["time_due"],
                )
                CURRENT_PATIENT_ID = None
                print(f"--- Finished flow for {patient['name']}. Next in 3s... ---")
                time.sleep(3)

            print(
                "--- All reminders done. Listening for Pillbox events (Ctrl+C to exit) ---"
            )
            time.sleep(60)  # Just wait and let the background thread do its work

    except KeyboardInterrupt:
        print("\nExiting voice assistant...")
        pixels.off()
    except Exception as e:
        print(f"Error in voice assistant: {e}")
        pixels.off()


if __name__ == "__main__":
    # Initialize DB if not exists
    setup_database()

    # Run the voice assistant in a background thread
    assistant_thread = threading.Thread(target=start_voice_assistant, daemon=True)
    assistant_thread.start()

    socketio.run(
        app,
        host="0.0.0.0",
        port=8080,
        debug=True,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
