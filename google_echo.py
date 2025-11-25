import os
import sys
import time
import wave
import pyaudio
import audioop
import json
import sqlite3
from datetime import datetime

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
        # In a real scenario, might need clarification if duplicates exist
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
            "Possible intents: 'MEDICATION_LOG', 'NEW_PATIENT', 'UNKNOWN'.",
            "Structure for MEDICATION_LOG: { 'intent': 'MEDICATION_LOG', 'patient_name': '...', 'status': 'TAKEN'/'MISSED', 'notes': '...' }",
            "Structure for NEW_PATIENT: { 'intent': 'NEW_PATIENT', 'name': '...', 'medicine': '...', 'time': '...' }",
            "Structure for UNKNOWN: { 'intent': 'UNKNOWN', 'response': '...' }",
            "If the user says 'I took my meds' and doesn't specify a name, infer the patient name based on who has a medication due around the current time. If unsure, return intent: UNKNOWN with response asking for the name."
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

        wf = wave.open(INPUT_FILENAME, "wb")
        wf.setnchannels(RESPEAKER_CHANNELS)
        wf.setsampwidth(p.get_sample_size(p.get_format_from_width(RESPEAKER_WIDTH)))
        wf.setframerate(RESPEAKER_RATE)
        wf.writeframes(b"".join(frames))
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
        
        patient_context = "Current Patient List: " + ", ".join([f"{p['name']} (Due: {p['time_due']})" for p in patients])
        current_time = datetime.now().strftime("%H:%M")
        full_prompt = f"Current Time: {current_time}. {patient_context}. User says: '{text}'"
        
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


def main():
    try:
        # 1. Record
        audio_file = record_audio()

        # 2. Transcribe
        text = speech_to_text(audio_file)

        if text:
            # 3. Analyze Intent
            intent_data = process_intent(text)

            response_speech = ""

            if intent_data["intent"] == "MEDICATION_LOG":
                success, msg = log_medication(
                    intent_data["patient_name"],
                    intent_data["status"],
                    intent_data.get("notes"),
                )
                if success:
                    response_speech = f"Okay, I've marked {intent_data['patient_name']} as {intent_data['status']}."
                else:
                    response_speech = f"I couldn't log that because {msg}"

            elif intent_data["intent"] == "NEW_PATIENT":
                # Simplified: In a real app, this would be a multi-turn convo.
                # Here we assume the user said everything in one go or Gemini extracted partials.
                name = intent_data.get("name")
                medicine = intent_data.get("medicine")
                time_due = intent_data.get("time")

                if name and medicine:
                    add_new_patient(name, medicine, time_due)
                    response_speech = f"I've added {name} taking {medicine}."
                else:
                    response_speech = (
                        "To add a patient, please say their name, medicine, and time."
                    )

            else:
                response_speech = intent_data.get(
                    "response", "I didn't quite catch that."
                )

            # 4. Synthesize Response
            success = text_to_speech(response_speech)
            if success:
                play_audio(OUTPUT_FILENAME)
        else:
            text_to_speech("I didn't hear anything.")
            play_audio(OUTPUT_FILENAME)

    except KeyboardInterrupt:
        print("\nExiting...")
        pixels.off()
    except Exception as e:
        print(f"Error: {e}")
        pixels.off()


if __name__ == "__main__":
    main()
