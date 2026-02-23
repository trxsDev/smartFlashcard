import os
import sys

# --- PyInstaller Resource Path Helper ---
def get_resource_path(relative_path):
    """
    Get the absolute path to a resource.
    Works for development mode and for PyInstaller compiled executables.
    PyInstaller creates a temp folder and stores path in _MEIPASS.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Development mode: base path is the parent directory of 'app/'
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)

# --- Application Configuration ---
APP_NAME = "บัตรภาพอัจฉริยะ V1.0"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
FPS = 60
CONFIDENCE_THRESHOLD = 0.8

# --- Flashcard Categories ---
# Maps the Thai Category Name to the corresponding SIFT pattern image filename prefixes.
# Add new cards here and drop the corresponding .jpg files into 'card_images/'
CATEGORY_MAP = {
    "เสื้อนักเรียน": ["b_shirt", "g_shirt"],
    "กางเกง": ["b_short"],
    "กระโปรง": ["g_skirt"],
    "รองเท้า": ["b_shoe", "g_shoe"],
    "ถุงเท้า": ["b_sock", "g_sock"]
}

# The Target Words that the game loop will iterate through
FLASHCARDS = list(CATEGORY_MAP.keys())
