# IoT Medication Manager - System Design

## 1. System Overview
The IoT Medication Manager is a smart assistive system designed to help patients adhere to their medication schedules. It combines a physical smart pillbox, a voice-activated assistant, and a web-based caregiver dashboard. The system is designed to run exclusively on a **Raspberry Pi** equipped with a **ReSpeaker 2-Mics Pi HAT** and interfaces with an Arduino-controlled pillbox.

## 2. Architecture

The system follows a hybrid architecture combining a local embedded control loop with cloud-based AI services.

```mermaid
graph TD
    subgraph "Hardware Layer"
        Arduino[Arduino Pillbox] -- Serial (USB) --> RPi[Raspberry Pi 4]
        ReSpeaker[ReSpeaker 2-Mics HAT] -- GPIO/SPI --> RPi
        Mic[Microphone Array] -- Audio Input --> ReSpeaker
        Speaker[Speaker] -- Audio Output --> ReSpeaker
        LEDs[APA102 LEDs] -- SPI --> ReSpeaker
    end

    subgraph "Application Layer (Flask App)"
        VoiceThread[Voice Assistant Thread]
        PillboxThread[Pillbox Monitor Thread]
        WebApp[Flask Web Server]
        SocketIO[Socket.IO Server]
        DB[(SQLite Database)]
    end

    subgraph "Cloud Services (Google Cloud)"
        STT[Speech-to-Text API]
        TTS[Text-to-Speech API]
        Gemini[Vertex AI (Gemini 2.5)]
    end

    subgraph "Frontend"
        Dashboard[Caregiver Dashboard]
        Calendar[Patient Calendar]
    end

    %% Connections
    RPi --> VoiceThread
    RPi --> PillboxThread
    
    VoiceThread -- Audio Stream --> ReSpeaker
    ReSpeaker -- Audio Data --> VoiceThread
    VoiceThread -- LED Control --> LEDs
    
    VoiceThread -- Audio --> STT
    STT -- Text --> Gemini
    Gemini -- Intent --> VoiceThread
    VoiceThread -- Text --> TTS
    TTS -- Audio --> Speaker
    
    PillboxThread -- Events --> DB
    VoiceThread -- Logs --> DB
    
    WebApp -- Reads/Writes --> DB
    WebApp -- Updates --> SocketIO
    SocketIO -- Real-time Data --> Dashboard
```

## 3. Components

### 3.1. Web Application (Flask)
*   **Role:** Serves the caregiver dashboard and API endpoints.
*   **Framework:** Flask (Python).
*   **Real-time Communication:** `flask_socketio` is used to push alerts and status updates to the browser immediately.
*   **Routes:**
    *   Dashboard view for monitoring all patients.
    *   Patient management (add new patient).
    *   Calendar views for medication history.

### 3.2. Voice Assistant Core
*   **Role:** Handles voice interaction with the patient.
*   **Execution:** Runs as a background daemon thread (`start_voice_assistant`).
*   **Hardware Integration:**
    *   **Audio Input:** Uses `pyaudio` configured specifically for the ReSpeaker HAT (Rate: 16000Hz, Channels: 2, Width: 2 bytes, Device Index: 2). It captures audio in chunks (1024 frames) and saves the stream to a local WAV file for processing, following the hardware validation script `record_with_leds.py`.
    *   **Visual Feedback:** Uses the `interfaces/pixels.py` library to control the on-board APA102 LEDs via SPI.
        *   **Listen Mode:** LEDs light up to indicate the microphone is active.
        *   **Think Mode:** LEDs animate while processing with Google Cloud/Gemini.
        *   **Speak Mode:** LEDs pulse while TTS audio is playing.
    *   **Logic:** Manages a state machine for reminders (Reminder -> Listen -> Confirm/Delay/Missed).

### 3.3. Hardware Interface
*   **Pillbox Monitor:** A dedicated background thread (`monitor_pillbox`) reads from the serial port (`/dev/ttyACM0`). It detects `OPENEVENT:<Day>` messages from the Arduino to confirm physical medication intake.
*   **ReSpeaker 2-Mics Pi HAT:**
    *   Provides the microphone array for far-field voice capture.
    *   Provides the 3.5mm audio jack for the speaker.
    *   Hosts the APA102 RGB LEDs for status indication.

### 3.4. External Services (Google Cloud)
*   **Speech-to-Text (STT):** Converts user voice response to text.
*   **Vertex AI (Gemini):** Analyzes the text to determine user intent (`CONFIRMATION`, `DELAY`, `UNKNOWN`).
*   **Text-to-Speech (TTS):** Synthesizes system responses.

## 4. Data Model (SQLite)

The system uses a local SQLite database (`medication_manager.db`) with two main tables:

