# Requirements Overview: Patient Medication Interview & Dashboard

## 1. Project Scope
The goal is to expand the IoT Medication Manager to proactively "interview" the patient about their daily medication and visualize this data on a local Web Dashboard. 

**Constraint:** The system currently tracks a single daily dose event (e.g., "Once a Day" regimen).

---

## 2. Voice User Interface (VUI) Requirements

### 2.1. The Interview Flow
The system must be able to initiate or respond to a conversation to determine medication adherence.

*   **Primary Question:** "Have you taken your medication for today?"
*   **Secondary Question (Optional):** "How are you feeling?" (for sentiment/notes).

### 2.2. Intent Classification (Powered by Gemini 2.5 Flash)
The LLM must process the user's spoken response and categorize it into one of three states:
1.  **CONFIRMED**: User said "Yes", "I took it this morning", "Yup", etc.
2.  **DENIED**: User said "No", "Not yet", "I forgot".
3.  **UNCLEAR**: User said something unrelated (e.g., "It's raining outside").

### 2.3. Dialog Management
*   **If Confirmed:** System responds positively (e.g., "Great, I've marked that down. Have a good day.") and ends the session.
*   **If Denied:** System offers a reminder (e.g., "Okay, please remember to take it soon.") and marks status as 'Pending'.
*   **If Unclear:** System asks for clarification once, then exits if still unclear.

---

## 3. Data persistence Requirements

To support the Calendar UI, data must be stored persistently on the Raspberry Pi.

### 3.1. Database Schema (SQLite recommended)
Two tables to support multiple patients:

**Table `patients`**
*   `id`: Primary Key
*   `name`: TEXT (e.g., "Grandpa Joe")

**Table `medication_logs`**
*   `id`: Primary Key
*   `patient_id`: Foreign Key linking to `patients.id`
*   `date`: YYYY-MM-DD
*   `time_taken`: Timestamp
*   `status`: TEXT ('TAKEN', 'MISSED', 'PENDING')
*   `notes`: TEXT (Optional transcript of how they felt)
*   **Constraint:** Unique combination of (`patient_id`, `date`)

---

## 4. Web UI Requirements

A lightweight web server hosted on the Raspberry Pi (accessible via local network IP).

### 4.0. Patient Selection
*   **Landing Page:** Select which patient profile to view or manage.

### 4.1. Dashboard View (Home)
*   **Current Status:** Big visual indicator for *Today* (e.g., Large Green Checkmark or Orange "Waiting").
*   **Action Button:** A manual "I took my meds" button (in case voice interaction isn't used).

### 4.2. Calendar View
*   **Monthly Grid:** Visual representation of the month.
*   **Color Coding:**
    *   🟢 **Green:** Taken
    *   🔴 **Red:** Missed (Day passed without confirmation)
    *   ⚪ **Gray/Empty:** Future dates

### 4.3. Technical Stack
*   **Backend:** Python Flask (integrates easily with our existing Python scripts).
*   **Frontend:** HTML/CSS/JavaScript (Minimal dependencies).
*   **Hosting:** Runs on port 5000 on the Pi.

---

## 5. Technical Workflow

1.  **Trigger:** User runs the script (or a cron job runs it at a set time).
2.  **Recording:** `google_echo.py` records audio.
3.  **Transcription:** Google STT converts audio to text.
4.  **Analysis:** Gemini 2.5 analyzes the text and returns a JSON object (e.g., `{"taken": true, "sentiment": "neutral"}`).
5.  **Storage:** Python script inserts/updates the SQLite database.
6.  **Feedback:** Google TTS speaks the confirmation.
7.  **Visualization:** User refreshes the Web UI to see the calendar update.

