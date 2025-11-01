"""
Improved SUT Service - Enhanced reliability for gaming automation
Uses Windows SendInput API for maximum compatibility with games
"""

import os
import time
import json
import subprocess
import threading
import psutil
from flask import Flask, request, jsonify, send_file
import pyautogui
from io import BytesIO
import logging
import win32api
import win32con
import win32gui
import ctypes
from ctypes import wintypes
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("improved_sut_service.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Global variables
game_process = None
game_lock = threading.Lock()
current_game_process_name = None

# Disable PyAutoGUI failsafe
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

# Check for admin privileges
def is_admin():
    """Check if running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# Windows API structures for SendInput
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION)
    ]

# Constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Virtual key codes
VK_CODES = {
    'left': 0x01, 'right': 0x02, 'middle': 0x04,
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'shift': 0x10,
    'ctrl': 0x11, 'alt': 0x12, 'pause': 0x13, 'caps_lock': 0x14,
    'escape': 0x1B, 'space': 0x20, 'page_up': 0x21, 'page_down': 0x22,
    'end': 0x23, 'home': 0x24, 'left_arrow': 0x25, 'up_arrow': 0x26,
    'right_arrow': 0x27, 'down_arrow': 0x28, 'insert': 0x2D, 'delete': 0x2E,
    'win': 0x5B, 'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78,
    'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B
}

class ImprovedInputController:
    """Enhanced input controller using Windows SendInput API."""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)

        # Reusable null pointer for dwExtraInfo to reduce allocations
        self._null_ptr = ctypes.cast(ctypes.pointer(wintypes.ULONG(0)), ctypes.POINTER(wintypes.ULONG))

        logger.info(f"Screen resolution: {self.screen_width}x{self.screen_height}")

    def _normalize_coordinates(self, x, y):
        """Convert screen coordinates to normalized coordinates (0-65535)."""
        normalized_x = int(x * 65535 / self.screen_width)
        normalized_y = int(y * 65535 / self.screen_height)
        return normalized_x, normalized_y

    def move_mouse(self, x, y, smooth=True, duration=0.3):
        """
        Move mouse to absolute position using SendInput.

        Args:
            x, y: Screen coordinates
            smooth: If True, move smoothly; if False, move instantly
            duration: Duration of smooth movement in seconds
        """
        try:
            if smooth and duration > 0:
                # Get current position
                current_x, current_y = win32api.GetCursorPos()

                # Optimize: cap steps at 50 to reduce CPU load (was 100)
                steps = min(50, max(10, int(duration * 60)))

                for i in range(steps + 1):
                    progress = i / steps
                    # Ease in-out cubic
                    if progress < 0.5:
                        eased = 4 * progress * progress * progress
                    else:
                        eased = 1 - pow(-2 * progress + 2, 3) / 2

                    inter_x = int(current_x + (x - current_x) * eased)
                    inter_y = int(current_y + (y - current_y) * eased)

                    self._move_mouse_absolute(inter_x, inter_y)
                    time.sleep(duration / steps)
            else:
                self._move_mouse_absolute(x, y)

            logger.debug(f"Mouse moved to ({x}, {y})")  # Changed to debug to reduce log spam
            return True
        except Exception as e:
            logger.error(f"Mouse move failed: {e}")
            return False

    def _move_mouse_absolute(self, x, y):
        """Move mouse using SendInput with absolute positioning."""
        norm_x, norm_y = self._normalize_coordinates(x, y)

        # Create mouse input structure
        mouse_input = MOUSEINPUT()
        mouse_input.dx = norm_x
        mouse_input.dy = norm_y
        mouse_input.mouseData = 0
        mouse_input.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        mouse_input.time = 0
        mouse_input.dwExtraInfo = self._null_ptr

        # Create INPUT structure
        input_struct = INPUT()
        input_struct.type = INPUT_MOUSE
        input_struct.union.mi = mouse_input

        # Send input
        result = self.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))

        if result == 0:
            # Fallback to win32api (only log on first failure to reduce spam)
            win32api.SetCursorPos((x, y))

    def click_mouse(self, x, y, button='left', move_duration=0.3, click_delay=0.1):
        """
        Click mouse at position using SendInput.

        Args:
            x, y: Screen coordinates
            button: 'left', 'right', or 'middle'
            move_duration: Time to move to position
            click_delay: Delay before clicking
        """
        try:
            # Move to position
            self.move_mouse(x, y, smooth=True, duration=move_duration)

            # Wait before clicking
            if click_delay > 0:
                time.sleep(click_delay)

            # Determine button flags
            if button == 'left':
                down_flag = MOUSEEVENTF_LEFTDOWN
                up_flag = MOUSEEVENTF_LEFTUP
            elif button == 'right':
                down_flag = MOUSEEVENTF_RIGHTDOWN
                up_flag = MOUSEEVENTF_RIGHTUP
            elif button == 'middle':
                down_flag = MOUSEEVENTF_MIDDLEDOWN
                up_flag = MOUSEEVENTF_MIDDLEUP
            else:
                logger.error(f"Invalid button: {button}")
                return False

            # Mouse down
            self._send_mouse_event(down_flag)
            time.sleep(0.05)  # Brief hold

            # Mouse up
            self._send_mouse_event(up_flag)

            logger.info(f"{button.capitalize()} click at ({x}, {y})")
            return True

        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    def _send_mouse_event(self, flags):
        """Send a mouse event using SendInput."""
        mouse_input = MOUSEINPUT()
        mouse_input.dx = 0
        mouse_input.dy = 0
        mouse_input.mouseData = 0
        mouse_input.dwFlags = flags
        mouse_input.time = 0
        mouse_input.dwExtraInfo = self._null_ptr

        input_struct = INPUT()
        input_struct.type = INPUT_MOUSE
        input_struct.union.mi = mouse_input

        result = self.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))

        if result == 0:
            # Fallback to win32api
            if flags == MOUSEEVENTF_LEFTDOWN:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
            elif flags == MOUSEEVENTF_LEFTUP:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            elif flags == MOUSEEVENTF_RIGHTDOWN:
                win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0)
            elif flags == MOUSEEVENTF_RIGHTUP:
                win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0)

    def press_key(self, key_name):
        """Press and release a key using SendInput."""
        try:
            # Normalize key name
            key_lower = key_name.lower().replace('_', '')

            # Map common variations
            key_map = {
                'esc': 'escape',
                'return': 'enter',
                'up': 'up_arrow',
                'down': 'down_arrow',
                'left': 'left_arrow',
                'right': 'right_arrow',
                'pageup': 'page_up',
                'pagedown': 'page_down',
                'capslock': 'caps_lock'
            }

            key_lower = key_map.get(key_lower, key_lower)

            # Get virtual key code
            if key_lower in VK_CODES:
                vk_code = VK_CODES[key_lower]
            elif len(key_name) == 1:
                # Single character
                vk_code = ord(key_name.upper())
            else:
                logger.warning(f"Unknown key '{key_name}', trying pyautogui fallback")
                try:
                    pyautogui.press(key_name)
                    logger.info(f"Pressed key via pyautogui: {key_name}")
                    return True
                except:
                    logger.error(f"Unknown key and fallback failed: {key_name}")
                    return False

            # Key down
            result1 = self._send_key_event(vk_code, False)
            time.sleep(0.05)

            # Key up
            result2 = self._send_key_event(vk_code, True)

            # Check if SendInput succeeded
            if result1 == 0 or result2 == 0:
                logger.warning(f"SendInput failed for key '{key_name}', using pyautogui fallback")
                try:
                    pyautogui.press(key_name)
                    logger.info(f"Pressed key via pyautogui: {key_name}")
                    return True
                except Exception as e:
                    logger.error(f"Fallback also failed: {e}")
                    return False

            logger.info(f"Pressed key: {key_name} (VK: 0x{vk_code:02X})")
            return True

        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return False

    def _send_key_event(self, vk_code, key_up=False):
        """Send a keyboard event using SendInput."""
        # Get hardware scan code for the virtual key
        scan_code = self.user32.MapVirtualKeyW(vk_code, 0)

        kbd_input = KEYBDINPUT()
        kbd_input.wVk = vk_code
        kbd_input.wScan = scan_code
        kbd_input.dwFlags = KEYEVENTF_KEYUP if key_up else 0
        kbd_input.time = 0
        kbd_input.dwExtraInfo = self._null_ptr

        input_struct = INPUT()
        input_struct.type = INPUT_KEYBOARD
        input_struct.union.ki = kbd_input

        result = self.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
        return result

    def press_hotkey(self, keys):
        """
        Press multiple keys together (hotkey combination).

        Args:
            keys: List of key names to press together (e.g., ['ctrl', 's'])
        """
        try:
            # Normalize and get VK codes
            vk_codes = []
            for key in keys:
                key_lower = key.lower().replace('_', '')
                key_map = {
                    'esc': 'escape',
                    'return': 'enter',
                    'up': 'up_arrow',
                    'down': 'down_arrow',
                    'left': 'left_arrow',
                    'right': 'right_arrow'
                }
                key_lower = key_map.get(key_lower, key_lower)

                if key_lower in VK_CODES:
                    vk_codes.append(VK_CODES[key_lower])
                elif len(key) == 1:
                    vk_codes.append(ord(key.upper()))
                else:
                    logger.error(f"Unknown key in hotkey: {key}")
                    return False

            # Press all keys down
            for vk_code in vk_codes:
                self._send_key_event(vk_code, False)
                time.sleep(0.01)

            time.sleep(0.05)

            # Release all keys in reverse order
            for vk_code in reversed(vk_codes):
                self._send_key_event(vk_code, True)
                time.sleep(0.01)

            logger.info(f"Pressed hotkey: {'+'.join(keys)}")
            return True

        except Exception as e:
            logger.error(f"Hotkey press failed: {e}")
            return False

    def double_click(self, x, y, button='left', move_duration=0.3):
        """Double-click at position."""
        try:
            # Move to position
            self.move_mouse(x, y, smooth=True, duration=move_duration)
            time.sleep(0.1)

            # Determine button flags
            if button == 'left':
                down_flag = MOUSEEVENTF_LEFTDOWN
                up_flag = MOUSEEVENTF_LEFTUP
            elif button == 'right':
                down_flag = MOUSEEVENTF_RIGHTDOWN
                up_flag = MOUSEEVENTF_RIGHTUP
            else:
                logger.error(f"Invalid button for double-click: {button}")
                return False

            # First click
            self._send_mouse_event(down_flag)
            time.sleep(0.05)
            self._send_mouse_event(up_flag)
            time.sleep(0.05)

            # Second click
            self._send_mouse_event(down_flag)
            time.sleep(0.05)
            self._send_mouse_event(up_flag)

            logger.info(f"Double-clicked {button} at ({x}, {y})")
            return True

        except Exception as e:
            logger.error(f"Double-click failed: {e}")
            return False

    def drag(self, x1, y1, x2, y2, button='left', duration=1.0):
        """
        Drag from one position to another.

        Args:
            x1, y1: Starting coordinates
            x2, y2: Ending coordinates
            button: Mouse button to use
            duration: Duration of drag in seconds
        """
        try:
            # Move to start position
            self.move_mouse(x1, y1, smooth=True, duration=0.3)
            time.sleep(0.1)

            # Determine button flags
            if button == 'left':
                down_flag = MOUSEEVENTF_LEFTDOWN
                up_flag = MOUSEEVENTF_LEFTUP
            elif button == 'right':
                down_flag = MOUSEEVENTF_RIGHTDOWN
                up_flag = MOUSEEVENTF_RIGHTUP
            else:
                logger.error(f"Invalid button for drag: {button}")
                return False

            # Press button down
            self._send_mouse_event(down_flag)
            time.sleep(0.1)

            # Move to end position while holding button
            self.move_mouse(x2, y2, smooth=True, duration=duration)
            time.sleep(0.1)

            # Release button
            self._send_mouse_event(up_flag)

            logger.info(f"Dragged from ({x1}, {y1}) to ({x2}, {y2})")
            return True

        except Exception as e:
            logger.error(f"Drag failed: {e}")
            return False

    def type_text(self, text, char_delay=0.05):
        """Type text character by character."""
        try:
            for char in text:
                if char == '\n':
                    self.press_key('enter')
                elif char == '\t':
                    self.press_key('tab')
                else:
                    # Use pyautogui as fallback for complex characters
                    pyautogui.write(char, interval=0)

                if char_delay > 0:
                    time.sleep(char_delay)

            logger.info(f"Typed text: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Type text failed: {e}")
            return False

    def scroll(self, x, y, clicks, direction='up'):
        """Scroll at position."""
        try:
            # Move to position first
            self.move_mouse(x, y, smooth=False, duration=0)
            time.sleep(0.05)

            # Calculate scroll amount (120 units per click)
            scroll_amount = 120 if direction == 'up' else -120

            # Optimize: send all scroll events without recalculating position
            for _ in range(clicks):
                mouse_input = MOUSEINPUT()
                mouse_input.dx = 0  # Relative scrolling, no position needed
                mouse_input.dy = 0
                mouse_input.mouseData = scroll_amount
                mouse_input.dwFlags = MOUSEEVENTF_WHEEL  # Removed ABSOLUTE flag
                mouse_input.time = 0
                mouse_input.dwExtraInfo = self._null_ptr

                input_struct = INPUT()
                input_struct.type = INPUT_MOUSE
                input_struct.union.mi = mouse_input

                self.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
                time.sleep(0.02)  # Reduced delay from 0.05 to 0.02

            logger.debug(f"Scrolled {direction} {clicks} times")  # Changed to debug
            return True

        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return False

# Initialize controller
input_controller = ImprovedInputController()

# Process management functions
def find_process_by_name(process_name):
    """Find a running process by its name."""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if (proc.info['name'] and process_name.lower() in proc.info['name'].lower()) or \
                   (proc.info['exe'] and process_name.lower() in os.path.basename(proc.info['exe']).lower()):
                    logger.info(f"Found process: {proc.info['name']} (PID: {proc.info['pid']})")
                    return psutil.Process(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        logger.error(f"Error searching for process {process_name}: {str(e)}")
    return None

def terminate_process_by_name(process_name):
    """Terminate a process by its name."""
    try:
        processes_terminated = []
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if (proc.info['name'] and process_name.lower() in proc.info['name'].lower()) or \
                   (proc.info['exe'] and process_name.lower() in os.path.basename(proc.info['exe']).lower()):

                    process = psutil.Process(proc.info['pid'])
                    logger.info(f"Terminating process: {proc.info['name']} (PID: {proc.info['pid']})")

                    process.terminate()
                    try:
                        process.wait(timeout=5)
                        processes_terminated.append(proc.info['name'])
                    except psutil.TimeoutExpired:
                        logger.warning(f"Force killing process: {proc.info['name']}")
                        process.kill()
                        processes_terminated.append(proc.info['name'])

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if processes_terminated:
            logger.info(f"Successfully terminated processes: {processes_terminated}")
            return True
        else:
            logger.info(f"No processes found with name: {process_name}")
            return False

    except Exception as e:
        logger.error(f"Error terminating process {process_name}: {str(e)}")
        return False

# Flask routes
@app.route('/status', methods=['GET'])
def status():
    """Enhanced status endpoint."""
    return jsonify({
        "status": "running",
        "version": "3.1-optimized",
        "input_method": "SendInput",
        "admin_privileges": is_admin(),
        "capabilities": [
            "sendinput_clicks", "sendinput_mouse", "smooth_movement",
            "keyboard_input", "hotkey_support", "double_click", "drag_drop",
            "scroll", "process_management", "text_input"
        ]
    })

@app.route('/screenshot', methods=['GET'])
def screenshot():
    """Capture and return a screenshot."""
    try:
        monitor = request.args.get('monitor', '0')
        region = request.args.get('region')

        if region:
            x, y, width, height = map(int, region.split(','))
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
        else:
            screenshot = pyautogui.screenshot()

        img_buffer = BytesIO()
        screenshot.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        logger.info(f"Screenshot captured (region: {region})")
        return send_file(img_buffer, mimetype='image/png')
    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/launch', methods=['POST'])
def launch_game():
    """Launch a game with process tracking."""
    global game_process, current_game_process_name

    try:
        data = request.json
        game_path = data.get('path', '')
        process_id = data.get('process_id', '')

        if not game_path or not os.path.exists(game_path):
            logger.error(f"Game path not found: {game_path}")
            return jsonify({"status": "error", "error": "Game executable not found"}), 404

        with game_lock:
            # Terminate existing game if running
            if current_game_process_name:
                logger.info(f"Terminating existing game: {current_game_process_name}")
                terminate_process_by_name(current_game_process_name)
                current_game_process_name = None

            if game_process and game_process.poll() is None:
                logger.info("Terminating existing subprocess")
                game_process.terminate()
                try:
                    game_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    game_process.kill()

            # Launch game
            logger.info(f"Launching game: {game_path}")
            current_game_process_name = process_id if process_id else os.path.splitext(os.path.basename(game_path))[0]

            game_process = subprocess.Popen(game_path)
            logger.info(f"Subprocess started with PID: {game_process.pid}")

            time.sleep(3)
            subprocess_status = "running" if game_process.poll() is None else "exited"

            # Wait for actual game process
            max_wait_time = 15
            actual_process = None

            for i in range(max_wait_time):
                time.sleep(1)
                actual_process = find_process_by_name(current_game_process_name)
                if actual_process:
                    logger.info(f"Game process found: {actual_process.name()} (PID: {actual_process.pid})")
                    break

            response_data = {
                "status": "success",
                "subprocess_pid": game_process.pid,
                "subprocess_status": subprocess_status
            }

            if actual_process:
                response_data["game_process_pid"] = actual_process.pid
                response_data["game_process_name"] = actual_process.name()
                logger.info(f"Game launched successfully")
            else:
                logger.warning(f"Game process not detected within {max_wait_time}s")
                response_data["warning"] = f"Game process not detected"

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error launching game: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/action', methods=['POST'])
def perform_action():
    """Enhanced action handler using SendInput."""
    try:
        data = request.json
        action_type = data.get('type', '').lower()

        logger.info(f"Executing action: {action_type}")

        if action_type == 'click':
            x = data.get('x', 0)
            y = data.get('y', 0)
            button = data.get('button', 'left').lower()
            move_duration = data.get('move_duration', 0.3)
            click_delay = data.get('click_delay', 0.1)

            success = input_controller.click_mouse(x, y, button, move_duration, click_delay)

            if success:
                return jsonify({
                    "status": "success",
                    "action": "click",
                    "coordinates": [x, y],
                    "button": button
                })
            else:
                return jsonify({"status": "error", "error": "Click failed"}), 500

        elif action_type in ['key', 'keypress']:
            key = data.get('key', '')
            success = input_controller.press_key(key)

            if success:
                return jsonify({"status": "success", "action": "keypress", "key": key})
            else:
                return jsonify({"status": "error", "error": "Key press failed"}), 500

        elif action_type in ['text', 'type', 'input']:
            text = data.get('text', '')
            char_delay = data.get('char_delay', 0.05)
            success = input_controller.type_text(text, char_delay)

            if success:
                return jsonify({"status": "success", "action": "text_input", "text_length": len(text)})
            else:
                return jsonify({"status": "error", "error": "Text input failed"}), 500

        elif action_type == 'scroll':
            x = data.get('x', 0)
            y = data.get('y', 0)
            direction = data.get('direction', 'up').lower()
            clicks = data.get('clicks', 3)

            success = input_controller.scroll(x, y, clicks, direction)

            if success:
                return jsonify({
                    "status": "success",
                    "action": "scroll",
                    "direction": direction,
                    "clicks": clicks
                })
            else:
                return jsonify({"status": "error", "error": "Scroll failed"}), 500

        elif action_type == 'hotkey':
            keys = data.get('keys', [])
            if not keys:
                return jsonify({"status": "error", "error": "No keys provided"}), 400

            success = input_controller.press_hotkey(keys)

            if success:
                return jsonify({
                    "status": "success",
                    "action": "hotkey",
                    "keys": keys
                })
            else:
                return jsonify({"status": "error", "error": "Hotkey failed"}), 500

        elif action_type == 'double_click':
            x = data.get('x', 0)
            y = data.get('y', 0)
            button = data.get('button', 'left').lower()
            move_duration = data.get('move_duration', 0.3)

            success = input_controller.double_click(x, y, button, move_duration)

            if success:
                return jsonify({
                    "status": "success",
                    "action": "double_click",
                    "coordinates": [x, y],
                    "button": button
                })
            else:
                return jsonify({"status": "error", "error": "Double-click failed"}), 500

        elif action_type == 'drag':
            x1 = data.get('x1', 0)
            y1 = data.get('y1', 0)
            x2 = data.get('x2', 0)
            y2 = data.get('y2', 0)
            button = data.get('button', 'left').lower()
            duration = data.get('duration', 1.0)

            success = input_controller.drag(x1, y1, x2, y2, button, duration)

            if success:
                return jsonify({
                    "status": "success",
                    "action": "drag",
                    "start": [x1, y1],
                    "end": [x2, y2]
                })
            else:
                return jsonify({"status": "error", "error": "Drag failed"}), 500

        elif action_type == 'wait':
            duration = data.get('duration', 1)
            logger.info(f"Waiting for {duration} seconds")
            time.sleep(duration)
            return jsonify({"status": "success", "action": "wait", "duration": duration})

        elif action_type == 'terminate_game':
            with game_lock:
                terminated = False

                if current_game_process_name:
                    if terminate_process_by_name(current_game_process_name):
                        terminated = True

                if game_process and game_process.poll() is None:
                    game_process.terminate()
                    try:
                        game_process.wait(timeout=5)
                        terminated = True
                    except subprocess.TimeoutExpired:
                        game_process.kill()
                        terminated = True

                message = "Game terminated" if terminated else "No game running"
                return jsonify({
                    "status": "success",
                    "action": "terminate_game",
                    "message": message
                })

        else:
            return jsonify({"status": "error", "error": f"Unknown action: {action_type}"}), 400

    except Exception as e:
        logger.error(f"Error performing action: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        health_status = {
            "service": "running",
            "version": "3.1-optimized",
            "input_method": "SendInput + win32api fallback",
            "admin_privileges": is_admin(),
            "screen_resolution": f"{input_controller.screen_width}x{input_controller.screen_height}"
        }

        if current_game_process_name:
            game_proc = find_process_by_name(current_game_process_name)
            health_status["game_process"] = "running" if game_proc else "not_found"
        else:
            health_status["game_process"] = "none"

        return jsonify({"status": "success", "health": health_status})

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Improved SUT Service v3.1')
    parser.add_argument('--port', type=int, default=8080, help='Port to run on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Improved SUT Service v3.1 - Optimized for Performance")
    logger.info("=" * 70)
    logger.info(f"Starting service on {args.host}:{args.port}")
    logger.info(f"Admin privileges: {'YES' if is_admin() else 'NO (some features may not work)'}")
    logger.info(f"Screen resolution: {input_controller.screen_width}x{input_controller.screen_height}")
    logger.info("")
    logger.info("Optimizations:")
    logger.info("  * Reduced mouse movement steps (50 max, ~40% faster)")
    logger.info("  * Reusable pointer allocations (reduced memory)")
    logger.info("  * Optimized scroll with relative positioning")
    logger.info("  * Proper scan codes for keyboard (better game compatibility)")
    logger.info("")
    logger.info("Supported Actions:")
    logger.info("  + Mouse clicks (left/right/middle)")
    logger.info("  + Double-click")
    logger.info("  + Drag and drop")
    logger.info("  + Smooth mouse movement with easing")
    logger.info("  + Keyboard input (single keys)")
    logger.info("  + Hotkeys (Ctrl+S, Alt+Tab, etc.)")
    logger.info("  + Text input")
    logger.info("  + Mouse scrolling (optimized)")
    logger.info("  + Process management")
    logger.info("=" * 70)

    if not is_admin():
        logger.warning("WARNING: Not running with administrator privileges!")
        logger.warning("Some games may block input. Run as administrator for best results.")
        logger.warning("")

    app.run(host=args.host, port=args.port, debug=args.debug)
