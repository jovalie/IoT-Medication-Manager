import os
import sys
import time
import wave
import pyaudio
import audioop
import json
import sqlite3
from datetime import datetime
import random

# Add interfaces path
sys.path.append(os.path.join(os.path.dirname(__file__), "interfaces"))

try:
    from pixels import pixels
except ImportError:
    print("Could not import pixels. Check project structure.")
    sys.exit(1)

from google.cloud import speech
from google.cloud import texttospeech
import vertexai
from vertexai.generative_models import GenerativeModel

# Configuration
CREDENTIALS_FILE = "google_credentials.json"
DB_NAME = "medication_manager.db"
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 2
RESPEAKER_WIDTH = 2
RESPEAKER_INDEX = 2  # Adjust if needed
CHUNK = 1024
INPUT_FILENAME = "input_request.wav"
OUTPUT_FILENAME = "output_response.wav"
GEMINI_MODEL_NAME = "gemini-2.5-flash"

# Silence detection settings
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 2.0
MAX_RECORD_SECONDS = 10


# Database Helper
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
        silence = b'\x00' * int(RESPEAKER_RATE * RESPEAKER_WIDTH * 0.5)
        
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


def speech_to_text(audio_file):
    print("* Sending to Google Speech-to-Text...")
    pixels.think()
    client = speech.SpeechClient()
    with open(audio_file, "rb") as audio:
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


def run_reminder_flow(patient_name="Grandpa Joe"):
    print(f"\n--- Starting Reminder Flow for {patient_name} ---")

    reminders_count = 0
    max_reminders = 4

    # 1. Play Reminder 1
    text_to_speech(f"Hello {patient_name}. Please take your medicine.")
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
    text_to_speech("Max reminders reached. Sending WhatsApp alert.")
    play_audio(OUTPUT_FILENAME)
    log_medication(patient_name, "MISSED")


def main():
    try:
        # For testing, jump straight into the flow for Grandpa Joe
        run_reminder_flow("Grandpa Joe")

    except KeyboardInterrupt:
        print("\nExiting...")
        pixels.off()
    except Exception as e:
        print(f"Error: {e}")
        pixels.off()


if __name__ == "__main__":
    main()
