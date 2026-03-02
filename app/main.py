import cv2
import pygame
import speech_recognition as sr
import threading
import time
import os
import sys
import numpy as np
import json
import requests
import difflib
from enum import Enum, auto
from feature_matcher import FeatureMatcher
from config import APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, FPS, UNIT_DATA, get_resource_path


# --- State Machine ---
class GameState(Enum):
    SPLASH_SCREEN = auto()   # Initial launching screen with icon
    SETTINGS_SCREEN_STEP_1 = auto() # Select Camera with Preview
    SETTINGS_SCREEN_STEP_2 = auto() # Check Internet Connection
    LANDING_PAGE = auto()    # Main Menu Lobby
    CHAPTER_SELECT = auto()  # Chapter 1-6 UI
    MODE_SELECT = auto()     # Select game mode after chapter
    PRE_GAME_FADE = auto()   # Transition into Gameplay
    SCANNING = auto()        # Waiting for camera to find object
    WRONG_OBJECT = auto()    # Paused when wrong object is scanned
    COUNTDOWN = auto()       # Object found, counting down 3..2..1
    READING_AND_SPELLING = auto() # Show word, highlight letters, play TTS
    COUNTDOWN_PRE_LISTEN = auto() # Countdown before listening
    LISTENING = auto()       # Listening for user pronunciation
    GAME_OVER = auto()       # Max mistakes reached
    END_SCREEN_FADE = auto() # Fade out to Game Over UI
    AUDIO_SETTINGS = auto()  # Settings overlay
    PAUSED = auto()          # Pause menu during gameplay

