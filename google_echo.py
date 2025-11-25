import os
import sys
import time
import wave
import pyaudio
import audioop
import json

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
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 2
RESPEAKER_WIDTH = 2
RESPEAKER_INDEX = 2  # Adjust if needed
CHUNK = 1024
INPUT_FILENAME = "input_request.wav"
OUTPUT_FILENAME = "output_response.wav"
GEMINI_MODEL_NAME = "gemini-2.5-flash"

# Silence detection settings
SILENCE_THRESHOLD = 500  # Adjust based on your microphone and environment
SILENCE_DURATION = 2.0  # Seconds of silence to stop recording
MAX_RECORD_SECONDS = 10  # Maximum recording length safety

# Check credentials
if not os.path.exists(CREDENTIALS_FILE):
    print(f"Error: {CREDENTIALS_FILE} not found!")
    print("Please download your service account key from Google Cloud Console,")
    print("rename it to 'google_credentials.json', and place it in this folder.")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE

# Initialize Vertex AI
try:
    with open(CREDENTIALS_FILE, "r") as f:
        creds_data = json.load(f)
        project_id = creds_data.get("project_id")
        if not project_id:
            print("Error: Could not find 'project_id' in google_credentials.json")
            sys.exit(1)

    vertexai.init(project=project_id, location="us-central1")

    # Initialize the model with the persona
    model = GenerativeModel(
        GEMINI_MODEL_NAME,
        system_instruction=[
            "You are a helpful medication manager.",
            "Your goal is to assist users with remembering their medications, tracking usage, and answering health-related questions safely.",
            "Keep your responses concise and spoken-friendly.",
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

            # Check for silence
            # We calculate RMS of the audio chunk
            rms = audioop.rms(data, 2)  # width=2 for 16-bit audio

            if rms < SILENCE_THRESHOLD:
                silent_chunks += 1
            else:
                silent_chunks = 0

            # Stop if silence is long enough
            if silent_chunks > max_silent_chunks:
                print("* Silence detected, stopping recording.")
                break

            # Stop if too long
            if chunk_count > max_total_chunks:
                print("* Max duration reached, stopping recording.")
                break

        stream.stop_stream()
        stream.close()

        # Save to file
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

    # Configure for the ReSpeaker audio format
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RESPEAKER_RATE,
        language_code="en-US",
        audio_channel_count=RESPEAKER_CHANNELS,  # Important for ReSpeaker
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

    print("No speech detected.")
    return None


def text_to_speech(text):
    print(f"* Synthesizing speech: '{text}'")
    pixels.think()  # Use think color for processing

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)

    # Build the voice request
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US", ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
    )

    # Select the type of audio file you want returned
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


def ask_gemini(text):
    print(f"* Asking Gemini: '{text}'")
    pixels.think()
    try:
        response = model.generate_content(text)
        print(f"Gemini response: {response.text}")
        return response.text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "I'm sorry, I'm having trouble thinking right now."


def main():
    try:
        # 1. Record
        audio_file = record_audio()

        # 2. Transcribe
        text = speech_to_text(audio_file)

        if text:
            # 3. Ask Gemini
            response_text = ask_gemini(text)

            # 4. Synthesize Response
            success = text_to_speech(response_text)

            if success:
                # 5. Playback
                play_audio(OUTPUT_FILENAME)
        else:
            # No speech detected
            print("No speech detected, playing apology...")
            success = text_to_speech("I'm sorry, I didn't hear what you said.")
            if success:
                play_audio(OUTPUT_FILENAME)

    except KeyboardInterrupt:
        print("\nExiting...")
        pixels.off()
    except Exception as e:
        print(f"Error: {e}")
        pixels.off()


if __name__ == "__main__":
    main()
