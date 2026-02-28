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
APP_NAME = "บัตรภาพอัจฉริยะ V2.0"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
FPS = 60
CONFIDENCE_THRESHOLD = 0.8

# --- Flashcard Categories ---
# Maps Units to their respective categories and SIFT pattern prefixes.
# Unit 1: Clothing (เครื่องแต่งกาย)
# Unit 2: Appliances (เครื่องใช้) - Placeholder
UNIT_DATA = {
    "Unit1": {
        "title": "เครื่องแต่งกายพิ้นฐาน",
        "cards": {
            "เสื้อนักเรียน": {"patterns": ["b_shirt", "g_shirt"], "aliases": ["เสื้อ"]},
            "กางเกง": {"patterns": ["b_short"], "aliases": []},
            "กระโปรง": {"patterns": ["g_skirt"], "aliases": []},
            "รองเท้า": {"patterns": ["b_shoe", "g_shoe"], "aliases": ["เท้า"]},
            "ถุงเท้า": {"patterns": ["b_sock", "g_sock"], "aliases": []}
        }
    },
    "Unit2": {
        "title": "เครื่องแต่งกายเสริม",
        "cards": {
            "หมวก" : {"patterns": ["b_hat","g_hat"], "aliases": ["หมวกปีก"]},
            "นาฬิกา" : {"patterns": ["watch"], "aliases": []},
            "แว่นตา" : {"patterns": ["glasses"], "aliases": ["แว่น"]},
            "กิ๊บ": {"patterns": ["clip"], "aliases": ["คลิป", "กิ๊บหนีบผม"]},
            "ต่างหู": {"patterns": ["ear_ring"], "aliases": []},
            "เข็มขัด": {"patterns": ["belt"], "aliases": []}
        } 
    },
    "Unit3": { "title": "ทักษะการแต่งกาย", "cards": {
        "การสวมใส่": {"patterns": [
            "bst_wear","bss_wear","bs_wear",
            "gss_wear","gst_wear",
        ], "aliases": []},
        "การถอด": {"patterns": ["gs_unwear","bs_unwear"], "aliases": []},
        "การเปลี่ยนเสื้อผ้า": {"patterns": ["bc_cloth","gc_cloth"], "aliases": []},
        "ความเรียบร้อย": {"patterns": ["bp","gp"], "aliases": []},
    } },
    "Unit4": { "title": "สีสันและลวดลาย", "cards": {
        "เสื้อสีอ่อน": {"patterns": ["lw"], "aliases": []},
        "เสื้อสีเข้ม": {"patterns": ["dw"], "aliases": []},
        "เสื้อลายดอก": {"patterns": ["fw"], "aliases": []},
        "เสื้อลายทาง": {"patterns": ["zw"], "aliases": []},
    } },
    "Unit5": { "title": "การดูแลรักษาเครื่องแต่งกาย", "cards": {
        "เก็บเข้าตู้": {"patterns": ["kw","kwc"], "aliases": []},
        "รีดผ้า": {"patterns": ["iw"], "aliases": []},
        "พับผ้า": {"patterns": ["fdw"], "aliases": []},
        "ตากผ้า": {"patterns": ["drw"], "aliases": []},
        "ขจัดคราบ": {"patterns": ["ctw"], "aliases": []},
        "ซักผ้า": {"patterns": ["cw"], "aliases": []},
    } },
    "Unit6": { "title": "การแต่งกายตามสภาพอากาศและโอกาสต่างๆ", "cards": {
        "อากาศหนาว": {"patterns": ["cold"], "aliases": []},
        "อากาศร้อน": {"patterns": ["hot"], "aliases": []},
        "ฝนตก": {"patterns": ["rain"], "aliases": []},
        "ไปวัด": {"patterns": ["gt"], "aliases": []},
        "ไปโรงเรียน": {"patterns": ["gsc"], "aliases": []},
        "ไปทะเล": {"patterns": ["gsa"], "aliases": []},
        "ไปตลาด": {"patterns": ["gtm"], "aliases": []},
    } }
}

# Default unit for backward compatibility or initial load
CATEGORY_MAP = UNIT_DATA["Unit1"]["cards"]
FLASHCARDS = list(CATEGORY_MAP.keys())
