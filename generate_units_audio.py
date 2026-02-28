import os
import sys

# Need to import UNIT_DATA from config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from app.config import UNIT_DATA
except ImportError:
    print("Cannot import config")
    sys.exit(1)

from gtts import gTTS

output_dir = "assets/audio"
os.makedirs(output_dir, exist_ok=True)

for unit in ["Unit3", "Unit4", "Unit5", "Unit6"]:
    if unit in UNIT_DATA:
        print(f"Generating audio files for {unit}...")
        for category in UNIT_DATA[unit]["cards"].keys():
            filepath = os.path.join(output_dir, f"{category}.mp3")
            if os.path.exists(filepath):
                print(f"Skipping: {category}.mp3 (Already exists)")
                continue
                
            print(f"Generating for: {category} ({category}.mp3)")
            try:
                tts = gTTS(text=category, lang="th")
                tts.save(filepath)
            except Exception as e:
                print(f"Error generating {category}: {e}")

print("Audio generation completed.")
