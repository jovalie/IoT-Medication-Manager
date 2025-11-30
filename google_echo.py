import sys
import os
import time
import wave
import json
import sqlite3
from datetime import datetime
import random
import argparse
import pyaudio
import audioop
import requests
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

# Add interfaces path
sys.path.append(os.path.join(os.path.dirname(__file__), "interfaces"))

# --- Argument Parser for Test Mode ---
parser = argparse.ArgumentParser(description="Medication Manager Voice Assistant")
parser.add_argument(
    "--no-pi",
    action="store_true",
    help="Run in local test mode without Pi-specific hardware (LEDs).",
)
args = parser.parse_args()

# --- Conditional Hardware Imports & Mocks ---
if args.no_pi:
    print("--- RUNNING IN AUDIO-ENABLED LOCAL TEST MODE (--no-pi) ---")

    # Mock only the Pi-specific LED hardware
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


from google.cloud import speech
from google.cloud import texttospeech
import vertexai
from vertexai.generative_models import GenerativeModel

# --- Constants ---
DB_NAME = "medication_manager.db"
CREDENTIALS_FILE = "google_credentials.json"
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 1  # Use 1 channel for local mic
RESPEAKER_WIDTH = 2
RESPEAKER_INDEX = -1  # For local testing, find a generic input device
CHUNK = 1024
INPUT_FILENAME = "input_request.wav"
OUTPUT_FILENAME = "output_response.wav"
GEMINI_MODEL_NAME = "gemini-2.5-flash"

# Silence detection settings
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 2.0
MAX_RECORD_SECONDS = 10

# For local testing, find a generic input device
if args.no_pi:
    p = pyaudio.PyAudio()
    # A more robust way to find an input device
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    RESPEAKER_INDEX = -1
    for i in range(0, numdevices):
        if (
            p.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")
        ) > 0:
            print(
                f"Found audio input device at index {i}: {p.get_device_info_by_host_api_device_index(0, i).get('name')}"
            )
            RESPEAKER_INDEX = i
            break
    if RESPEAKER_INDEX == -1:
        print("FATAL: No audio input device found.")
        sys.exit(1)
    p.terminate()
else:
    RESPEAKER_INDEX = 2  # Pi-specific index


