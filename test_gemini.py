import os
import sys
import json
import vertexai
from vertexai.generative_models import GenerativeModel

# Configuration
CREDENTIALS_FILE = "google_credentials.json"

# List of models based on latest documentation
MODELS_TO_TRY = [
    "gemini-2.5-pro",  # Stable
    "gemini-2.5-flash",  # Stable
    "gemini-2.0-flash",  # Latest
    "gemini-2.0-flash-lite",  # Latest
    "gemini-1.5-pro-002",
    "gemini-1.5-flash-002",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


def test_gemini():
    print("--- Gemini API Test Script ---")

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"FAIL: {CREDENTIALS_FILE} not found!")
        return False
    print(f"PASS: {CREDENTIALS_FILE} found.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE

    try:
        with open(CREDENTIALS_FILE, "r") as f:
            creds_data = json.load(f)
            project_id = creds_data.get("project_id")

        print(f"INFO: Using Project ID: {project_id}")
        vertexai.init(project=project_id, location="us-central1")
        print("PASS: Vertex AI initialized.")
    except Exception as e:
        print(f"FAIL: Initialization error: {e}")
        return False

    success = False
    for model_name in MODELS_TO_TRY:
        print(f"\nTrying model: {model_name}...")
        try:
            model = GenerativeModel(model_name)
            response = model.generate_content("Say 'Hello' if you hear me.")
            print(f"SUCCESS with {model_name}!")
            print(f"Response: {response.text}")
            success = True
            break  # Stop after first success
        except Exception as e:
            print(f"Failed with {model_name}: {e}")

    if not success:
        print("\nFAIL: All models failed.")
        return False

    return True


if __name__ == "__main__":
    success = test_gemini()
    sys.exit(0 if success else 1)
