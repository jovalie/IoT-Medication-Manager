import speech_recognition as sr
from gtts import gTTS
import os
import sys
import time

# Add the interfaces directory to the path so we can import Pixels
sys.path.append(os.path.join(os.path.dirname(__file__), 'interfaces'))

try:
    from pixels import pixels
except ImportError:
    print("Could not import pixels. Please check your project structure.")
    sys.exit(1)

def listen_and_recognize():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone(device_index=2) # Using ReSpeaker index

    print("Listening...")
    pixels.listen()
    
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source)
        try:
            audio = recognizer.listen(source, timeout=5)
        except sr.WaitTimeoutError:
            print("Timeout: No speech detected")
            pixels.off()
            return None

    pixels.think()
    print("Recognizing...")
    
    try:
        # Use Google Speech Recognition
        text = recognizer.recognize_google(audio)
        print(f"You said: {text}")
        return text
    except sr.UnknownValueError:
        print("Google Speech Recognition could not understand audio")
    except sr.RequestError as e:
        print(f"Could not request results from Google Speech Recognition service; {e}")
    finally:
        pixels.off()
    
    return None

def speak_text(text):
    if not text:
        return

    print(f"Speaking: {text}")
    pixels.speak()
    
    try:
        tts = gTTS(text=text, lang='en')
        tts.save("response.mp3")
        # Use mpg321 or omxplayer to play the audio on Pi
        os.system("mpg321 response.mp3") 
    except Exception as e:
        print(f"Error in TTS: {e}")
    finally:
        pixels.off()
        if os.path.exists("response.mp3"):
            os.remove("response.mp3")

def main():
    while True:
        try:
            text = listen_and_recognize()
            if text:
                speak_text(f"You said: {text}")
            
            # Optional: Short pause before listening again
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\nExiting...")
            pixels.off()
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            pixels.off()
            break

if __name__ == "__main__":
    main()

