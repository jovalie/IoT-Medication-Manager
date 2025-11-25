import pyaudio
import wave
import sys
import os
import time

# Add the interfaces directory to the path so we can import Pixels
sys.path.append(os.path.join(os.path.dirname(__file__), "interfaces"))

try:
    from pixels import pixels
except ImportError:
    print("Could not import pixels. Please check your project structure.")
    sys.exit(1)

# Audio Configuration
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 2
RESPEAKER_WIDTH = 2
# Index might need adjustment depending on the device.
# Run recording_examples/get_device_index.py if needed.
RESPEAKER_INDEX = 2
CHUNK = 1024
RECORD_SECONDS = 5
WAVE_OUTPUT_FILENAME = "output.wav"


def main():
    # Pixels (LEDs) is already initialized on import

    # Initialize PyAudio
    p = pyaudio.PyAudio()

    try:
        stream = p.open(
            rate=RESPEAKER_RATE,
            format=p.get_format_from_width(RESPEAKER_WIDTH),
            channels=RESPEAKER_CHANNELS,
            input=True,
            input_device_index=RESPEAKER_INDEX,
        )
    except Exception as e:
        print(f"Error initializing audio stream: {e}")
        print(
            "Please verify RESPEAKER_INDEX using recording_examples/get_device_index.py"
        )
        pixels.off()
        time.sleep(1)
        sys.exit(1)

    print(f"* Recording for {RECORD_SECONDS} seconds...")

    # Turn on LEDs to indicate listening/recording
    pixels.listen()

    frames = []

    try:
        for i in range(0, int(RESPEAKER_RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK)
            frames.append(data)
    except KeyboardInterrupt:
        print("\nRecording stopped by user")
    except Exception as e:
        print(f"Error during recording: {e}")
    finally:
        print("* Done recording")

        # Turn off LEDs
        pixels.off()
        time.sleep(0.1)

        # Stop recording stream
        if "stream" in locals():
            stream.stop_stream()
            stream.close()

    # Save to WAV file
    try:
        wf = wave.open(WAVE_OUTPUT_FILENAME, "wb")
        wf.setnchannels(RESPEAKER_CHANNELS)
        wf.setsampwidth(p.get_sample_size(p.get_format_from_width(RESPEAKER_WIDTH)))
        wf.setframerate(RESPEAKER_RATE)
        wf.writeframes(b"".join(frames))
        wf.close()
        print(f"Audio saved to {WAVE_OUTPUT_FILENAME}")
    except Exception as e:
        print(f"Error saving file: {e}")
        p.terminate()
        return

    # Playback for debugging
    print("Playing back recorded audio...")
    try:
        wf = wave.open(WAVE_OUTPUT_FILENAME, "rb")

        # Open output stream
        stream_out = p.open(
            format=p.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True,
        )

        data = wf.readframes(CHUNK)
        while data:
            stream_out.write(data)
            data = wf.readframes(CHUNK)

        stream_out.stop_stream()
        stream_out.close()
        wf.close()
        print("Playback finished")
    except Exception as e:
        print(f"Error during playback: {e}")
    finally:
        p.terminate()


if __name__ == "__main__":
    main()
