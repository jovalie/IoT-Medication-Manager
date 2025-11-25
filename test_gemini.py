import os
import sys
import json
import vertexai
from vertexai.generative_models import GenerativeModel

# Configuration
CREDENTIALS_FILE = "google_credentials.json"

# List of models to try in order
MODELS_TO_TRY = [
    "gemini-1.5-flash-001",
    "gemini-1.5-flash",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro",
    "gemini-1.0-pro",
    "gemini-pro"
]

def test_gemini():
    print("--- Gemini API Test Script ---")
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"FAIL: {CREDENTIALS_FILE} not found!")
        return False
    print(f"PASS: {CREDENTIALS_FILE} found.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE

    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
            project_id = creds_data.get('project_id')
        
        print(f"INFO: Using Project ID: {project_id}")
        vertexai.init(project=project_id, location="us-central1")
        print("PASS: Vertex AI initialized.")
    except Exception as e:
        print(f"FAIL: Initialization error: {e}")
        return False

    for model_name in MODELS_TO_TRY:
        print(f"\nTrying model: {model_name}...")
        try:
            model = GenerativeModel(model_name)
            response = model.generate_content("Say 'Hello' if you hear me.")
            print(f"SUCCESS with {model_name}!")
            print(f"Response: {response.text}")
            return True
        except Exception as e:
            print(f"Failed with {model_name}: {e}")
    
    print("\nFAIL: All models failed.")
    return False

if __name__ == "__main__":
    success = test_gemini()
    sys.exit(0 if success else 1)
