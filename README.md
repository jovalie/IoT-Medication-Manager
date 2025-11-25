# IoT Medication Manager (with ReSpeaker 4-Mic HAT)

A voice-controlled medication management assistant for Raspberry Pi using the ReSpeaker 4-Mic HAT. It features custom LED animations for visual feedback and uses Google Cloud services for Speech-to-Text (STT), Text-to-Speech (TTS), and Gemini 2.5 Flash for intelligent responses.

## Features

-   **Voice Interface**: Hands-free interaction using microphone array and speaker.
-   **Smart Assistant**: Powered by **Google Gemini 2.5 Flash** with a "Medication Manager" persona.
-   **Visual Feedback**:
    -   **Breathing White**: Listening (Waiting for user input)
    -   **Rotating White**: Thinking (Processing/AI generation)
    -   **Breathing Green**: Speaking (Playing response)
-   **Silence Detection**: Automatically stops recording when you stop speaking.
-   **Cloud Integration**: Uses Google Vertex AI, Cloud Speech-to-Text, and Cloud Text-to-Speech.

## Hardware Requirements

-   Raspberry Pi (Zero 2 W, 3B+, 4, or 5)
-   [ReSpeaker 4-Mic Array for Raspberry Pi](https://wiki.seeedstudio.com/ReSpeaker_4_Mic_Array_for_Raspberry_Pi/)
-   Speaker (connected via 3.5mm jack on the HAT or Pi)

## Software Requirements

-   Python 3.11+
-   Google Cloud Platform Account with enabled APIs:
    -   Cloud Speech-to-Text API
    -   Cloud Text-to-Speech API
    -   Vertex AI API

## Installation

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/jovalie/IoT-Medication-Manager.git
    cd IoT-Medication-Manager
    ```

2.  **System Dependencies**:
    ```bash
    sudo apt-get update
    sudo apt-get install portaudio19-dev python3-pyaudio
    ```

3.  **Python Dependencies**:
    It is recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Google Cloud Credentials**:
    -   Create a Service Account in Google Cloud Console.
    -   Grant it the **Vertex AI User** role.
    -   Download the JSON key file.
    -   Rename it to `google_credentials.json` and place it in the project root.

## Usage

Run the main application:

```bash
python google_echo.py
```

### Other Scripts
-   `record_with_leds.py`: Simple test script to record audio with LED feedback and play it back.
-   `test_gemini.py`: Diagnostic script to verify Google Cloud credentials and Gemini model availability.

## Technical Details

-   **Audio Recording**: Uses `pyaudio` to capture 16kHz, 16-bit linear PCM audio from the ReSpeaker array (Channel 0-1).
-   **LED Control**: Uses `spidev` and `gpiozero` to control the APA102 LEDs on the HAT via SPI.
-   **AI Backend**:
    -   **STT**: `google-cloud-speech`
    -   **TTS**: `google-cloud-texttospeech`
    -   **LLM**: `gemini-2.5-flash` via `google-cloud-aiplatform` (Vertex AI).
