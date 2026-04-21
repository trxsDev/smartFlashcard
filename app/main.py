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
import ctypes
from enum import Enum, auto
from feature_matcher import FeatureMatcher
from config import APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, FPS, UNIT_DATA, get_resource_path, logger

# --- Windows High DPI Awareness ---
if sys.platform == "win32":
    try:
        # Query DPI Awareness (Windows 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(1) # 1 = PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            # Older Windows (Vista, 7, 8)
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass # Fallback for non-windows or errors


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
        pygame.init()
        self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE | pygame.DOUBLEBUF | pygame.HWSURFACE)
        self.screen = pygame.Surface((1280, 720)) # Draw at 720p, scale to 1080p/Resize for performance
        pygame.display.set_caption(APP_NAME)

        # Scaling variables for Resizable Window
        self.is_fullscreen = False
        self.target_aspect = 16 / 9
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.scaled_surf_size = (WINDOW_WIDTH, WINDOW_HEIGHT)
        
        self.calculate_scaling()

        # --- Instant Splash Feedback ---
        try:
            splash_path = get_resource_path("assets/ui/backgrounds/icon_background.png")
            if os.path.exists(splash_path):
                icon_bg = pygame.image.load(splash_path).convert()
                icon_bg = pygame.transform.scale(icon_bg, self.window.get_size())
                self.window.blit(icon_bg, (0, 0))
                pygame.display.flip()
        except:
            pass
        
        # Load and set the Window Icon
        try:
            icon_path = get_resource_path("assets/ui/icons/icon.png")
            if os.path.exists(icon_path):
                self.app_icon = pygame.image.load(icon_path).convert_alpha()
                pygame.display.set_icon(self.app_icon)
        except:
            self.app_icon = None
            pass

        self.clock = pygame.time.Clock()
        
        # Initialize Audio Mixer & SFX
        try:
            pygame.event.pump()
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
            pygame.event.pump()
            self.sfx_correct = pygame.mixer.Sound(get_resource_path("assets/sfx/correct.mp3"))
            self.sfx_wrong = pygame.mixer.Sound(get_resource_path("assets/sfx/wrong.mp3"))
            self.sfx_hover = pygame.mixer.Sound(get_resource_path("assets/sfx/hover.mp3"))
            self.sfx_click = pygame.mixer.Sound(get_resource_path("assets/sfx/click.mp3"))
            pygame.event.pump()
            self.sfx_new_word = pygame.mixer.Sound(get_resource_path("assets/sfx/new_word.mp3"))
            self.sfx_game_over = pygame.mixer.Sound(get_resource_path("assets/sfx/game_over.mp3"))
            self.sfx_fail = pygame.mixer.Sound(get_resource_path("assets/sfx/faild.mp3"))
            pygame.event.pump()
        except Exception as e:
            logger.error(f"Failed to initialize mixer or load SFX: {e}")
            self.sfx_correct = self.sfx_wrong = self.sfx_hover = self.sfx_click = None
            self.sfx_new_word = self.sfx_game_over = self.sfx_fail = None

        self.bgm_volume = 0.5
        self.sfx_volume = 0.8
        self.update_sfx_volume()
        
        # Load BGM
        try:
            pygame.mixer.music.load(get_resource_path("assets/sfx/bgm.mp3"))
            pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
        except Exception as e:
            logger.warning(f"BGM could not be loaded: {e}")

        self.hovered_buttons = set()

        # Fonts
        try:
            font_bold = get_resource_path("assets/fonts/Mali/Mali-Bold.ttf")
            font_regular = get_resource_path("assets/fonts/Mali/Mali-Regular.ttf")
            self.font_title = pygame.font.Font(font_bold, 75)
            self.font_large = pygame.font.Font(font_bold, 60)
            self.font_medium = pygame.font.Font(font_bold, 40)
            self.font_small = pygame.font.Font(font_regular, 25)
            self.font_tiny = pygame.font.Font(font_regular, 18)
        except Exception as e:
            logger.error(f"Failed to load fonts: {e}")
            self.font_title = self.font_large = self.font_medium = pygame.font.Font(None, 40)
            self.font_small = self.font_tiny = pygame.font.Font(None, 24)

        # Camera Setup
        self.available_cameras = self.check_available_cameras()
        self.current_camera_index = self.load_camera_config()
        self.cap = None
        
        if self.available_cameras:
            if self.current_camera_index >= len(self.available_cameras):
                self.current_camera_index = 0
            self.init_camera(self.available_cameras[self.current_camera_index])

        # Network Status
        self.network_status = "รอการตรวจสอบ..."
        self.is_checking_network = False
        
        # Initialize Feature Matcher
        self.current_unit = "Unit1"
        self.matcher = None
        self.matcher_ready = False
        threading.Thread(target=self.load_matcher_background, args=(self.current_unit,), daemon=True).start()

        # Load dynamic category maps and flashcards
        self.category_map = UNIT_DATA[self.current_unit]["cards"]
        self.flashcards = list(self.category_map.keys())

        # Load UI Image Assets
        try:
            self.bg_splash = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/icon_background.png")).convert(), (1280, 720))
        except:
            self.bg_splash = None
            
        self.bg_menu = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/bg_menu.png")).convert(), (1280, 720))
        self.bg_gameplay = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/backgrounds/bg_gameplay.png")).convert(), (1280, 720))
        
        self.icon_heart_full = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/heart_full.png")).convert_alpha(), (40, 40))
        self.icon_heart_empty = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/heart_empty.png")).convert_alpha(), (40, 40))
        self.icon_lock = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/lock_icon.png")).convert_alpha(), (60, 60))
        self.icon_wifi = pygame.transform.scale(pygame.image.load(get_resource_path("assets/ui/icons/wifi_check.png")).convert_alpha(), (80, 80))

        # Load custom chapter buttons if available
        self.chapter_buttons = {}
        for i in range(1, 7):
            try:
                btn_img = pygame.image.load(get_resource_path(f"assets/ui/buttons/unit{i}_btn.png")).convert_alpha()
                self.chapter_buttons[i] = pygame.transform.scale(btn_img, (240, 160))
            except:
                pass

        # Initialize Speech Recognition
        self.recognizer = sr.Recognizer()
        
        # Threading & State Control
        self.is_listening = False
        self.speech_thread = None
        self.running = True

        # Game State Variables
        self.current_state = GameState.SPLASH_SCREEN
        self.splash_start_time = time.time()
        self.current_card_index = 0
        self.play_sequence = list(self.flashcards)
        self.target_category = self.play_sequence[self.current_card_index] if self.play_sequence else ""
        self.target_word_thai = self.target_category
    
        self.is_random_mode = False
    
        self.pre_pause_state = None
        self.mistakes = 0
        self.score = 0
        self.total_cards = 0
        self.spelling_start_time = 0
        self.countdown_start_time = 0
        self.wrong_object_timer = 0
        self.fade_alpha = 255
        self.fade_start_time = 0
        self.last_speech_result = ""
        self.feedback_message = ""
        self.feedback_timer = 0
        
        # Temporal Cross-Check Tracker
        self.tracking_history = []
        self.REQUIRED_CONSECUTIVE_FRAMES = 3
        
        # Threading for Computer Vision
        self.last_scan_result = None
        self.current_scan_frame = None
        self.cv_thread = threading.Thread(target=self.scan_worker)
        self.cv_thread.daemon = True
        self.cv_thread.start()
        
        # Frame buffer
        self.current_surface = None
        self.mouse_pos = (0, 0)

    def update_sfx_volume(self):
        vol = self.sfx_volume * 0.2 
        if self.sfx_correct: self.sfx_correct.set_volume(vol)
        if self.sfx_wrong: self.sfx_wrong.set_volume(vol)
        if self.sfx_hover: self.sfx_hover.set_volume(vol)
        if self.sfx_click: self.sfx_click.set_volume(vol)
        if self.sfx_new_word: self.sfx_new_word.set_volume(vol)
        if self.sfx_game_over: self.sfx_game_over.set_volume(vol)
        if self.sfx_fail: self.sfx_fail.set_volume(vol)

    def calculate_scaling(self):
        w, h = self.window.get_size()
        should_fit = self.is_fullscreen or self.is_maximized()
        
        if should_fit:
            self.scaled_surf_size = (w, h)
            self.offset_x = 0
            self.offset_y = 0
            self.scale_x = w / 1280
            self.scale_y = h / 720
        else:
            current_aspect = w / h
            if current_aspect > self.target_aspect:
                new_h = h
                new_w = int(h * self.target_aspect)
                self.offset_x = (w - new_w) // 2
                self.offset_y = 0
            else:
                new_w = w
                new_h = int(w / self.target_aspect)
                self.offset_x = 0
                self.offset_y = (h - new_h) // 2
            
            self.scaled_surf_size = (new_w, new_h)
            self.scale_x = new_w / 1280
            self.scale_y = new_h / 720

    def is_maximized(self):
        if sys.platform == "win32":
            try:
                hwnd = pygame.display.get_wm_info()['window']
                GWL_STYLE = -16
                WS_MAXIMIZE = 0x01000000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                return bool(style & WS_MAXIMIZE)
            except: pass
        try:
            info = pygame.display.Info()
            curr_w, curr_h = self.window.get_size()
            return curr_w >= info.current_w - 60 and curr_h >= info.current_h - 100
        except: return False

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.HWSURFACE)
        else:
            self.window = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE | pygame.DOUBLEBUF | pygame.HWSURFACE)
        self.calculate_scaling()

    def map_mouse_pos(self, pos):
        mx, my = pos
        virtual_x = (mx - self.offset_x) / self.scale_x
        virtual_y = (my - self.offset_y) / self.scale_y
        return (virtual_x, virtual_y)

    def load_camera_config(self):
        try:
            with open("config.json", "r") as f:
                data = json.load(f)
                return data.get("camera_index", 0)
        except:
            return 0

    def save_camera_config(self, index):
        try:
            with open("config.json", "w") as f:
                json.dump({"camera_index": index}, f)
        except Exception as e:
            logger.error(f"Failed to save camera config: {e}")

    def check_network_worker(self):
        self.is_checking_network = True
        self.network_status = "กำลังตรวจสอบการเชื่อมต่ออินเทอร์เน็ต..."
        try:
            requests.get("http://clients3.google.com/generate_204", timeout=3)
            self.network_status = "เชื่อมต่อสำเร็จ! พร้อมเข้าเกม"
        except:
            self.network_status = "ล้มเหลว: ไม่พบการเชื่อมต่ออินเทอร์เน็ต"
        finally:
            self.is_checking_network = False

    def check_available_cameras(self):
        available = []
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        return available

    def init_camera(self, camera_index):
        try:
            if self.cap:
                self.cap.release()
            self.cap = cv2.VideoCapture(camera_index)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        except Exception as e:
            logger.error(f"Critical error during camera init: {e}")

    def release_camera(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def start_game(self):
        import random
        self.current_card_index = 0
        self.category_map = UNIT_DATA[self.current_unit]["cards"]
        self.flashcards = list(self.category_map.keys())
        self.play_sequence = list(self.flashcards)
        if self.is_random_mode:
            random.shuffle(self.play_sequence)
        if self.play_sequence:
            self.target_category = self.play_sequence[self.current_card_index]
            self.target_word_thai = self.target_category
            self.total_cards = len(self.play_sequence)
        self.mistakes = 0
        self.score = 0
        self.feedback_message = ""
        if self.available_cameras:
            self.init_camera(self.available_cameras[self.current_camera_index])
        pygame.mixer.music.set_volume(self.bgm_volume * 0.2)
        self.current_state = GameState.PRE_GAME_FADE
        self.fade_alpha = 255
        self.fade_start_time = time.time()

    def next_card(self):
        self.current_card_index += 1
        if self.current_card_index >= len(self.play_sequence):
            pygame.mixer.music.stop()
            self.current_state = GameState.END_SCREEN_FADE
            self.fade_alpha = 0
            self.fade_start_time = time.time()
            accuracy = (self.score / self.total_cards) * 100 if self.total_cards > 0 else 0
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
        self.tracking_history.clear()

    def trigger_wrong_action(self, reason_message):
        if self.sfx_wrong: self.sfx_wrong.play()
        self.mistakes += 1
        self.feedback_message = reason_message

    def load_matcher_background(self, unit_id):
        try:
            path = get_resource_path(f"card_images/{unit_id}")
            if os.path.exists(path):
                self.matcher = FeatureMatcher(path)
                self.matcher_ready = True
        except Exception as e:
            logger.error(f"Error loading matcher: {e}")

    def scan_worker(self):
        while self.running:
            if self.current_state == GameState.SCANNING and self.current_scan_frame is not None and self.matcher_ready:
                target_info = self.category_map.get(self.target_category, {})
                patterns = target_info.get("patterns", [])
                self.last_scan_result = self.matcher.predict(self.current_scan_frame.copy(), target_classes=patterns)
                time.sleep(0.08)
            else:
                time.sleep(0.05)

    def listen_speech_worker(self):
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
        except: pass
        with sr.Microphone() as source:
            try:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
                if self.recognizer.energy_threshold > 250:
                    self.recognizer.energy_threshold = 250
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                text = self.recognizer.recognize_google(audio, language="th-TH")
                target_info = self.category_map.get(self.target_word_thai, {})
                aliases = target_info.get("aliases", [])
                is_correct = any(difflib.SequenceMatcher(None, t, text).ratio() >= 0.6 or t in text for t in ([self.target_word_thai] + aliases))
                if is_correct:
                    if self.sfx_correct: self.sfx_correct.play()
                    self.score += 1
                    self.feedback_message = "ถูกต้อง! +1 คะแนน"
                    time.sleep(1) 
                    self.next_card()
                else:
                    if self.mistakes >= 2:
                        self.trigger_wrong_action("หมดโควต้าแล้ว! ข้ามไปเลย")
                        time.sleep(1.5)
                        self.next_card()
                    else:
                        self.trigger_wrong_action(f"ลองอีกครั้ง! (ได้ยิน: {text})")
                        self.current_state = GameState.COUNTDOWN_PRE_LISTEN
                        self.countdown_start_time = time.time()
            except sr.UnknownValueError:
                if self.mistakes >= 2:
                    self.trigger_wrong_action("ฟังไม่ชัด! ข้ามไปก่อนนะ")
                    time.sleep(1.5)
                    self.next_card()
                else:
                    self.trigger_wrong_action("ฟังไม่ชัด! ลองอีกครั้ง")
                    self.current_state = GameState.COUNTDOWN_PRE_LISTEN
                    self.countdown_start_time = time.time()
            except:
                pass
            finally:
                self.is_listening = False 
                try:
                    if self.current_state not in [GameState.GAME_OVER, GameState.END_SCREEN_FADE]:
                        pygame.mixer.music.unpause()
                except: pass

    def update(self):
        if self.current_state == GameState.PAUSED: return
        if self.current_state not in [GameState.SETTINGS_SCREEN_STEP_2, GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.GAME_OVER, GameState.AUDIO_SETTINGS]:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if not ret: frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            else: frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        else: frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        if self.current_state == GameState.SPLASH_SCREEN:
            if time.time() - self.splash_start_time >= 1.5:
                self.current_state = GameState.SETTINGS_SCREEN_STEP_1
                try: pygame.mixer.music.play(-1)
                except: pass
        elif self.current_state == GameState.PRE_GAME_FADE:
            elapsed = time.time() - self.fade_start_time
            if elapsed > 2.0:
                self.fade_alpha = max(0, int(255 * (1.0 - (elapsed - 2.0) / 2.0)))
                if self.fade_alpha <= 0: self.current_state = GameState.SCANNING
        elif self.current_state == GameState.SCANNING:
            self.current_scan_frame = frame.copy()
            if self.last_scan_result:
                pts = self.last_scan_result['polygon']
                is_target = self.last_scan_result['class_name'] in self.category_map.get(self.target_category, {}).get("patterns", [])
                cv2.polylines(frame, [pts], True, (0, 255, 0) if is_target else (0, 0, 255), 3, cv2.LINE_AA)
                self.tracking_history.append(self.last_scan_result['class_name'])
                if len(self.tracking_history) > self.REQUIRED_CONSECUTIVE_FRAMES: self.tracking_history.pop(0)
                if len(self.tracking_history) == self.REQUIRED_CONSECUTIVE_FRAMES and all(c == self.tracking_history[0] for c in self.tracking_history) and is_target:
                    if self.sfx_correct: self.sfx_correct.play()
                    self.current_state = GameState.COUNTDOWN
                    self.countdown_start_time = time.time()
                    self.last_scan_result = None
                    self.tracking_history.clear()
        elif self.current_state == GameState.COUNTDOWN:
            if time.time() - self.countdown_start_time >= 3.0:
                self.current_state = GameState.READING_AND_SPELLING
                self.spelling_start_time = time.time()
                audio_path = get_resource_path(f"assets/audio/{self.target_category}.mp3")
                if os.path.exists(audio_path): pygame.mixer.Sound(audio_path).play()
        elif self.current_state == GameState.READING_AND_SPELLING:
            if time.time() - self.spelling_start_time >= 3.0:
                self.current_state = GameState.COUNTDOWN_PRE_LISTEN
                self.countdown_start_time = time.time()
        elif self.current_state == GameState.COUNTDOWN_PRE_LISTEN:
            if time.time() - self.countdown_start_time >= 3.0: self.current_state = GameState.LISTENING
        elif self.current_state == GameState.LISTENING and not self.is_listening:
            self.is_listening = True
            threading.Thread(target=self.listen_speech_worker, daemon=True).start()
        elif self.current_state == GameState.END_SCREEN_FADE:
            self.fade_alpha = min(255, int(255 * (time.time() - self.fade_start_time) / 2.0))
            if self.fade_alpha >= 255: self.release_camera(); self.current_state = GameState.GAME_OVER

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.current_surface = pygame.surfarray.make_surface(np.transpose(frame_rgb, (1, 0, 2)))

    def draw_text_centered(self, text, font, color, y_offset=0, bg_color=None):
        text_surface = font.render(text, True, color)
        rect = text_surface.get_rect(center=(1280 // 2, 720 // 2 + y_offset))
        if bg_color:
            pygame.draw.rect(self.screen, bg_color, rect.inflate(20, 10), border_radius=10)
        self.screen.blit(text_surface, rect)

    def draw_panel(self, rect, base_color=(250, 240, 210), border_color=(210, 50, 80)):
        shadow = rect.copy(); shadow.y += 8
        pygame.draw.rect(self.screen, (0, 0, 0, 80), shadow, border_radius=25)
        pygame.draw.rect(self.screen, border_color, rect, border_radius=25)
        pygame.draw.rect(self.screen, base_color, rect.inflate(-16, -16), border_radius=18)

    def draw_bubbly_button(self, text, rect, color=(100, 200, 50), text_color=(255, 255, 255), font=None):
        font = font or self.font_medium
        is_hovered = rect.collidepoint(self.mouse_pos)
        if is_hovered:
            button_id = f"{text}_{rect.x}_{rect.y}"
            if button_id not in self.hovered_buttons:
                if self.sfx_hover: self.sfx_hover.play()
                self.hovered_buttons.add(button_id)
            color = tuple(min(255, c + 30) for c in color)
            rect = rect.move(0, 2)
        else:
            self.hovered_buttons.discard(f"{text}_{rect.x}_{rect.y}")
        pygame.draw.rect(self.screen, tuple(max(0, c - 50) for c in color), rect.move(0, 6), border_radius=20)
        pygame.draw.rect(self.screen, color, rect, border_radius=20)
        txt_surf = font.render(text, True, (0, 0, 0))
        self.screen.blit(txt_surf, txt_surf.get_rect(center=(rect.centerx, rect.centery + 2)))
        txt_surf = font.render(text, True, text_color)
        self.screen.blit(txt_surf, txt_surf.get_rect(center=rect.center))

    def draw(self):
        self.screen.fill((250, 240, 210))
        if self.current_state == GameState.SPLASH_SCREEN: self.screen.blit(self.bg_splash or self.bg_menu, (0, 0))
        elif self.current_state in [GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.MODE_SELECT, GameState.AUDIO_SETTINGS]: self.screen.blit(self.bg_menu, (0, 0))
        else: self.screen.blit(self.bg_gameplay, (0, 0))

        if self.current_state not in [GameState.SPLASH_SCREEN, GameState.SETTINGS_SCREEN_STEP_2, GameState.LANDING_PAGE, GameState.CHAPTER_SELECT, GameState.MODE_SELECT, GameState.GAME_OVER, GameState.AUDIO_SETTINGS]:
            if self.current_surface: self.screen.blit(self.current_surface, (0, 0))

        if self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
            self.draw_panel(pygame.Rect(1280//2-300, 720//2-250, 600, 500))
            self.draw_text_centered("ตั้งค่ากล้อง", self.font_large, (255, 80, 80), -200)
            if self.current_surface: self.screen.blit(pygame.transform.scale(self.current_surface, (384, 216)), (1280//2-192, 720//2-138))
            self.draw_bubbly_button("◀", pygame.Rect(1280//2-220, 720//2+90, 60, 60), color=(80, 150, 255))
            self.draw_bubbly_button("▶", pygame.Rect(1280//2+160, 720//2+90, 60, 60), color=(80, 150, 255))
            self.draw_bubbly_button("ถัดไป", pygame.Rect(1280//2-100, 720//2+170, 200, 60), color=(100, 220, 100))
        elif self.current_state == GameState.SETTINGS_SCREEN_STEP_2:
            self.draw_panel(pygame.Rect(1280//2-300, 720//2-200, 600, 400))
            self.draw_text_centered("เช็คอินเทอร์เน็ต", self.font_large, (255, 80, 80), -120)
            self.screen.blit(self.icon_wifi, self.icon_wifi.get_rect(center=(1280//2, 720//2-50)))
            color = (50, 200, 50) if "สำเร็จ" in self.network_status else (255, 50, 50)
            self.draw_text_centered(self.network_status, self.font_small, color, 0)
            self.draw_bubbly_button("ลุยเลย!" if "สำเร็จ" in self.network_status else "ย้อนกลับ", pygame.Rect(1280//2-150, 720//2+100, 300, 60))
        elif self.current_state == GameState.LANDING_PAGE:
            self.draw_text_centered("บัตรคำอัจฉริยะ", self.font_title, (255, 80, 120), -150)
            self.draw_bubbly_button("เลือกบทเรียน", pygame.Rect(1280//2-160, 720//2+55, 320, 90), color=(80, 200, 255))
        elif self.current_state == GameState.CHAPTER_SELECT:
            for i in range(6):
                rect = pygame.Rect(1280//2-400+(i%3)*280, 720//2-150+(i//3)*200, 240, 160)
                self.draw_panel(rect)
                self.screen.blit(self.font_large.render(str(i+1), True, (50, 100, 50)), rect.move(100, 40))
        elif self.current_state == GameState.MODE_SELECT:
            self.draw_bubbly_button("ยืนยันและเริ่มเกม", pygame.Rect(1280-410, 720-130, 360, 80), color=(255, 150, 50))
        elif self.current_state == GameState.GAME_OVER:
            self.draw_panel(pygame.Rect(1280//2-350, 720//2-250, 700, 500))
            self.draw_text_centered(f"คะแนน: {self.score} / {self.total_cards}", self.font_large, (50, 50, 200), -120)
            self.draw_bubbly_button("กลับหน้าหลัก", pygame.Rect(1280//2-150, 720//2+120, 300, 80), color=(80, 200, 255))
        elif self.current_state == GameState.PRE_GAME_FADE:
            s = pygame.Surface((1280, 720)); s.fill((250, 240, 210)); s.set_alpha(self.fade_alpha); self.screen.blit(s, (0, 0))
            if self.fade_alpha > 50: self.draw_text_centered(f"คำที่ {self.current_card_index + 1}: {self.target_word_thai}", self.font_large, (210, 50, 80), 0)
        elif self.current_state == GameState.SCANNING:
             header_bg = pygame.Surface((1280, 80), pygame.SRCALPHA); header_bg.fill((210, 51, 80, 180)); self.screen.blit(header_bg, (0, 0))
             self.screen.blit(self.font_medium.render(f"คำที่ {self.current_card_index + 1}: {self.target_word_thai}", True, (255, 255, 255)), (20, 15))

        scaled_output = pygame.transform.scale(self.screen, self.scaled_surf_size)
        self.window.fill((0, 0, 0))
        self.window.blit(scaled_output, (self.offset_x, self.offset_y))
        pygame.display.flip()

    def handle_click(self):
        p = self.mouse_pos
        if self.current_state == GameState.SETTINGS_SCREEN_STEP_1:
            if pygame.Rect(1280//2-220, 720//2+90, 60, 60).collidepoint(p): self.current_camera_index=(self.current_camera_index-1)%len(self.available_cameras); self.init_camera(self.available_cameras[self.current_camera_index])
            elif pygame.Rect(1280//2+160, 720//2+90, 60, 60).collidepoint(p): self.current_camera_index=(self.current_camera_index+1)%len(self.available_cameras); self.init_camera(self.available_cameras[self.current_camera_index])
            elif pygame.Rect(1280//2-100, 720//2+170, 200, 60).collidepoint(p): self.save_camera_config(self.current_camera_index); self.current_state=GameState.SETTINGS_SCREEN_STEP_2
        elif self.current_state == GameState.SETTINGS_SCREEN_STEP_2:
            if pygame.Rect(1280//2-150, 720//2+100, 300, 60).collidepoint(p):
                if "สำเร็จ" in self.network_status: self.current_state=GameState.LANDING_PAGE; self.release_camera()
                else: self.current_state=GameState.SETTINGS_SCREEN_STEP_1
        elif self.current_state == GameState.LANDING_PAGE:
            if pygame.Rect(1280//2-160, 720//2+55, 320, 90).collidepoint(p): self.current_state=GameState.CHAPTER_SELECT
        elif self.current_state == GameState.CHAPTER_SELECT:
            for i in range(6):
                if pygame.Rect(1280//2-400+(i%3)*280, 720//2-150+(i//3)*200, 240, 160).collidepoint(p):
                    self.current_unit=f"Unit{i+1}"; self.matcher_ready=False; threading.Thread(target=self.load_matcher_background, args=(self.current_unit,), daemon=True).start()
                    self.category_map=UNIT_DATA[self.current_unit]["cards"]; self.flashcards=list(self.category_map.keys()); self.current_state=GameState.MODE_SELECT; break
        elif self.current_state == GameState.MODE_SELECT:
            if pygame.Rect(1280-410, 720-130, 360, 80).collidepoint(p): self.start_game()
        elif self.current_state == GameState.GAME_OVER:
            if pygame.Rect(1280//2-150, 720//2+120, 300, 80).collidepoint(p): self.current_state = GameState.LANDING_PAGE

    def run(self):
        while self.running:
            self.clock.tick(FPS)
            pygame.event.pump()
            self.mouse_pos = self.map_mouse_pos(pygame.mouse.get_pos())
            for event in pygame.event.get():
                if event.type == pygame.QUIT: self.running = False
                elif event.type == pygame.VIDEORESIZE: self.calculate_scaling()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1: self.handle_click()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11: self.toggle_fullscreen()
                    elif event.key == pygame.K_ESCAPE: self.running = False
            self.update()
            self.draw()
        if self.cap: self.cap.release()
        pygame.quit(); sys.exit()

if __name__ == "__main__":
    GameController().run()