# --- Database Setup (Merged) ---
def setup_database():
    print("--- Running Database Setup ---")
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
    print("Tables created.")

    # Check if we already have patients
    c.execute("SELECT count(*) FROM patients")
    if c.fetchone()[0] > 0:
        print("Data already exists, skipping seed.")
        conn.close()
        return

    # Seed data
    print("Seeding initial data...")
    patients = [
        ("Grandpa Albert", "Omeprazole", "08:00"),  # Student Persona
        ("Grandpa Hamad", "Lisinopril", "20:00"),  # Senior Care Persona
        ("Auntie Joan", "Fish Oil", "12:00"),  # Athlete Persona
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
    print("--- Database Setup Complete ---")


# --- Main Application Logic ---
# Run setup immediately
setup_database()


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def add_new_patient(name, medicine, time_due):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO patients (name, medicine, time_due) VALUES (?, ?, ?)",
            (name, medicine, time_due),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False


def log_medication(patient_name, status, notes=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Find patient ID (simple lookup by name for now)
        c.execute("SELECT id FROM patients WHERE name LIKE ?", (f"%{patient_name}%",))
        patient = c.fetchone()

        if not patient:
            conn.close()
            return False, "Patient not found."

        patient_id = patient["id"]
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M:%S")

        # Upsert log
        c.execute(
            """
            INSERT INTO medication_logs (patient_id, date, time_taken, status, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, date) DO UPDATE SET
            status=excluded.status,
            time_taken=excluded.time_taken,
            notes=excluded.notes
        """,
            (patient_id, date_str, time_str, status, notes),
        )

        conn.commit()
        conn.close()
        return True, "Success"
    except Exception as e:
        print(f"DB Error: {e}")
        return False, str(e)


# Check credentials
if not os.path.exists(CREDENTIALS_FILE):
    print(f"Error: {CREDENTIALS_FILE} not found!")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE

# Initialize Vertex AI
try:
    with open(CREDENTIALS_FILE, "r") as f:
        creds_data = json.load(f)
        project_id = creds_data.get("project_id")

    vertexai.init(project=project_id, location="us-central1")

    # Initialize the model with Structured Output instructions
    model = GenerativeModel(
        GEMINI_MODEL_NAME,
        system_instruction=[
            "You are a helpful medication manager assistant.",
            "You analyze what the user says and extract the intent.",
            "Return ONLY a JSON object. Do not include markdown formatting.",
            "Possible intents: 'MEDICATION_LOG', 'NEW_PATIENT', 'INTRODUCTION', 'DELAY', 'CONFIRMATION', 'UNKNOWN'.",
            "Structure for MEDICATION_LOG: { 'intent': 'MEDICATION_LOG', 'patient_name': '...', 'status': 'TAKEN'/'MISSED', 'notes': '...' }",
            "Structure for NEW_PATIENT: { 'intent': 'NEW_PATIENT', 'name': '...', 'medicine': '...', 'time': '...' }",
            "Structure for INTRODUCTION: { 'intent': 'INTRODUCTION' }",
            "Structure for DELAY: { 'intent': 'DELAY', 'duration': '...' }",
            "Structure for CONFIRMATION: { 'intent': 'CONFIRMATION', 'value': 'YES'/'NO' }",
            "Structure for UNKNOWN: { 'intent': 'UNKNOWN', 'response': '...' }",
            "If the user says 'Yes', 'Yeah', 'I did', 'I already did', 'It is done', 'I took it', return intent: CONFIRMATION value: YES.",
            "If the user says 'No', 'Nope', 'Not yet', 'I forgot', return intent: CONFIRMATION value: NO.",
            "If the user says 'I will take it later' or 'Give me 5 minutes', return intent: DELAY.",
            "If the user says 'I took my meds' and doesn't specify a name, infer the patient name based on who has a medication due around the current time. If unsure, return intent: UNKNOWN with response asking for the name.",
        ],
    )
    print(f"* Vertex AI Initialized with model: {GEMINI_MODEL_NAME}")
except Exception as e:
    print(f"Error initializing Vertex AI: {e}")
    sys.exit(1)


def record_audio():
    if args.no_pi:
        pixels.listen()
        text_input = input("🎤 YOU (type response): ")
        pixels.off()
        return text_input  # In test mode, we return the text directly

    print(f"* Recording until {SILENCE_DURATION} seconds of silence...")
    pixels.listen()

    p = pyaudio.PyAudio()
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
        max_silent_chunks = int(chunks_per_second * SILENCE_DURATION)
        max_total_chunks = int(chunks_per_second * MAX_RECORD_SECONDS)

        chunk_count = 0

        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            chunk_count += 1

            rms = audioop.rms(data, 2)
            if rms < SILENCE_THRESHOLD:
                silent_chunks += 1
            else:
                silent_chunks = 0

            if silent_chunks > max_silent_chunks or chunk_count > max_total_chunks:
                break

        stream.stop_stream()
        stream.close()

        # Add 0.5s silence at start padding
        silence = b"\x00" * int(RESPEAKER_RATE * RESPEAKER_WIDTH * 0.5)

        wf = wave.open(INPUT_FILENAME, "wb")
        wf.setnchannels(RESPEAKER_CHANNELS)
        wf.setsampwidth(p.get_sample_size(p.get_format_from_width(RESPEAKER_WIDTH)))
        wf.setframerate(RESPEAKER_RATE)
        wf.writeframes(silence + b"".join(frames))
        wf.close()

    finally:
        pixels.off()
        p.terminate()
        time.sleep(0.1)

    return INPUT_FILENAME


def speech_to_text(audio_or_text):
    if args.no_pi:
        print(f"You said: {audio_or_text}")
        return audio_or_text  # Passthrough in test mode

    print("* Sending to Google Speech-to-Text...")
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
    except Exception as e:
        print(f"STT Error: {e}")
        pixels.off()
        return None
    pixels.off()
    for result in response.results:
        text = result.alternatives[0].transcript
        print(f"You said: {text}")
        return text
    return None


def text_to_speech(text):
    if args.no_pi:
        print(f"🔊 ASSISTANT (would say): {text}")
        return True  # Simulate success

    print(f"* Synthesizing speech: '{text}'")
    pixels.think()
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
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
    except Exception as e:
        print(f"TTS Error: {e}")
        pixels.off()
        return False
    with open(OUTPUT_FILENAME, "wb") as out:
        out.write(response.audio_content)
    pixels.off()
    return True


def play_audio(audio_file):
    if args.no_pi:
        # Already printed in text_to_speech for test mode
        return

    print("* Playing response...")
    pixels.speak()
    wf = wave.open(audio_file, "rb")
    p = pyaudio.PyAudio()
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
    finally:
        pixels.off()
        p.terminate()
        wf.close()


def process_intent(text):
    print(f"* Analyzing Intent with Gemini: '{text}'")
    pixels.think()

    # Context Injection: Fetch patient schedules to help Gemini infer the name
    try:
        conn = get_db_connection()
        patients = conn.execute("SELECT name, time_due FROM patients").fetchall()
        conn.close()

        patient_context = "Current Patient List: " + ", ".join(
            [f"{p['name']} (Due: {p['time_due']})" for p in patients]
        )
        current_time = datetime.now().strftime("%H:%M")
        full_prompt = (
            f"Current Time: {current_time}. {patient_context}. User says: '{text}'"
        )

    except Exception as e:
        print(f"DB Context Error: {e}")
        full_prompt = text

    try:
        response = model.generate_content(full_prompt)
        cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(cleaned_text)
        print(f"Gemini Intent: {data}")
        return data
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {
            "intent": "UNKNOWN",
            "response": "I'm having trouble understanding right now.",
        }


def send_whatsapp_alert(patient_name):
    """Send a WhatsApp notification to the caregiver."""
    token = os.getenv("WHATSAPP_API_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    caregiver_number = os.getenv("CAREGIVER_PHONE_NUMBER")

    if not all([token, phone_number_id, caregiver_number]):
        print("!!! WHATSAPP_ERROR: Missing one or more environment variables.")
        return

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # IMPORTANT: 'medication_alert' is a pre-approved message template in Meta Business Manager.
    # It must contain one variable parameter like: "Alert: {{1}} has missed their medication."
    payload = {
        "messaging_product": "whatsapp",
        "to": caregiver_number,
        "type": "template",
        "template": {
            "name": "medication_alert",
            "language": {"code": "en_US"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": patient_name}]}],
        },
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes
        print(f"✅ WhatsApp Alert Sent Successfully for {patient_name}!")
    except requests.exceptions.RequestException as e:
        print(f"!!! WHATSAPP_ERROR: Failed to send alert for {patient_name}.")
        print(f"    Error: {e}")
        print(f"    Response: {response.text if 'response' in locals() else 'N/A'}")


def run_reminder_flow(patient_name, medicine, time_due):
    print(f"\n--- Starting Reminder Flow for {patient_name} ---")

    reminders_count = 0
    max_reminders = 4

    # 1. Play Reminder 1 with medication details
    text_to_speech(f"Hello {patient_name}. It's {time_due}, time for your {medicine}.")
    play_audio(OUTPUT_FILENAME)

    while reminders_count < max_reminders:
        print(f"\n[Reminder Loop: {reminders_count + 1}/{max_reminders}]")

        # Listen for response
        audio_file = record_audio()
        text = speech_to_text(audio_file)

        if not text:
            # NO RESPONSE -> Wait 15 mins (simulated 5s) -> Check Pillbox (Voice)
            print("* No response. Waiting 5 seconds (simulated 15 mins)...")
            time.sleep(5)

            # Check pillbox (Simulated by asking again)
            text_to_speech(
                "I noticed you haven't responded. Did you open your pillbox?"
            )
            play_audio(OUTPUT_FILENAME)

            audio_file = record_audio()
            text = speech_to_text(audio_file)

            if text and "yes" in text.lower():
                text_to_speech("Great. Recording that you took it.")
                play_audio(OUTPUT_FILENAME)
                log_medication(patient_name, "TAKEN")
                return
            else:
                # No -> Send Alert -> End
                print("* Sending WhatsApp Alert...")
                send_whatsapp_alert(patient_name) # Call the function here
                text_to_speech(
                    f"Alerting caregiver that {patient_name} has not taken medication."
                )
                play_audio(OUTPUT_FILENAME)
                log_medication(patient_name, "MISSED")
                return

        # Analyze Intent
        intent_data = process_intent(text)

        if (
            intent_data["intent"] == "MEDICATION_LOG"
            and intent_data.get("status") == "TAKEN"
        ) or (
            intent_data["intent"] == "CONFIRMATION"
            and intent_data.get("value") == "YES"
        ):
            # "Already took it" or "Yes" -> End
            log_medication(patient_name, "TAKEN")
            text_to_speech("Thank you. Have a nice day.")
            play_audio(OUTPUT_FILENAME)
            return

        elif intent_data["intent"] == "DELAY":
            # "I will take it in 5 mins" -> Wait 5 mins (simulated 5s) -> Check Pillbox
            print("* User requested delay. Waiting 5 seconds (simulated 5 mins)...")
            text_to_speech("Okay, waiting 5 minutes.")
            play_audio(OUTPUT_FILENAME)
            time.sleep(5)

            text_to_speech("Five minutes have passed. Did you take your medicine?")
            play_audio(OUTPUT_FILENAME)

            audio_file = record_audio()
            text = speech_to_text(audio_file)

            # Re-process intent for the follow-up
            intent_data = process_intent(text)

            if (
                (
                    intent_data["intent"] == "MEDICATION_LOG"
                    and intent_data.get("status") == "TAKEN"
                )
                or (
                    intent_data["intent"] == "CONFIRMATION"
                    and intent_data.get("value") == "YES"
                )
                or (text and "yes" in text.lower())
            ):  # Fallback text check
                log_medication(patient_name, "TAKEN")
                text_to_speech("Great. Recorded.")
                play_audio(OUTPUT_FILENAME)
                return
            else:
                # Loop back if reminders < 4
                reminders_count += 1
                if reminders_count < max_reminders:
                    text_to_speech("Please take your medicine.")
                    play_audio(OUTPUT_FILENAME)
                continue

        elif (
            intent_data["intent"] == "CONFIRMATION" and intent_data.get("value") == "NO"
        ):
            # "No" -> Loop back (reminder)
            text_to_speech("Please take your medicine now.")
            play_audio(OUTPUT_FILENAME)
            reminders_count += 1
            continue

        else:
            # Unclear/Other -> Loop back
            reminders_count += 1
            if reminders_count < max_reminders:
                text_to_speech("I didn't understand. Please take your medicine.")
                play_audio(OUTPUT_FILENAME)

    # If loop finishes (max reminders reached)
    print("* Max reminders reached. Sending Alert...")
    send_whatsapp_alert(patient_name) # And also call it here
    text_to_speech("Max reminders reached. Sending WhatsApp alert.")
    play_audio(OUTPUT_FILENAME)
    log_medication(patient_name, "MISSED")


def main():
    try:
        conn = get_db_connection()
        patients = conn.execute(
            "SELECT name, medicine, time_due FROM patients ORDER BY id"
        ).fetchall()
        conn.close()

        for patient in patients:
            run_reminder_flow(patient["name"], patient["medicine"], patient["time_due"])
            print(
                f"--- Finished flow for {patient['name']}. Starting next in 3 seconds... ---"
            )
            time.sleep(3)

    except KeyboardInterrupt:
        print("\nExiting...")
        pixels.off()
    except Exception as e:
        print(f"Error: {e}")
        pixels.off()


if __name__ == "__main__":
    main()
