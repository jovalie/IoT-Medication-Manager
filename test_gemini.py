import os
import sys
import json
import vertexai
from vertexai.generative_models import GenerativeModel

# Configuration
CREDENTIALS_FILE = "google_credentials.json"
GEMINI_MODEL_NAME = "gemini-1.5-flash-001"  # Fallback/Safe model for testing

def test_gemini():
    print("--- Gemini API Test Script ---")
    
    # 1. Check Credentials File
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"FAIL: {CREDENTIALS_FILE} not found!")
        return False
    print(f"PASS: {CREDENTIALS_FILE} found.")

    # 2. Set Environment Variable
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE
    print("PASS: Environment variable set.")

    # 3. Load Project ID and Initialize Vertex AI
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
            project_id = creds_data.get('project_id')
            if not project_id:
                print("FAIL: 'project_id' missing in JSON.")
                return False
        
        print(f"INFO: Using Project ID: {project_id}")
        vertexai.init(project=project_id, location="us-central1")
        print("PASS: Vertex AI initialized.")
    except Exception as e:
        print(f"FAIL: Initialization error: {e}")
        return False

    # 4. Initialize Model
    try:
        model = GenerativeModel(GEMINI_MODEL_NAME)
        print(f"PASS: Model '{GEMINI_MODEL_NAME}' object created.")
    except Exception as e:
        print(f"FAIL: Model creation error: {e}")
        return False

    # 5. Send Test Request
    print(f"\nSending test prompt to {GEMINI_MODEL_NAME}...")
    try:
        response = model.generate_content("Say 'Hello, I am working!' if you can hear me.")
        print("\n--- Response from Gemini ---")
        print(response.text)
        print("-----------------------------")
        print("PASS: Successfully received response!")
        return True
    except Exception as e:
        print(f"\nFAIL: API Request failed.")
        print(f"Error details: {e}")
        return False

if __name__ == "__main__":
    success = test_gemini()
    sys.exit(0 if success else 1)