### `patients`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER (PK) | Unique patient ID |
| `name` | TEXT | Patient name |
| `medicine` | TEXT | Name of the medication |
| `time_due` | TEXT | Scheduled time (e.g., "10:00") |

### `medication_logs`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER (PK) | Unique log ID |
| `patient_id` | INTEGER (FK) | Reference to `patients.id` |
| `date` | TEXT | Date of the log (YYYY-MM-DD) |
| `time_taken` | TEXT | Time when taken (HH:MM:SS) |
| `status` | TEXT | `TAKEN`, `MISSED`, `PENDING` |
| `notes` | TEXT | Additional info (e.g., "Taken via pillbox") |

## 5. Key Workflows

### 5.1. Medication Reminder Flow
1.  System checks if medication is already `TAKEN`.
2.  If not, TTS announces: "Hello [Name], it's time for your [Medicine]."
3.  **LEDs:** Switch to `pixels.listen()`.
4.  System records audio response via ReSpeaker mic.
5.  **LEDs:** Switch to `pixels.think()`.
6.  STT converts audio to text.
7.  Gemini analyzes intent:
    *   **YES/CONFIRM:** Log as `TAKEN`, play confirmation.
    *   **DELAY:** Wait 5 minutes (or until pillbox event), then retry.
    *   **NO/SILENCE:** Retry up to 3 times, then log as `MISSED` and alert caregiver.
8.  **LEDs:** Switch to `pixels.off()` when idle.

### 5.2. Pillbox Event Flow
1.  Arduino detects compartment open.
2.  Sends `OPENEVENT:<Day>` via Serial.
3.  `monitor_pillbox` thread receives event.
4.  Checks if the opened day matches the current day.
5.  If valid, logs medication as `TAKEN` in DB.
6.  Emits socket event to update Dashboard.
7.  Signals the main voice thread to stop reminding.

### 5.3. Caregiver Dashboard Flow
1.  Caregiver accesses `/caregiver`.
2.  Server renders HTML with current day's status for all patients.
3.  Socket.IO client connects.
4.  When a patient takes meds (Voice or Pillbox), server emits `status_update`.
5.  Dashboard updates the status color (Green/Red/Orange) instantly.
6.  If a patient misses meds or delays too much, an alert popup appears.

## 6. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/patient/<id>/logs` | Returns JSON list of logs for a specific patient (for calendar). |
| `GET` | `/api/logs/all` | Returns JSON list of all logs for all patients. |
| `POST` | `/patient/create` | Creates a new patient record. |
| `POST` | `/admin/reset_status` | Resets all statuses to PENDING for the current day (Demo tool). |

## 7. Hardware Requirements
*   **Raspberry Pi 4** (Required)
*   **ReSpeaker 2-Mics Pi HAT** (Required for Audio & LEDs)
*   **Arduino Uno/Nano** (Required for Pillbox control)
*   **USB Speaker** (Connected to ReSpeaker Audio Jack)
*   **Magnetic Reed Switches** (for Pillbox compartments)

## 8. Demo Scenarios
For the purposes of this demo, there is only one hardware pillbox (all serial connectivity is to the same device) and all example users will be using the same hardware.

### 8.1. Student Hamad
*   **Behavior:** Takes medication immediately.
*   **Action:** Opens the pillbox compartment directly.
*   **Voice Interaction:** None.
*   **Outcome:** Status updates to `TAKEN` immediately upon pillbox event.

### 8.2. Athlete Joan
*   **Behavior:** Delays initially, then takes medication.
*   **Action:**
    1.  System reminds.
    2.  Joan says: "Five more minutes."
    3.  System acknowledges delay.
    4.  Joan opens the pillbox compartment.
*   **Outcome:** Status updates to `TAKEN` upon pillbox event.

### 8.3. Uncle Sam
*   **Behavior:** Misses medication completely.
*   **Action:**
    1.  System reminds.
    2.  Sam does not respond (silence/timeout).
    3.  System retries 3 times.
*   **Outcome:** Status updates to `MISSED`. Caregiver dashboard receives an alert.

### 8.4. Grandpa Albert
*   **Behavior:** Delays repeatedly, triggers alert, then takes medication.
*   **Action:**
    1.  System reminds.
    2.  Albert says: "Five more minutes." (Delay 1)
    3.  System reminds again.
    4.  Albert says: "Five more minutes." (Delay 2)
    5.  System reminds again.
    6.  Albert says: "Five more minutes." (Delay 3 - Max Reached)
    7.  System triggers caregiver alert for "Exceeded max delays".
    8.  Albert opens the pillbox compartment.
*   **Outcome:** Status updates to `TAKEN` (overriding the alert state). Caregiver sees the final success.