class GameController:
    def __init__(self):
        # Initialize Pygame
        pygame.init()
        self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
        self.screen = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption(APP_NAME)
        
        # Load and set the Window Icon
        try:
            self.app_icon = pygame.image.load(get_resource_path("assets/ui/icons/icon.png")).convert_alpha()
            pygame.display.set_icon(self.app_icon)
        except:
            self.app_icon = None
            pass

        self.clock = pygame.time.Clock()
        
        # Initialize Audio Mixer & SFX
        pygame.mixer.init()
        try:
            self.sfx_correct = pygame.mixer.Sound(get_resource_path("assets/sfx/correct.mp3"))
            self.sfx_wrong = pygame.mixer.Sound(get_resource_path("assets/sfx/wrong.mp3"))
            self.sfx_hover = pygame.mixer.Sound(get_resource_path("assets/sfx/hover.mp3"))
            self.sfx_click = pygame.mixer.Sound(get_resource_path("assets/sfx/click.mp3"))
            self.sfx_new_word = pygame.mixer.Sound(get_resource_path("assets/sfx/new_word.mp3"))
            self.sfx_game_over = pygame.mixer.Sound(get_resource_path("assets/sfx/game_over.mp3"))
            self.sfx_fail = pygame.mixer.Sound(get_resource_path("assets/sfx/faild.mp3"))
        except:
            self.sfx_correct = None
            self.sfx_wrong = None
            self.sfx_hover = None
            self.sfx_click = None
            self.sfx_new_word = None
            self.sfx_game_over = None
            self.sfx_fail = None

        self.bgm_volume = 0.5
        self.sfx_volume = 0.8
        self.update_sfx_volume()
        
        # Load BGM
        try:
            pygame.mixer.music.load(get_resource_path("assets/sfx/bgm.mp3"))
            pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
            # BGM will be played after SPLASH_SCREEN finishes
        except:
            print(f"Warning: {get_resource_path('assets/sfx/bgm.mp3')} not found!")

        self.hovered_buttons = set() # Track hover state to play sound only once

        # Fonts (Using Mali to match the UI style and support Thai characters)
        font_bold = get_resource_path("assets/fonts/Mali/Mali-Bold.ttf")
        font_regular = get_resource_path("assets/fonts/Mali/Mali-Regular.ttf")
        
        self.font_title = pygame.font.Font(font_bold, 75)
        self.font_large = pygame.font.Font(font_bold, 60)
        self.font_medium = pygame.font.Font(font_bold, 40)
        self.font_small = pygame.font.Font(font_regular, 25)
        self.font_tiny = pygame.font.Font(font_regular, 18)

        # Camera Setup Variables
        self.available_cameras = self.check_available_cameras()
        self.current_camera_index = self.load_camera_config()
        self.cap = None
        # Start camera immediately for preview in Step 1
        if self.available_cameras:
            self.init_camera(self.available_cameras[self.current_camera_index])

        # Network Check
        self.network_status = "รอการตรวจสอบ..."
        self.is_checking_network = False
        
        # Initialize Feature Matcher (SIFT)
        print("Loading SIFT Feature Matcher...")
        self.current_unit = "Unit1"
        self.matcher = FeatureMatcher(get_resource_path(f"card_images/{self.current_unit}")) 
        print(f"Features loaded for {self.current_unit}.")

        # Load dynamic category maps and flashcards
        self.category_map = UNIT_DATA[self.current_unit]["cards"]
        self.flashcards = list(self.category_map.keys())

        # Load UI Image Assets
        try:
            self.bg_splash = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/icon_background.png")).convert(), (WINDOW_WIDTH, WINDOW_HEIGHT))
        except:
            self.bg_splash = None
            
        self.bg_menu = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/bg_menu.png")).convert(), (WINDOW_WIDTH, WINDOW_HEIGHT))
        self.bg_gameplay = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/bg_gameplay.png")).convert(), (WINDOW_WIDTH, WINDOW_HEIGHT))
        
        self.icon_heart_full = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/heart_full.png")).convert_alpha(), (40, 40))
        self.icon_heart_empty = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/heart_empty.png")).convert_alpha(), (40, 40))
        self.icon_lock = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/lock_icon.png")).convert_alpha(), (60, 60))
        self.icon_wifi = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/wifi_check.png")).convert_alpha(), (80, 80))

        # Load custom chapter buttons if available
        self.chapter_buttons = {}
        for i in range(1, 7):
            try:
                # Expected to be 240x160
                btn_img = pygame.image.load(get_resource_path(f"assets/ui/buttons/unit{i}_btn.png")).convert_alpha()
                self.chapter_buttons[i] = pygame.transform.scale(btn_img, (240, 160))
            except:
                pass

        # Initialize Speech Recognition
        self.recognizer = sr.Recognizer()
        # We will instantiate microphone per thread to avoid context manager assertion errors
        
        # Threading & State Control
        self.is_listening = False
        self.speech_thread = None
        self.running = True

        # Game State Variables
        self.current_state = GameState.SPLASH_SCREEN # Start with Splash Screen
        self.splash_start_time = time.time()
        self.current_card_index = 0
        self.play_sequence = list(self.flashcards)
        self.target_category = self.play_sequence[self.current_card_index] if self.play_sequence else ""
        self.target_word_thai = self.target_category
    
        self.is_random_mode = False
    
        self.pre_pause_state = None # To return to previous state after unpausing
        self.mistakes = 0
        self.score = 0
        self.total_cards = 0
        self.spelling_start_time = 0
        self.countdown_start_time = 0
        self.wrong_object_timer = 0
        self.fade_alpha = 255  # For screen transitions
        self.fade_start_time = 0
        self.last_speech_result = ""
        self.feedback_message = ""
        self.feedback_timer = 0
        
        # Temporal Cross-Check Tracker
        self.tracking_history = []
        self.REQUIRED_CONSECUTIVE_FRAMES = 3 # Require 3 consecutive hits
        
        # Threading for Computer Vision
        self.last_scan_result = None
        self.current_scan_frame = None
        self.cv_thread = threading.Thread(target=self.scan_worker)
        self.cv_thread.daemon = True
        self.cv_thread.start()

        # Frame buffer
        self.current_surface = None
        self.current_window_width = WINDOW_WIDTH
        self.current_window_height = WINDOW_HEIGHT

    def update_sfx_volume(self):
        # Scale down SFX maximum amplitude so TTS voice can be heard clearly
        vol = self.sfx_volume * 0.2 
        if self.sfx_correct: self.sfx_correct.set_volume(vol)
        if self.sfx_wrong: self.sfx_wrong.set_volume(vol)
        if self.sfx_hover: self.sfx_hover.set_volume(vol)
        if self.sfx_click: self.sfx_click.set_volume(vol)
        if self.sfx_new_word: self.sfx_new_word.set_volume(vol)
        if self.sfx_game_over: self.sfx_game_over.set_volume(vol)
        if self.sfx_fail: self.sfx_fail.set_volume(vol)

    def get_logical_mouse_pos(self):
        win_w, win_h = self.window.get_size()
        aspect_ratio = WINDOW_WIDTH / WINDOW_HEIGHT
        target_w = win_w
        target_h = int(target_w / aspect_ratio)
        if target_h > win_h:
            target_h = win_h
            target_w = int(target_h * aspect_ratio)
            
        x_offset = (win_w - target_w) // 2
        y_offset = (win_h - target_h) // 2
        
        phys_x, phys_y = pygame.mouse.get_pos()
        if target_w == 0 or target_h == 0: return -1, -1
        logical_x = int((phys_x - x_offset) * (WINDOW_WIDTH / target_w))
        logical_y = int((phys_y - y_offset) * (WINDOW_HEIGHT / target_h))
        return logical_x, logical_y

    def load_camera_config(self):
        try:
            with open("config.json", "r") as f:
                data = json.load(f)
                return data.get("camera_index", 0)
        except:
            return 0

    def save_camera_config(self, index):
        with open("config.json", "w") as f:
            json.dump({"camera_index": index}, f)

    def check_network_worker(self):
        """Threaded network check to prevent UI hanging"""
        self.is_checking_network = True
        self.network_status = "กำลังตรวจสอบการเชื่อมต่ออินเทอร์เน็ต..."
        try:
            # Fast ping to Google's connectivity check endpoint
            requests.get("http://clients3.google.com/generate_204", timeout=3)
            self.network_status = "เชื่อมต่อสำเร็จ! พร้อมเข้าเกม"
        except (requests.ConnectionError, requests.Timeout):
            self.network_status = "ล้มเหลว: ไม่พบการเชื่อมต่ออินเทอร์เน็ต"
        finally:
            self.is_checking_network = False

    def check_available_cameras(self):
        """Check the first 5 indices for available cameras."""
        available = []
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        return available

    def init_camera(self, camera_index):
        if self.cap:
            self.cap.release()
            self.cap = None
        
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WINDOW_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, WINDOW_HEIGHT)
        
        if not self.cap.isOpened():
            print(f"Error: Could not open webcam {camera_index}.")
        else:
            print(f"Initialized Camera {camera_index}")

    def release_camera(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def start_game(self):
        # Reset game values
        import random
        self.current_card_index = 0
        self.category_map = UNIT_DATA[self.current_unit]["cards"]
        self.flashcards = list(self.category_map.keys())
        self.play_sequence = list(self.flashcards)
        
        if not self.play_sequence:
            print(f"Warning: No cards found for {self.current_unit}")
            # Optional: handle empty unit case
            
        if self.is_random_mode:
            random.shuffle(self.play_sequence)
            
        if self.play_sequence:
            self.target_category = self.play_sequence[self.current_card_index]
            self.target_word_thai = self.target_category
            self.total_cards = len(self.play_sequence)
        else:
            self.target_category = ""
            self.target_word_thai = ""
            self.total_cards = 0
        self.mistakes = 0
        self.score = 0
        self.feedback_message = ""
        
        # Power on Camera
        if self.available_cameras:
            self.init_camera(self.available_cameras[self.current_camera_index])
            
        # Lower BGM volume significantly during gameplay
        pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
            
        # Begin Pre-Game Fade Sequence
        self.current_state = GameState.PRE_GAME_FADE
        self.fade_alpha = 255
        self.fade_start_time = time.time()

    def next_card(self):
        self.current_card_index += 1
        if self.current_card_index >= len(self.play_sequence):
            # Stop BGM when game is over
            pygame.mixer.music.stop()
            
            self.current_state = GameState.END_SCREEN_FADE
            self.fade_alpha = 0
            self.fade_start_time = time.time()
            self.feedback_message = ""
            
            # Determine audio based on score threshold
            accuracy = 0
            if self.total_cards > 0:
                accuracy = (self.score / self.total_cards) * 100
                
            if accuracy >= 75:
                if self.sfx_game_over: self.sfx_game_over.play()
            else:
                if self.sfx_fail: self.sfx_fail.play()
            return

        if self.sfx_new_word: self.sfx_new_word.play()
        self.target_category = self.play_sequence[self.current_card_index]
        self.target_word_thai = self.target_category
        self.current_state = GameState.PRE_GAME_FADE
        self.fade_alpha = 255
        self.fade_start_time = time.time()
        self.mistakes = 0
        self.last_speech_result = ""
        self.feedback_message = ""
        self.tracking_history.clear() # Reset tracker
        print(f"Next card: {self.target_word_thai}")

    def trigger_wrong_action(self, reason_message):
        if self.sfx_wrong: self.sfx_wrong.play()
        self.mistakes += 1
        self.feedback_message = reason_message
        print(f"Mistake {self.mistakes}: {reason_message}")

    def scan_worker(self):
        """Threaded function for running SIFT prediction without blocking UI"""
        while self.running:
            if self.current_state == GameState.SCANNING and self.current_scan_frame is not None:
                # Predict on the latest captured frame copy
                frame_to_scan = self.current_scan_frame.copy()
                self.last_scan_result = self.matcher.predict(frame_to_scan, target_class=None)
                time.sleep(0.1) # Max ~10 FPS for the detector to save CPU
            else:
                time.sleep(0.05)

    def listen_speech_worker(self):
        """Threaded function for speech recognition to prevent blocking"""
        print("THREAD: Starting listening...")
        # Pause BGM so it doesn't interfere with the microphone
        pygame.mixer.music.pause()
        
        with sr.Microphone() as source:
            try:
                # Adjust for ambient noise to handle room background noise
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
                
                # Force a lower threshold for soft speakers (default is ~300) 
                # but keep dynamic adjustments enabled
                if self.recognizer.energy_threshold > 250:
                    self.recognizer.energy_threshold = 250
                self.recognizer.dynamic_energy_threshold = True
                
                # Increased timeout and phrase limit for slower speakers/thinking time
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                print("THREAD: Processing audio...")
                try:
                    text = self.recognizer.recognize_google(audio, language="th-TH")
                    print(f"THREAD: Heard '{text}'")
                    self.last_speech_result = text
                    
                    # Modern Check: Check if target word OR any aliases are in the result
                    target_info = self.category_map.get(self.target_word_thai, {})
                    aliases = target_info.get("aliases", [])
                    
                    is_correct = False
                    
                    def is_match(target, spoken):
                        # 1. Exact or Substring match (e.g., spoken sentence contains the target word)
                        if target in spoken:
                            return True
                        # 2. Fuzzy match (e.g., "กะทะ" instead of "กระทะ") - 60% similarity threshold
                        similarity = difflib.SequenceMatcher(None, target, spoken).ratio()
                        return similarity >= 0.60

                    if is_match(self.target_word_thai, text):
                        is_correct = True
                    else:
                        for alias in aliases:
                            if is_match(alias, text):
                                is_correct = True
                                break

                    if is_correct:
                        if self.sfx_correct: self.sfx_correct.play()
                        self.score += 1
                        self.feedback_message = "ถูกต้อง! +1 คะแนน"
                        time.sleep(1) 
                        self.next_card()
                    else:
                        if self.mistakes >= 1: # This is the 2nd mistake (0-indexed effectively since we'll trigger)
                            self.trigger_wrong_action(f"หมดโควต้าแล้ว! ข้ามไปคำถัดไปเลยนะ")
                            time.sleep(1.5)
                            self.next_card()
                        else:
                            self.trigger_wrong_action(f"ลองอีกครั้ง! (ได้ยิน: {text})")
                            if self.current_state != GameState.GAME_OVER:
                                self.current_state = GameState.COUNTDOWN_PRE_LISTEN
                                self.countdown_start_time = time.time()
                
                except sr.UnknownValueError:
                    print("THREAD: Could not understand audio")
                    self.feedback_message = "???"
                except sr.RequestError as e:
                    print(f"THREAD: Request error; {e}")
                    self.feedback_message = "ข้อผิดพลาดระบบเครือข่าย"

            except sr.WaitTimeoutError:
                print("THREAD: Listening timed out")
            except Exception as e:
                print(f"THREAD: Error: {e}")
            finally:
                self.is_listening = False 
                # Resume BGM if we haven't transitioned to Game Over
                if self.current_state != GameState.GAME_OVER and self.current_state != GameState.END_SCREEN_FADE:
                    pygame.mixer.music.unpause()
                print("THREAD: Finished.")

    def update(self):
        # 0. If paused, don't update camera or logic
        if self.current_state == GameState.PAUSED:
            return

        # 1. Capture Camera Frame (Only if game is actively using it or in Step 1 config)
        if self.current_state not in [GameState.SETTINGS_SCREEN_STEP_2, GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.GAME_OVER, GameState.AUDIO_SETTINGS]:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if not ret: 
                    # Use a blank frame if read fails
                    frame = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)
            else:
                frame = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)
        else:
            frame = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)

        # 2. Process based on State
        if self.current_state == GameState.SPLASH_SCREEN:
            elapsed = time.time() - self.splash_start_time
            if elapsed >= 3.0: # Show splash for 3 seconds
                self.current_state = GameState.SETTINGS_SCREEN_STEP_1
                try:
                    pygame.mixer.music.play(-1) # Start BGM now
                except:
                    pass
                    
        elif self.current_state in [GameState.SETTINGS_SCREEN_STEP_1, GameState.SETTINGS_SCREEN_STEP_2, GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.AUDIO_SETTINGS]:
            # Completely UI driven, no logic per frame needed here
            pass
            
        elif self.current_state == GameState.PRE_GAME_FADE:
            elapsed = time.time() - self.fade_start_time
            # Wait 2 seconds before fading out the black cover
            if elapsed > 2.0:
                fade_duration = 2.0
                ratio = (elapsed - 2.0) / fade_duration
                self.fade_alpha = max(0, int(255 * (1.0 - ratio)))
                if self.fade_alpha <= 0:
                    self.current_state = GameState.SCANNING

        elif self.current_state == GameState.SCANNING:
            # We copy the frame to a thread-safe variable for the background CV worker
            self.current_scan_frame = frame.copy()
            
            result = self.last_scan_result
            if result:
                x1, y1, x2, y2 = result['bbox']
                pts = result['polygon']
                detect_class = result['class_name']
                
                # Check if the detected class is one of the valid classes for the current target category
                valid_patterns = self.category_map.get(self.target_category, {}).get("patterns", [])
                is_target = detect_class in valid_patterns
                
                # Draw the polygon matched area (Green if correct, Red if wrong)
                box_color = (0, 255, 0) if is_target else (0, 0, 255) # OpenCV uses BGR
                cv2.polylines(frame, [pts], True, box_color, 3, cv2.LINE_AA)
                
                # Temporal Cross-Check: Add to history
                self.tracking_history.append(detect_class)
                if len(self.tracking_history) > self.REQUIRED_CONSECUTIVE_FRAMES:
                    self.tracking_history.pop(0)

                # Only proceed if we have enough consistent history
                is_stable = (len(self.tracking_history) == self.REQUIRED_CONSECUTIVE_FRAMES and 
                             all(c == detect_class for c in self.tracking_history))

                if is_stable:
                    if is_target:
                        if self.current_state == GameState.SCANNING:
                            if self.sfx_correct: self.sfx_correct.play()
                            self.current_state = GameState.COUNTDOWN
                            self.countdown_start_time = time.time()
                            self.last_scan_result = None # Reset for next card
                            self.tracking_history.clear()
                            print(f"Confirmed {self.target_word_thai}! Starting countdown...")
                    else:
                        # Temporarily disabled wrong card penalty to reduce interruptions
                        pass
                        # wrong_category = next((cat for cat, items in CATEGORY_MAP.items() if detect_class in items), 'รูปที่ไม่รู้จัก')
                        # self.trigger_wrong_action(f"ผิดรูป! เจอบัตร: {wrong_category}")
                        # if self.current_state != GameState.GAME_OVER:
                        #     self.current_state = GameState.WRONG_OBJECT
                        #     self.wrong_object_timer = time.time()
                        #     self.last_scan_result = None # Reset so it doesn't immediately re-fire
                        #     self.tracking_history.clear()


        elif self.current_state == GameState.WRONG_OBJECT:
            elapsed = time.time() - self.wrong_object_timer
            if elapsed >= 2.0:
                self.current_state = GameState.SCANNING
                self.feedback_message = ""
                self.tracking_history.clear() # Reset tracking after pause

        elif self.current_state == GameState.COUNTDOWN:
            elapsed = time.time() - self.countdown_start_time
            if elapsed >= 3.0:
                self.current_state = GameState.READING_AND_SPELLING
                self.spelling_start_time = time.time()
                
                # Load and play audio using the broad category name (e.g. "เสื้อนักเรียน.mp3")
                audio_path = get_resource_path(f"assets/audio/{self.target_category}.mp3")
                if os.path.exists(audio_path):
                    tts_sound = pygame.mixer.Sound(audio_path)
                    tts_sound.set_volume(1.0) # Always play TTS at 100%
                    tts_sound.play()
                    
                self.feedback_message = ""
            
        elif self.current_state == GameState.READING_AND_SPELLING:
            elapsed = time.time() - self.spelling_start_time
            # Duration of spelling animation (2.5 seconds)
            if elapsed >= 3.0:
                self.current_state = GameState.COUNTDOWN_PRE_LISTEN
                self.countdown_start_time = time.time()
                
        elif self.current_state == GameState.COUNTDOWN_PRE_LISTEN:
            elapsed = time.time() - self.countdown_start_time
            if elapsed >= 3.0:
                self.current_state = GameState.LISTENING

        elif self.current_state == GameState.LISTENING:
            if not self.is_listening:
                self.is_listening = True
                self.speech_thread = threading.Thread(target=self.listen_speech_worker)
                self.speech_thread.daemon = True
                self.speech_thread.start()
                
        elif self.current_state == GameState.END_SCREEN_FADE:
            elapsed = time.time() - self.fade_start_time
            # Fade camera to black over 2 seconds
            ratio = elapsed / 2.0
            self.fade_alpha = min(255, int(255 * ratio))
            if self.fade_alpha >= 255:
                self.release_camera()
                self.current_state = GameState.GAME_OVER

        # 3. Convert Frame to Pygame Surface
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb = np.rot90(frame_rgb)
        frame_rgb = np.flipud(frame_rgb)
        self.current_surface = pygame.surfarray.make_surface(frame_rgb)

    def draw_text_centered(self, text, font, color, y_offset=0, bg_color=None):
        text_surface = font.render(text, True, color)
        rect = text_surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + y_offset))
        if bg_color:
            bg_rect = rect.inflate(20, 10)
            pygame.draw.rect(self.screen, bg_color, bg_rect, border_radius=10)
        self.screen.blit(text_surface, rect)

    # --- Candy Crush Style UI Helpers ---
    def draw_panel(self, rect, base_color=(250, 240, 210), border_color=(210, 50, 80)):
        """Draws a rounded, bubbly pop-up panel."""
        shadow_rect = rect.copy()
        shadow_rect.y += 8
        pygame.draw.rect(self.screen, (0, 0, 0, 80), shadow_rect, border_radius=25)
        pygame.draw.rect(self.screen, border_color, rect, border_radius=25)
        inner_rect = rect.inflate(-16, -16)
        pygame.draw.rect(self.screen, base_color, inner_rect, border_radius=18)

    def draw_bubbly_button(self, text, rect, color=(100, 200, 50), text_color=(255, 255, 255), font=None):
        """Draws a bright, pill-shaped button with a 3D drop-shadow effect."""
        if font is None:
            font = self.font_medium
        mouse_pos = self.get_logical_mouse_pos()
        is_hovered = rect.collidepoint(mouse_pos)
        
        button_id = f"{text}_{rect.x}_{rect.y}"
        if is_hovered:
            if button_id not in self.hovered_buttons:
                if self.sfx_hover: self.sfx_hover.play()
                self.hovered_buttons.add(button_id)
            color = (min(255, color[0]+30), min(255, color[1]+30), min(255, color[2]+30))
            rect = rect.move(0, 2) # Depress slightly on hover
        else:
            if button_id in self.hovered_buttons:
                self.hovered_buttons.remove(button_id)
            
        shadow_color = (max(0, color[0]-50), max(0, color[1]-50), max(0, color[2]-50))
        
        # Deep Bottom Shadow
        bottom_rect = rect.copy()
        bottom_rect.y += 6
        pygame.draw.rect(self.screen, shadow_color, bottom_rect, border_radius=20)
        
        # Main Button
        pygame.draw.rect(self.screen, color, rect, border_radius=20)
        
        # Top Highlight (Gloss)
        highlight_rect = pygame.Rect(rect.x + 10, rect.y + 5, rect.width - 20, 10)
        pygame.draw.rect(self.screen, (255, 255, 255, 100), highlight_rect, border_radius=5)
        
        # Text
        txt_surf = font.render(text, True, (0, 0, 0)) # Drop shadow text
        self.screen.blit(txt_surf, txt_surf.get_rect(center=(rect.centerx, rect.centery + 2)))
        txt_surf = font.render(text, True, text_color)
        self.screen.blit(txt_surf, txt_surf.get_rect(center=rect.center))

    def draw_heart(self, x, y, width, active=True):
        """Draws the heart icon active or empty state centered."""
        img = self.icon_heart_full if active else self.icon_heart_empty
        rect = img.get_rect(center=(x, y + (width // 2)))
        self.screen.blit(img, rect)

    def draw(self):
        # Draw background pattern Image
        if self.current_state == GameState.SPLASH_SCREEN:
            if getattr(self, 'bg_splash', None):
                self.screen.blit(self.bg_splash, (0, 0))
            else:
                self.screen.blit(self.bg_menu, (0, 0))
        elif self.current_state in [GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.MODE_SELECT, GameState.AUDIO_SETTINGS]:
            self.screen.blit(self.bg_menu, (0, 0))
        else:
            self.screen.blit(self.bg_gameplay, (0, 0))

        # Draw Camera Feed (if game is active or in Settings Step 1)
        if self.current_state not in [GameState.SPLASH_SCREEN, GameState.SETTINGS_SCREEN_STEP_2, GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.MODE_SELECT, GameState.GAME_OVER, GameState.AUDIO_SETTINGS]:
            if self.current_surface:
                self.screen.blit(self.current_surface, (0, 0))

        # UI Overlay Logic Per State
        if self.current_state == GameState.SPLASH_SCREEN:
            # Simply show the bg_splash image without overlaying text or icon 
            pass

        elif self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
            panel_rect = pygame.Rect(0, 0, 600, 500)
            panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
            self.draw_panel(panel_rect)
            
            self.draw_text_centered("ตั้งค่ากล้อง", self.font_large, (255, 80, 80), -200)
            
            # Preview box hole
            preview_rect = pygame.Rect(0, 0, 384, 216)
            preview_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 30)
            # Draw preview feed if available
            if self.current_surface:
                scaled_cam = pygame.transform.scale(self.current_surface, (384, 216))
                self.screen.blit(scaled_cam, preview_rect.topleft)
            pygame.draw.rect(self.screen, (50, 50, 100), preview_rect, border_radius=10, width=5)

            cam_name = str(self.available_cameras[self.current_camera_index]) if self.available_cameras else "ไม่พบกล้อง"
            self.draw_text_centered(f"Camera ID: {cam_name}", self.font_medium, (50, 50, 100), 120)
            
            # Left/Right Buttons
            left_rect = pygame.Rect(WINDOW_WIDTH//2 - 220, WINDOW_HEIGHT//2 + 90, 60, 60)
            right_rect = pygame.Rect(WINDOW_WIDTH//2 + 160, WINDOW_HEIGHT//2 + 90, 60, 60)
            self.draw_bubbly_button("◀", left_rect, color=(80, 150, 255))
            self.draw_bubbly_button("▶", right_rect, color=(80, 150, 255))
            
            # Button (Next)
            btn_rect = pygame.Rect(0, 0, 200, 60)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 200)
            self.draw_bubbly_button("ถัดไป", btn_rect, color=(100, 220, 100))

        elif self.current_state == GameState.SETTINGS_SCREEN_STEP_2:
            panel_rect = pygame.Rect(0, 0, 600, 400)
            panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
            self.draw_panel(panel_rect)
            
            self.draw_text_centered("เช็คอินเทอร์เน็ต", self.font_large, (255, 80, 80), -120)
            
            # Wifi Icon
            wifi_rect = self.icon_wifi.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 50))
            self.screen.blit(self.icon_wifi, wifi_rect)
            
            # Network Status Text
            color = (150, 150, 50) if self.is_checking_network else ((50, 200, 50) if "สำเร็จ" in self.network_status else (255, 50, 50))
            self.draw_text_centered(self.network_status, self.font_small, color, 0)
            
            # Button states
            btn_rect = pygame.Rect(0, 0, 300, 60)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 100)
            
            if self.is_checking_network:
                self.draw_bubbly_button("กำลังโหลด...", btn_rect, color=(200, 200, 200))
            elif "สำเร็จ" in self.network_status:
                self.draw_bubbly_button("ลุยเลย!", btn_rect, color=(100, 220, 100))
            else:
                self.draw_bubbly_button("ลองตรวจสอบใหม่", btn_rect, color=(255, 100, 100))

        elif self.current_state == GameState.LANDING_PAGE:
            self.draw_text_centered("บัตรคำอัจฉริยะ", self.font_title, (255, 80, 120), -150)
            
            title_bg_rect = pygame.Rect(0, 0, 650, 60)
            title_bg_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 50)
            pygame.draw.rect(self.screen, (255, 255, 255), title_bg_rect, border_radius=30)
            self.draw_text_centered("เกมทายบัตรคำศัพท์สุดหรรษา", self.font_medium, (200, 100, 50), -50)
            
            # Play Button
            btn_rect = pygame.Rect(0, 0, 320, 90)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 100)
            self.draw_bubbly_button("เลือกบทเรียน", btn_rect, color=(80, 200, 255))
            
            # Settings Button
            settings_rect = pygame.Rect(WINDOW_WIDTH - 240, 30, 200, 60)
            self.draw_bubbly_button("ตั้งค่าเสียง", settings_rect, color=(200, 150, 200), font=self.font_small)

        elif self.current_state == GameState.CHAPTER_SELECT:
            self.draw_text_centered("เลือกบทเรียน", self.font_large, (255, 100, 150), -230)
            
            # Draw 6 Chapters Box Grid
            start_x = WINDOW_WIDTH // 2 - 400
            start_y = WINDOW_HEIGHT // 2 - 150
            for i in range(6):
                unit_id = f"Unit{i+1}"
                unit_info = UNIT_DATA.get(unit_id, {"title": f"Unit {i+1}", "cards": {}})
                
                x = start_x + (i % 3) * 280
                y = start_y + (i // 3) * 200
                rect = pygame.Rect(x, y, 240, 160)
                
                # Check if unit has cards to decide color
                has_cards = len(unit_info["cards"]) > 0
                
                # Hover sound logic
                mpos = self.get_logical_mouse_pos()
                is_hovered = rect.collidepoint(mpos)
                button_id = f"chap_btn_{i}"
                if is_hovered:
                    if button_id not in self.hovered_buttons:
                        if self.sfx_hover: self.sfx_hover.play()
                        self.hovered_buttons.add(button_id)
                else:
                    self.hovered_buttons.discard(button_id)
                
                if (i + 1) in self.chapter_buttons:
                    btn_img = self.chapter_buttons[i + 1]
                    
                    # Draw custom image shadow
                    shadow = btn_img.copy()
                    # Fill with black to make it dark, keeping original alpha
                    shadow.fill((0, 0, 0, 150), special_flags=pygame.BLEND_RGBA_MULT) 
                    self.screen.blit(shadow, (x + 4, y + 6))
                    
                    # Draw custom image
                    self.screen.blit(btn_img, (x, y))
                    
                    # Optional: adding a dark overlay if the unit has no cards
                    if not has_cards:
                        dark_overlay = pygame.Surface((240, 160), pygame.SRCALPHA)
                        dark_overlay.fill((0, 0, 0, 100))
                        self.screen.blit(dark_overlay, (x, y))
                else:
                    base_col = (200, 250, 220) if has_cards else (240, 240, 240)
                    border_col = (100, 200, 120) if has_cards else (200, 200, 200)
                    
                    self.draw_panel(rect, base_color=base_col, border_color=border_col)
                    
                    # Chapter number
                    ch_text = self.font_large.render(str(i+1), True, (80, 180, 100) if has_cards else (150, 150, 150))
                    # Chapter title
                    title_text = unit_info["title"]
                    if len(title_text) > 18:
                        import textwrap
                        # Use Thai logic friendly split if possible, but textwrap width=18 usually works for this case
                        wrapped_lines = textwrap.wrap(title_text, width=22)
                        y_offset = y + 100
                        for line in wrapped_lines:
                            sub_text = self.font_tiny.render(line, True, (50, 100, 50) if has_cards else (120, 120, 120))
                            self.screen.blit(sub_text, sub_text.get_rect(center=(x+120, y_offset)))
                            y_offset += 22
                    else:
                        sub_text = self.font_small.render(title_text, True, (50, 100, 50) if has_cards else (120, 120, 120))
                        self.screen.blit(sub_text, sub_text.get_rect(center=(x+120, y+120)))
                        
                    self.screen.blit(ch_text, ch_text.get_rect(center=(x+120, y+60)))
                
                if not has_cards:
                    lock_rect = self.icon_lock.get_rect(center=(x+120, y+80))
                    self.screen.blit(self.icon_lock, lock_rect)

        elif self.current_state == GameState.MODE_SELECT:
            self.draw_text_centered("ตั้งค่าก่อนเริ่มเกม", self.font_large, (255, 100, 150), -230)
            
            self.draw_text_centered("โหมดการจัดตารางคำศัพท์:", self.font_medium, (150, 100, 50), -110)

            # Sequence Mode Button
            btn_seq_rect = pygame.Rect(0, 0, 360, 70)
            btn_seq_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 30)
            color_seq = (100, 220, 100) if not self.is_random_mode else (200, 200, 200)
            self.draw_bubbly_button("ตามลำดับ", btn_seq_rect, color=color_seq)

            # Random Mode Button
            btn_rand_rect = pygame.Rect(0, 0, 360, 70)
            btn_rand_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 60)
            color_rand = (100, 220, 100) if self.is_random_mode else (200, 200, 200)
            self.draw_bubbly_button("สุ่ม (Random)", btn_rand_rect, color=color_rand)

            # Confirm and Start Button (Bottom Right)
            btn_start_rect = pygame.Rect(0, 0, 360, 80)
            btn_start_rect.bottomright = (WINDOW_WIDTH - 50, WINDOW_HEIGHT - 50)
            self.draw_bubbly_button("ยืนยันและเริ่มเกม", btn_start_rect, color=(255, 150, 50))
            
            # Back Button (Bottom Left)
            btn_back_rect = pygame.Rect(0, 0, 200, 60)
            btn_back_rect.bottomleft = (50, WINDOW_HEIGHT - 50)
            self.draw_bubbly_button("◀ กลับ", btn_back_rect, color=(200, 200, 200))

        elif self.current_state == GameState.AUDIO_SETTINGS:
            self.screen.blit(self.bg_menu, (0, 0)) # Redraw background just in case
            panel_rect = pygame.Rect(0, 0, 750, 500)
            panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
            self.draw_panel(panel_rect, base_color=(250, 240, 250), border_color=(200, 180, 200))
            
            self.draw_text_centered("ตั้งค่าเสียงระบบ", self.font_large, (200, 100, 200), -200)
            
            start_x = WINDOW_WIDTH // 2 - 200
            
            # BGM Row
            self.draw_text_centered(f"เพลงประกอบ (BGM): {int(self.bgm_volume*100)}%", self.font_medium, (100, 100, 100), -80)
            bgm_y = WINDOW_HEIGHT // 2 - 30
            btn_bgm_minus = pygame.Rect(start_x - 60, bgm_y, 45, 50)
            self.draw_bubbly_button("-", btn_bgm_minus, color=(255, 150, 150))
            btn_bgm_plus = pygame.Rect(start_x + 460, bgm_y, 45, 50)
            self.draw_bubbly_button("+", btn_bgm_plus, color=(150, 255, 150))
            # Step slider 1-10
            for i in range(10):
                rect = pygame.Rect(start_x + i * 45, bgm_y, 40, 50)
                color = (150, 255, 150) if i < int(self.bgm_volume * 10 + 0.1) else (230, 230, 230)
                border_col = (100, 200, 100) if i < int(self.bgm_volume * 10 + 0.1) else (180, 180, 180)
                pygame.draw.rect(self.screen, color, rect, border_radius=8)
                pygame.draw.rect(self.screen, border_col, rect, width=3, border_radius=8)
            
            # SFX Row
            self.draw_text_centered(f"เสียงเอฟเฟกต์ (SFX): {int(self.sfx_volume*100)}%", self.font_medium, (100, 100, 100), 60)
            sfx_y = WINDOW_HEIGHT // 2 + 110
            btn_sfx_minus = pygame.Rect(start_x - 60, sfx_y, 45, 50)
            self.draw_bubbly_button("-", btn_sfx_minus, color=(255, 150, 150))
            btn_sfx_plus = pygame.Rect(start_x + 460, sfx_y, 45, 50)
            self.draw_bubbly_button("+", btn_sfx_plus, color=(150, 255, 150))
            # Step slider 1-10
            for i in range(10):
                rect = pygame.Rect(start_x + i * 45, sfx_y, 40, 50)
                color = (150, 200, 255) if i < int(self.sfx_volume * 10 + 0.1) else (230, 230, 230)
                border_col = (100, 150, 200) if i < int(self.sfx_volume * 10 + 0.1) else (180, 180, 180)
                pygame.draw.rect(self.screen, color, rect, border_radius=8)
                pygame.draw.rect(self.screen, border_col, rect, width=3, border_radius=8)
            
            # Back button
            btn_back = pygame.Rect(0, 0, 200, 60)
            btn_back.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 210)
            self.draw_bubbly_button("กลับ", btn_back, color=(150, 150, 150))

        elif self.current_state == GameState.PAUSED:
            # Semi-transparent overlay over the gameplay
            overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))
            
            panel_rect = pygame.Rect(0, 0, 500, 400)
            panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
            self.draw_panel(panel_rect, base_color=(250, 240, 210), border_color=(210, 50, 80))
            
            self.draw_text_centered("หยุดพักชั่วคราว", self.font_large, (210, 50, 80), -120)
            
            # Resume Button
            btn_resume = pygame.Rect(0, 0, 300, 70)
            btn_resume.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 10)
            self.draw_bubbly_button("เล่นต่อ", btn_resume, color=(100, 220, 100))
            
            # Quit to Main Menu Button
            btn_quit = pygame.Rect(0, 0, 300, 70)
            btn_quit.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 80)
            self.draw_bubbly_button("ออกจากเกม", btn_quit, color=(255, 100, 100))

        elif self.current_state == GameState.PRE_GAME_FADE:
            # Cream colored cover overlay (matching panel background)
            fade_surf = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
            fade_surf.fill((250, 240, 210))
            fade_surf.set_alpha(self.fade_alpha)
            self.screen.blit(fade_surf, (0, 0))
            
            # Show floating word during transition phase
            if self.fade_alpha > 50:
                 self.draw_text_centered(f"คำที่ {self.current_card_index + 1}: {self.target_word_thai}", self.font_large, (210, 50, 80), 0)

        elif self.current_state == GameState.END_SCREEN_FADE:
            fade_surf = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
            fade_surf.fill((250, 240, 210))
            fade_surf.set_alpha(self.fade_alpha)
            self.screen.blit(fade_surf, (0, 0))

        elif self.current_state == GameState.GAME_OVER:
            panel_rect = pygame.Rect(0, 0, 700, 500)
            panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
            self.draw_panel(panel_rect)
            
            # Calculate accuracy
            accuracy = 0
            if self.total_cards > 0:
                accuracy = (self.score / self.total_cards) * 100
                
            # Score Text
            score_text = f"คะแนน: {self.score} / {self.total_cards}"
            self.draw_text_centered(score_text, self.font_large, (50, 50, 200), -150)
            
            # Message based on 75% threshold
            if accuracy >= 75:
                msg1 = "เก่งมาก!"
                msg2 = "ยอดเยี่ยมไปเลย"
                color = (50, 200, 50) # Green
            else:
                msg1 = "พยายามอีกนิดนะ!"
                msg2 = "สู้ๆ"
                color = (255, 100, 50) # Orange
                
            self.draw_text_centered(msg1, self.font_title, color, -40)
            self.draw_text_centered(msg2, self.font_medium, color, 40)
            
            # Button
            btn_rect = pygame.Rect(0, 0, 300, 80)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 160)
            self.draw_bubbly_button("กลับหน้าหลัก", btn_rect, color=(80, 200, 255))
        
        else: # Regular In-Game HUDs
            # Top Header Background
            header_bg = pygame.Surface((WINDOW_WIDTH, 80), pygame.SRCALPHA)
            header_bg.fill((210, 51, 80, 180))
            self.screen.blit(header_bg, (0, 0))
            
            # Game Header Update - Progress UI
            target_text = f"คำที่ {self.current_card_index + 1}/{len(self.play_sequence)}: {self.target_word_thai}"
            header_surf = self.font_medium.render(target_text, True, (255, 255, 255))
            self.screen.blit(header_surf, (20, 15))

            if self.current_state == GameState.SCANNING:
                scan_msg = self.font_small.render("ส่องกล้องไปที่รูปภาพบัตรคำ...", True, (200, 200, 200))
                self.screen.blit(scan_msg, (20, 85))

            elif self.current_state == GameState.COUNTDOWN:
                remaining = 3.0 - (time.time() - self.countdown_start_time)
                display_num = int(remaining) + 1
                if display_num > 0:
                    self.draw_text_centered(str(display_num), self.font_large, (255, 50, 50), 0, (0,0,0,100))
                    
            elif self.current_state == GameState.READING_AND_SPELLING:
                elapsed = time.time() - self.spelling_start_time
                spelling_duration = 2.0
                
                # Calculate how many characters to show based on elapsed time
                total_chars = len(self.target_word_thai)
                chars_to_show = int((elapsed / spelling_duration) * total_chars)
                chars_to_show = min(chars_to_show, total_chars)
                spelled_text = self.target_word_thai[:chars_to_show]
                
                # Render full text in gray as background
                full_surf = self.font_large.render(self.target_word_thai, True, (100, 100, 100))
                rect = full_surf.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
                
                # Draw background box for readability
                bg_rect = rect.inflate(40, 20)
                pygame.draw.rect(self.screen, (0,0,0,150), bg_rect, border_radius=10)
                
                # Blit the gray text
                self.screen.blit(full_surf, rect)
                
                # Render the bright colored revealed text on top (Karaoke effect)
                partial_surf = self.font_large.render(spelled_text, True, (255, 255, 50))
                # Blit exactly at the bottom-left of the gray text rect to prevent Thai vowel vertical jumping
                partial_rect = partial_surf.get_rect()
                partial_rect.bottomleft = rect.bottomleft
                self.screen.blit(partial_surf, partial_rect)

            elif self.current_state == GameState.COUNTDOWN_PRE_LISTEN:
                self.draw_text_centered("เตรียมพูด...", self.font_medium, (50, 200, 255), -80, (0,0,0,150))
                remaining = 3.0 - (time.time() - self.countdown_start_time)
                display_num = int(remaining) + 1
                if display_num > 0:
                    self.draw_text_centered(str(display_num), self.font_large, (255, 50, 50), 0, (0,0,0,100))

            elif self.current_state == GameState.LISTENING:
                self.draw_text_centered(f"พูดว่า: '{self.target_word_thai}'", self.font_medium, (50, 255, 50), -50, (0,0,0,150))
                status = "กำลังฟัง..." if self.is_listening else "กำลังประมวลผล..."
                self.draw_text_centered(status, self.font_small, (200, 200, 200), 20)

            elif self.current_state == GameState.WRONG_OBJECT:
                self.draw_text_centered("บัตรไม่ตรงกับโจทย์!", self.font_medium, (255, 100, 100), -50, (0,0,0,150))

            if self.feedback_message and self.current_state != GameState.GAME_OVER:
                color = (0, 255, 0) if "ถูกต้อง" in self.feedback_message else (255, 100, 100)
                msg = f"{self.feedback_message} (พลาดได้อีก {2 - self.mistakes} ครั้ง)" if self.mistakes > 0 else self.feedback_message
                self.draw_text_centered(msg, self.font_medium, color, 100, (0,0,0,200))

        # Scale and blit the internal surface onto the actual window
        win_w, win_h = self.window.get_size()
        aspect_ratio = WINDOW_WIDTH / WINDOW_HEIGHT
        target_w = win_w
        target_h = int(target_w / aspect_ratio)
        if target_h > win_h:
            target_h = win_h
            target_w = int(target_h * aspect_ratio)
            
        x_offset = (win_w - target_w) // 2
        y_offset = (win_h - target_h) // 2
        
        scaled_surf = pygame.transform.smoothscale(self.screen, (target_w, target_h))
        self.window.fill((0, 0, 0)) # Fill black bars
        self.window.blit(scaled_surf, (x_offset, y_offset))
        pygame.display.flip()

        # Clean up duplicate mouse pos logic if present

    def handle_click(self):
        lpos = self.get_logical_mouse_pos()
        click_handled = False
        
        if self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
            left_rect = pygame.Rect(WINDOW_WIDTH//2 - 220, WINDOW_HEIGHT//2 + 90, 60, 60)
            right_rect = pygame.Rect(WINDOW_WIDTH//2 + 160, WINDOW_HEIGHT//2 + 90, 60, 60)
            btn_start_rect = pygame.Rect(0, 0, 200, 60)
            btn_start_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 200)
            
            if left_rect.collidepoint(lpos) and len(self.available_cameras) > 0:
                self.current_camera_index = (self.current_camera_index - 1) % len(self.available_cameras)
                self.init_camera(self.available_cameras[self.current_camera_index])
                click_handled = True
            elif right_rect.collidepoint(lpos) and len(self.available_cameras) > 0:
                self.current_camera_index = (self.current_camera_index + 1) % len(self.available_cameras)
                self.init_camera(self.available_cameras[self.current_camera_index])
                click_handled = True
            elif btn_start_rect.collidepoint(lpos):
                self.save_camera_config(self.current_camera_index)
                self.current_state = GameState.SETTINGS_SCREEN_STEP_2
                self.network_status = "กำลังตรวจสอบ..."
                self.is_checking_network = True
                threading.Thread(target=self.check_network_worker, daemon=True).start()
                click_handled = True
                
        elif self.current_state == GameState.SETTINGS_SCREEN_STEP_2:
            btn_start_rect = pygame.Rect(WINDOW_WIDTH // 2 - 150, WINDOW_HEIGHT // 2 + 100, 300, 60)
            
            if btn_start_rect.collidepoint(lpos) and not self.is_checking_network:
                # Don't allow continuing if offline
                if "สำเร็จ" in self.network_status:
                    self.current_state = GameState.LANDING_PAGE
                    self.release_camera()
                elif "ล้มเหลว" in self.network_status:
                    self.network_status = "กรุณาเชื่อมต่ออินเทอร์เน็ตก่อน!"
                click_handled = True

        elif self.current_state == GameState.LANDING_PAGE:
            btn_rect = pygame.Rect(0, 0, 320, 90)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 100)
            settings_rect = pygame.Rect(WINDOW_WIDTH - 240, 30, 200, 60)
            
            if btn_rect.collidepoint(lpos):
                self.current_state = GameState.CHAPTER_SELECT
                click_handled = True
            elif settings_rect.collidepoint(lpos):
                self.current_state = GameState.AUDIO_SETTINGS
                click_handled = True
                
        elif self.current_state == GameState.AUDIO_SETTINGS:
            start_x = WINDOW_WIDTH // 2 - 200
            bgm_y = WINDOW_HEIGHT // 2 - 30
            sfx_y = WINDOW_HEIGHT // 2 + 110
            
            # Check BGM adjustments
            btn_bgm_minus = pygame.Rect(start_x - 60, bgm_y, 45, 50)
            btn_bgm_plus = pygame.Rect(start_x + 460, bgm_y, 45, 50)
            if btn_bgm_minus.collidepoint(lpos):
                self.bgm_volume = max(0.0, self.bgm_volume - 0.1)
                pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
                click_handled = True
            elif btn_bgm_plus.collidepoint(lpos):
                self.bgm_volume = min(1.0, self.bgm_volume + 0.1)
                pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
                click_handled = True
                
            # Check SFX adjustments
            btn_sfx_minus = pygame.Rect(start_x - 60, sfx_y, 45, 50)
            btn_sfx_plus = pygame.Rect(start_x + 460, sfx_y, 45, 50)
            if btn_sfx_minus.collidepoint(lpos):
                self.sfx_volume = max(0.0, self.sfx_volume - 0.1)
                self.update_sfx_volume()
                click_handled = True
            elif btn_sfx_plus.collidepoint(lpos):
                self.sfx_volume = min(1.0, self.sfx_volume + 0.1)
                self.update_sfx_volume()
                click_handled = True
                
            # Check 10-step sliders
            for i in range(10):
                rect_b = pygame.Rect(start_x + i * 45, bgm_y, 40, 50)
                if rect_b.collidepoint(lpos):
                    self.bgm_volume = (i + 1) / 10.0
                    pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
                    click_handled = True
                    
                rect_s = pygame.Rect(start_x + i * 45, sfx_y, 40, 50)
                if rect_s.collidepoint(lpos):
                    self.sfx_volume = (i + 1) / 10.0
                    self.update_sfx_volume()
                    click_handled = True

            btn_back = pygame.Rect(0, 0, 200, 60)
            btn_back.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 210)
            if btn_back.collidepoint(lpos):
                self.current_state = GameState.LANDING_PAGE
                click_handled = True
                
        elif self.current_state == GameState.CHAPTER_SELECT:
            start_x = WINDOW_WIDTH // 2 - 400
            start_y = WINDOW_HEIGHT // 2 - 150
            for i in range(6):
                x = start_x + (i % 3) * 280
                y = start_y + (i // 3) * 200
                btn_rect = pygame.Rect(x, y, 240, 160)
                
                if btn_rect.collidepoint(lpos):
                    unit_id = f"Unit{i+1}"
                    # Only allow selection if there are cards (or allow it but show empty)
                    # For now, let's allow selection if not empty or just allow it and see
                    self.current_unit = unit_id
                    
                    # Reload Matcher for the new unit
                    print(f"Switching to {unit_id}...")
                    self.matcher = FeatureMatcher(get_resource_path(f"card_images/{unit_id}"))
                    self.category_map = UNIT_DATA[unit_id]["cards"]
                    # Sequence should be the Thai keys
                    self.flashcards = list(self.category_map.keys())
                    
                    self.current_state = GameState.MODE_SELECT
                    click_handled = True
                    break
                
        elif self.current_state == GameState.MODE_SELECT:
            btn_start_rect = pygame.Rect(0, 0, 360, 80)
            btn_start_rect.bottomright = (WINDOW_WIDTH - 50, WINDOW_HEIGHT - 50)
            
            btn_seq_rect = pygame.Rect(0, 0, 360, 70)
            btn_seq_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 30)
            
            btn_rand_rect = pygame.Rect(0, 0, 360, 70)
            btn_rand_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 60)
            
            btn_back_rect = pygame.Rect(0, 0, 200, 60)
            btn_back_rect.bottomleft = (50, WINDOW_HEIGHT - 50)

            if btn_start_rect.collidepoint(lpos):
                click_handled = True
                self.start_game()
            elif btn_seq_rect.collidepoint(lpos):
                click_handled = True
                self.is_random_mode = False
            elif btn_rand_rect.collidepoint(lpos):
                click_handled = True
                self.is_random_mode = True
            elif btn_back_rect.collidepoint(lpos):
                click_handled = True
                self.current_state = GameState.CHAPTER_SELECT

        elif self.current_state == GameState.PAUSED:
            btn_resume = pygame.Rect(0, 0, 300, 70)
            btn_resume.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 10)
            
            btn_quit = pygame.Rect(0, 0, 300, 70)
            btn_quit.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 80)
            
            if btn_resume.collidepoint(lpos):
                self.current_state = self.pre_pause_state
                click_handled = True
            elif btn_quit.collidepoint(lpos):
                self.release_camera()
                self.current_state = GameState.LANDING_PAGE
                pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
                click_handled = True

        elif self.current_state == GameState.GAME_OVER:
            btn_rect = pygame.Rect(0, 0, 300, 80)
            btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 160)
            
            if btn_rect.collidepoint(lpos):
                click_handled = True
                self.current_state = GameState.LANDING_PAGE
                pygame.mixer.music.play(-1) # Restart BGM after game
                pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
                
        if click_handled and self.sfx_click:
            self.sfx_click.play()

    def run(self):
        while self.running:
            self.clock.tick(FPS)
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    pass # Handled inherently by surface scaling
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    lpos = self.get_logical_mouse_pos()
                    
                    if self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
                        btn_rect = pygame.Rect(0, 0, 200, 60)
                        btn_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 200)
                        left_rect = pygame.Rect(WINDOW_WIDTH//2 - 220, WINDOW_HEIGHT//2 + 90, 60, 60)
                        right_rect = pygame.Rect(WINDOW_WIDTH//2 + 160, WINDOW_HEIGHT//2 + 90, 60, 60)
                        
                        if btn_rect.collidepoint(lpos):
                            self.release_camera()
                    self.handle_click()

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        # NEW: Handle ESC based on context
                        # If in gameplay (not in menu/setup), show PAUSE modal
                        gameplay_states = [
                            GameState.SCANNING, GameState.WRONG_OBJECT, 
                            GameState.COUNTDOWN, GameState.READING_AND_SPELLING, 
                            GameState.COUNTDOWN_PRE_LISTEN, GameState.LISTENING
                        ]
                        
                        if self.current_state in gameplay_states:
                            self.pre_pause_state = self.current_state
                            self.current_state = GameState.PAUSED
                        elif self.current_state == GameState.PAUSED:
                            self.current_state = self.pre_pause_state
                        elif self.current_state in [GameState.CHAPTER_SELECT, GameState.GAME_OVER, GameState.MODE_SELECT, GameState.AUDIO_SETTINGS]:
                            self.current_state = GameState.LANDING_PAGE
                        else:
                            self.running = False
                            
                    elif event.key == pygame.K_w:
                        # Hidden Bypass: Force Win
                        gameplay_states = [GameState.SCANNING, GameState.WRONG_OBJECT, GameState.COUNTDOWN, GameState.READING_AND_SPELLING, GameState.COUNTDOWN_PRE_LISTEN, GameState.LISTENING]
                        if self.current_state in gameplay_states:
                            pygame.mixer.music.stop()
                            self.score = self.total_cards
                            self.current_state = GameState.END_SCREEN_FADE
                            self.fade_alpha = 0
                            self.fade_start_time = time.time()
                            self.feedback_message = ""
                            if self.sfx_game_over: self.sfx_game_over.play()
                            
                    elif event.key == pygame.K_l:
                        # Hidden Bypass: Force Loss
                        gameplay_states = [GameState.SCANNING, GameState.WRONG_OBJECT, GameState.COUNTDOWN, GameState.READING_AND_SPELLING, GameState.COUNTDOWN_PRE_LISTEN, GameState.LISTENING]
                        if self.current_state in gameplay_states:
                            pygame.mixer.music.stop()
                            self.score = 0
                            self.current_state = GameState.END_SCREEN_FADE
                            self.fade_alpha = 0
                            self.fade_start_time = time.time()
                            self.feedback_message = ""
                            if self.sfx_fail: self.sfx_fail.play()
                    
                    if self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
                        if event.key == pygame.K_RETURN:
                            # Proceed to Network Check step, releasing camera to save CPU
                            self.release_camera()
                            self.current_state = GameState.SETTINGS_SCREEN_STEP_2
                            # Auto-start check
                            t = threading.Thread(target=self.check_network_worker)
                            t.daemon = True
                            t.start()
                        elif event.key == pygame.K_RIGHT:
                            if self.available_cameras:
                                self.current_camera_index = (self.current_camera_index + 1) % len(self.available_cameras)
                                self.init_camera(self.available_cameras[self.current_camera_index])
                        elif event.key == pygame.K_LEFT:
                            if self.available_cameras:
                                self.current_camera_index = (self.current_camera_index - 1) % len(self.available_cameras)
                                self.init_camera(self.available_cameras[self.current_camera_index])
                                
                    elif self.current_state == GameState.SETTINGS_SCREEN_STEP_2 and not self.is_checking_network:
                        if event.key == pygame.K_RETURN:
                            if "สำเร็จ" in self.network_status:
                                self.save_camera_config(self.available_cameras[self.current_camera_index] if self.available_cameras else 0)
                                self.current_state = GameState.LANDING_PAGE
                            else: # Retry ping
                                t = threading.Thread(target=self.check_network_worker)
                                t.daemon = True
                                t.start()

                    elif self.current_state == GameState.LANDING_PAGE:
                        if event.key == pygame.K_RETURN:
                            self.current_state = GameState.CHAPTER_SELECT

                    elif self.current_state == GameState.CHAPTER_SELECT:
                        if event.key == pygame.K_RETURN:
                            self.start_game()
                            
                    elif self.current_state == GameState.GAME_OVER:
                        if event.key == pygame.K_RETURN:
                            self.current_state = GameState.LANDING_PAGE
                            pygame.mixer.music.play(-1) # Restart BGM
                            pygame.mixer.music.set_volume(self.bgm_volume * 0.2)

            self.update()
            self.draw()

        if self.cap: self.cap.release()
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    game = GameController()
    game.run()
