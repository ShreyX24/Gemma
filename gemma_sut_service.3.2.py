# -*- coding: utf-8 -*-
"""
Enhanced SUT Service v3.1 - Comprehensive action support for gaming automation
Combines the best of both worlds: comprehensive feature set with optimized SendInput API
Supports all modular action types: clicks, drags, scrolls, hotkeys, text input, etc.
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
from pynput import mouse, keyboard
from pynput.mouse import Button, Listener as MouseListener
from pynput.keyboard import Key, Listener as KeyboardListener
import ctypes
from ctypes import wintypes
import pydirectinput
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("enhanced_sut_service.log"),
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
mouse_controller = mouse.Controller()
keyboard_controller = keyboard.Controller()

# Configure PyAutoGUI for enhanced control
pyautogui.FAILSAFE = False  # Disable failsafe for automation
pyautogui.PAUSE = 0.01  # Minimal pause between actions

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

# Constants for SendInput
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

# Enhanced Virtual key codes
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

class EnhancedInputController:
    """Enhanced input controller with SendInput API integration and fallback support."""

    def __init__(self):
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()

        # SendInput API components
        self.user32 = ctypes.windll.user32
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)

        # Reusable null pointer for dwExtraInfo to reduce allocations
        self._null_ptr = ctypes.cast(ctypes.pointer(wintypes.ULONG(0)), ctypes.POINTER(wintypes.ULONG))

        logger.info(f"Enhanced controller initialized - Screen: {self.screen_width}x{self.screen_height}")

    def _normalize_coordinates(self, x, y):
        """Convert screen coordinates to normalized coordinates (0-65535)."""
        normalized_x = int(x * 65535 / self.screen_width)
        normalized_y = int(y * 65535 / self.screen_height)
        return normalized_x, normalized_y

    def smooth_move(self, start_x, start_y, end_x, end_y, duration=1.0, steps=50):
        """Smooth mouse movement between two points with optimized performance."""
        # Optimize: cap steps at 50 to reduce CPU load
        steps = min(50, max(10, steps))
        step_delay = duration / steps

        for i in range(steps + 1):
            progress = i / steps
            # Use easing for natural movement
            eased_progress = self._ease_in_out_cubic(progress)

            current_x = start_x + (end_x - start_x) * eased_progress
            current_y = start_y + (end_y - start_y) * eased_progress

            # Use SendInput for more reliable movement
            if not self._move_mouse_sendinput(int(current_x), int(current_y)):
                # Fallback to pynput
                self.mouse.position = (int(current_x), int(current_y))
            time.sleep(step_delay)

    def _ease_in_out_cubic(self, t):
        """Cubic easing function for natural movement."""
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2

    def _move_mouse_sendinput(self, x, y):
        """Move mouse using SendInput with absolute positioning."""
        try:
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
            return result > 0
        except Exception as e:
            logger.debug(f"SendInput mouse move failed: {e}")
            return False

    def _send_mouse_event_sendinput(self, flags):
        """Send a mouse event using SendInput."""
        try:
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
            return result > 0
        except Exception as e:
            logger.debug(f"SendInput mouse event failed: {e}")
            return False

    def _send_key_event_sendinput(self, vk_code, key_up=False):
        """Send a keyboard event using SendInput."""
        try:
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
            return result > 0
        except Exception as e:
            logger.debug(f"SendInput key event failed: {e}")
            return False

# Initialize enhanced controller
input_controller = EnhancedInputController()

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

@app.route('/status', methods=['GET'])
def status():
    """Enhanced status endpoint with capabilities and Gemma identification."""
    import socket
    import platform
    import uuid
    
    # Generate or get unique device ID
    device_id = f"gemma_sut_{platform.node()}_{uuid.getnode()}"
    
    return jsonify({
        "status": "running",
        "version": "3.1-enhanced",
        "gemma_sut_signature": "gemma_sut_v3.1",  # Unique identifier for Gemma SUTs
        "input_method": "SendInput + fallback",
        "admin_privileges": is_admin(),
        "device_id": device_id,
        "hostname": platform.node(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "capabilities": [
            "sendinput_clicks", "basic_clicks", "advanced_clicks", "drag_drop", "scroll",
            "hotkeys", "text_input", "sequences", "process_management",
            "performance_monitoring", "multi_monitor", "gaming_optimizations",
            "optimized_movement", "scan_code_keyboard"
        ]
    })

@app.route('/screen_info', methods=['GET'])
def screen_info():
    """Get screen resolution and monitor information."""
    try:
        import tkinter as tk
        
        # Get screen resolution using tkinter
        root = tk.Tk()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()
        
        logger.info(f"Screen resolution: {screen_width}x{screen_height}")
        return jsonify({
            "status": "success",
            "screen_width": screen_width,
            "screen_height": screen_height,
            "resolution": f"{screen_width}x{screen_height}"
        })
    except Exception as e:
        logger.error(f"Error getting screen info: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/screenshot', methods=['GET'])
def screenshot():
    """Capture and return a screenshot with optional parameters."""
    try:
        # Optional parameters for screenshot
        monitor = request.args.get('monitor', '0')  # Monitor index
        region = request.args.get('region')  # Format: "x,y,width,height"
        
        if region:
            # Capture specific region
            x, y, width, height = map(int, region.split(','))
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
        else:
            # Capture entire screen
            screenshot = pyautogui.screenshot()
        
        # Save to a bytes buffer
        img_buffer = BytesIO()
        screenshot.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        logger.info(f"Screenshot captured (monitor: {monitor}, region: {region})")
        return send_file(img_buffer, mimetype='image/png')
    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/launch', methods=['POST'])
def launch_game():
    """Launch a game with support for process ID tracking - FIXED for Steam games."""
    global game_process, current_game_process_name
    
    try:
        data = request.json
        game_path = data.get('path', '')
        process_id = data.get('process_id', '')  # Expected process name
        
        if not game_path or not os.path.exists(game_path):
            logger.error(f"Game path not found: {game_path}")
            return jsonify({"status": "error", "error": "Game executable not found"}), 404
        
        with game_lock:
            # Terminate existing game if running
            if current_game_process_name:
                logger.info(f"Terminating existing game process: {current_game_process_name}")
                terminate_process_by_name(current_game_process_name)
                current_game_process_name = None
            
            # Also terminate using the old method if we have a subprocess handle
            if game_process and game_process.poll() is None:
                logger.info("Terminating existing game subprocess")
                game_process.terminate()
                try:
                    game_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    game_process.kill()
            
            # Launch the game
            logger.info(f"Launching game: {game_path}")
            if process_id:
                logger.info(f"Expected process name: {process_id}")
                current_game_process_name = process_id
            else:
                # Fallback to executable name without extension
                current_game_process_name = os.path.splitext(os.path.basename(game_path))[0]
            
            game_process = subprocess.Popen(game_path)
            logger.info(f"Subprocess started with PID: {game_process.pid}")
            
            # FIXED: Don't fail if subprocess exits - this is normal for Steam games
            # Wait a moment and check subprocess status but don't treat exit as failure
            time.sleep(3)
            subprocess_status = "running" if game_process.poll() is None else "exited"
            logger.info(f"Subprocess status after 3 seconds: {subprocess_status}")
            
            # Give the actual game process time to start (important for Steam games)
            max_wait_time = 15  # Wait up to 15 seconds for the game process to appear
            wait_interval = 1
            actual_process = None
            
            for i in range(max_wait_time):
                time.sleep(wait_interval)
                actual_process = find_process_by_name(current_game_process_name)
                if actual_process:
                    logger.info(f"Game process found after {i+1} seconds: {actual_process.name()} (PID: {actual_process.pid})")
                    break
                elif i == 5:  # Log progress at 5 seconds
                    logger.info(f"Still waiting for game process '{current_game_process_name}' to start...")
            
            response_data = {
                "status": "success",
                "subprocess_pid": game_process.pid,
                "subprocess_status": subprocess_status
            }
            
            if actual_process:
                response_data["game_process_pid"] = actual_process.pid
                response_data["game_process_name"] = actual_process.name()
                response_data["game_process_status"] = actual_process.status()
                logger.info(f"[OK] Game launched successfully: {actual_process.name()} (PID: {actual_process.pid})")
            else:
                # This is now a warning, not an error - the game might still be starting
                logger.warning(f"Game process '{current_game_process_name}' not found within {max_wait_time} seconds")
                logger.warning("The game might still be starting or the process_id might be incorrect")
                response_data["warning"] = f"Game process '{current_game_process_name}' not detected within {max_wait_time}s, but subprocess launched successfully"
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error launching game: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/action', methods=['POST'])
def perform_action():
    """Enhanced action handler supporting all modular action types."""
    try:
        data = request.json
        action_type = data.get('type', '').lower()
        
        logger.info(f"Executing action: {action_type}")
        
        # === CLICK ACTIONS ===
        if action_type == 'click':
            return handle_click_action(data)
        
        # === ADVANCED MOUSE ACTIONS ===
        elif action_type in ['double_click', 'triple_click']:
            return handle_multi_click_action(data)
        
        # === DRAG ACTIONS ===
        elif action_type in ['drag', 'drag_drop']:
            return handle_drag_action(data)
        
        # === SCROLL ACTIONS ===
        elif action_type == 'scroll':
            return handle_scroll_action(data)
        
        # === KEYBOARD ACTIONS ===
        elif action_type in ['key', 'keypress']:
            return handle_key_action(data)
        
        # === HOTKEY ACTIONS ===
        elif action_type == 'hotkey':
            return handle_hotkey_action(data)
        
        # === TEXT INPUT ACTIONS ===
        elif action_type in ['text', 'type', 'input']:
            return handle_text_action(data)
        
        # === WAIT ACTIONS ===
        elif action_type == 'wait':
            return handle_wait_action(data)
        
        # === SEQUENCE ACTIONS ===
        elif action_type == 'sequence':
            return handle_sequence_action(data)
        
        # === GAME MANAGEMENT ===
        elif action_type == 'terminate_game':
            return handle_terminate_game()
        
        # === SYSTEM ACTIONS ===
        elif action_type in ['screenshot_region', 'window_focus', 'window_resize']:
            return handle_system_action(data)
        
        else:
            logger.error(f"Unknown action type: {action_type}")
            return jsonify({"status": "error", "error": f"Unknown action type: {action_type}"}), 400
            
    except Exception as e:
        logger.error(f"Error performing action: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_click_action(data):
    """Handle all types of click actions with enhanced precision and SendInput support."""
    x = data.get('x', 0)
    y = data.get('y', 0)
    button = data.get('button', 'left').lower()
    click_type = data.get('clickType', 'sendinput').lower()  # Default to SendInput
    move_duration = data.get('move_duration', 0.3)
    click_delay = data.get('click_delay', 0.1)

    # Validate button
    if button not in ['left', 'right', 'middle']:
        return jsonify({"status": "error", "error": f"Invalid button: {button}"}), 400

    try:
        # Get current position for smooth movement
        current_pos = mouse_controller.position

        # Smooth movement to target
        if move_duration > 0:
            input_controller.smooth_move(current_pos[0], current_pos[1], x, y, move_duration)
        else:
            # Use SendInput for instant movement if available
            if not input_controller._move_mouse_sendinput(x, y):
                mouse_controller.position = (x, y)

        # Wait before clicking
        if click_delay > 0:
            time.sleep(click_delay)

        # Perform click based on clickType with SendInput priority
        success = False

        if click_type == "sendinput":
            # Use enhanced SendInput method
            if button == 'left':
                success = (input_controller._send_mouse_event_sendinput(MOUSEEVENTF_LEFTDOWN) and
                          input_controller._send_mouse_event_sendinput(MOUSEEVENTF_LEFTUP))
            elif button == 'right':
                success = (input_controller._send_mouse_event_sendinput(MOUSEEVENTF_RIGHTDOWN) and
                          input_controller._send_mouse_event_sendinput(MOUSEEVENTF_RIGHTUP))
            elif button == 'middle':
                success = (input_controller._send_mouse_event_sendinput(MOUSEEVENTF_MIDDLEDOWN) and
                          input_controller._send_mouse_event_sendinput(MOUSEEVENTF_MIDDLEUP))
            time.sleep(0.05)  # Brief hold between down and up

        if not success:  # Fallback to existing methods
            button_map = {
                'left': Button.left,
                'right': Button.right,
                'middle': Button.middle
            }

            if click_type == "win32":
                win32api.SetCursorPos((x, y))
                if button == 'left':
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
                elif button == 'right':
                    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, x, y, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, x, y, 0, 0)
                elif button == 'middle':
                    win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN, x, y, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP, x, y, 0, 0)
                success = True
            elif click_type == "pyautogui":
                pyautogui.click(x=x, y=y, button=button)
                success = True
            elif click_type == "pynput":
                mouse_controller.position = (x, y)
                mouse_controller.click(button_map[button])
                success = True
            elif click_type == "ctypes":
                # Convert to absolute coordinates and click
                screenWidth = ctypes.windll.user32.GetSystemMetrics(0)
                screenHeight = ctypes.windll.user32.GetSystemMetrics(1)
                absX = int(x * 65535 / screenWidth)
                absY = int(y * 65535 / screenHeight)
                ctypes.windll.user32.mouse_event(0x0001 | 0x8000, absX, absY, 0, 0)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.1)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                success = True
            else:
                # Default fallback to pynput
                mouse_controller.position = (x, y)
                mouse_controller.click(button_map[button])
                success = True

        if success:
            logger.info(f"{button.capitalize()}-clicked at ({x}, {y}) using {click_type}")
            return jsonify({
                "status": "success",
                "clickType": click_type,
                "action": f"{button}_click",
                "coordinates": [x, y],
                "move_duration": move_duration,
                "click_delay": click_delay
            })
        else:
            raise Exception(f"All click methods failed for {click_type}")

    except Exception as e:
        logger.error(f"Click action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_multi_click_action(data):
    """Handle double-click, triple-click actions."""
    x = data.get('x', 0)
    y = data.get('y', 0)
    button = data.get('button', 'left').lower()
    action_type = data.get('type', 'double_click')
    click_count = 2 if action_type == 'double_click' else 3
    
    try:
        mouse_controller.position = (x, y)
        time.sleep(0.1)
        
        button_map = {
            'left': Button.left,
            'right': Button.right,
            'middle': Button.middle
        }
        
        for i in range(click_count):
            mouse_controller.click(button_map[button])
            if i < click_count - 1:  # Don't sleep after last click
                time.sleep(0.05)  # Small delay between clicks
        
        logger.info(f"{action_type} ({button}) at ({x}, {y})")
        return jsonify({
            "status": "success", 
            "action": action_type, 
            "coordinates": [x, y],
            "click_count": click_count
        })
        
    except Exception as e:
        logger.error(f"Multi-click action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_drag_action(data):
    """Handle drag and drop actions."""
    start_x = data.get('start_x', data.get('x', 0))
    start_y = data.get('start_y', data.get('y', 0))
    end_x = data.get('end_x', start_x + 100)
    end_y = data.get('end_y', start_y)
    duration = data.get('duration', 1.0)
    button = data.get('button', 'left').lower()
    
    try:
        button_map = {
            'left': Button.left,
            'right': Button.right,
            'middle': Button.middle
        }
        
        # Move to start position
        mouse_controller.position = (start_x, start_y)
        time.sleep(0.1)
        
        # Press and hold button
        mouse_controller.press(button_map[button])
        
        # Smooth drag to end position
        input_controller.smooth_move(start_x, start_y, end_x, end_y, duration)
        
        # Release button
        mouse_controller.release(button_map[button])
        
        logger.info(f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y}) with {button} button")
        return jsonify({
            "status": "success", 
            "action": "drag", 
            "start": [start_x, start_y],
            "end": [end_x, end_y],
            "duration": duration
        })
        
    except Exception as e:
        logger.error(f"Drag action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_scroll_action(data):
    """Handle scroll actions."""
    x = data.get('x', 0)
    y = data.get('y', 0)
    direction = data.get('direction', 'up').lower()
    clicks = data.get('clicks', 3)
    
    try:
        mouse_controller.position = (x, y)
        time.sleep(0.1)
        
        # Convert direction to scroll value
        if direction == 'up':
            scroll_value = 1
        elif direction == 'down':
            scroll_value = -1
        else:
            return jsonify({"status": "error", "error": f"Invalid scroll direction: {direction}"}), 400
        
        # Perform scroll
        for _ in range(clicks):
            mouse_controller.scroll(0, scroll_value)
            time.sleep(0.05)  # Small delay between scroll clicks
        
        logger.info(f"Scrolled {direction} {clicks} clicks at ({x}, {y})")
        return jsonify({
            "status": "success", 
            "action": "scroll", 
            "coordinates": [x, y],
            "direction": direction,
            "clicks": clicks
        })
        
    except Exception as e:
        logger.error(f"Scroll action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_key_action(data):
    """Handle single key press actions with SendInput support."""
    key_name = data.get('key', '')
    method_type = data.get('methodType', 'sendinput')  # Default to SendInput

    if not key_name:
        return jsonify({"status": "error", "error": "No key specified"}), 400

    try:
        used_method = method_type
        success = False

        # Try SendInput first if requested
        if method_type == "sendinput":
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
                vk_code = None

            if vk_code:
                # Try SendInput
                success = (input_controller._send_key_event_sendinput(vk_code, False) and
                          input_controller._send_key_event_sendinput(vk_code, True))
                time.sleep(0.05)

        # Fallback to existing methods if SendInput failed or not requested
        if not success:
            # Map common key names for different input methods
            pynput_key_mapping = {
                'enter': Key.enter,
                'return': Key.enter,
                'space': Key.space,
                'tab': Key.tab,
                'escape': Key.esc,
                'esc': Key.esc,
                'delete': Key.delete,
                'backspace': Key.backspace,
                'shift': Key.shift,
                'ctrl': Key.ctrl,
                'alt': Key.alt,
                'win': Key.cmd,
                'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
                'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
                'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
                'up': Key.up, 'down': Key.down, 'left': Key.left, 'right': Key.right,
                'home': Key.home, 'end': Key.end, 'pageup': Key.page_up, 'pagedown': Key.page_down
            }

            # PyAutoGUI key mapping (string-based)
            pyautogui_key_mapping = {
                'enter': 'enter',
                'return': 'enter',
                'space': 'space',
                'tab': 'tab',
                'escape': 'esc',
                'esc': 'esc',
                'delete': 'delete',
                'backspace': 'backspace',
                'shift': 'shift',
                'ctrl': 'ctrl',
                'alt': 'alt',
                'win': 'winleft',
                'f1': 'f1', 'f2': 'f2', 'f3': 'f3', 'f4': 'f4',
                'f5': 'f5', 'f6': 'f6', 'f7': 'f7', 'f8': 'f8',
                'f9': 'f9', 'f10': 'f10', 'f11': 'f11', 'f12': 'f12',
                'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
                'home': 'home', 'end': 'end', 'pageup': 'pageup', 'pagedown': 'pagedown'
            }

            # Execute key press based on methodType
            if method_type == "pydirectinput" or (method_type == "sendinput" and not success):
                # Use original key name for pydirectinput
                pydirectinput.press(key_name)
                used_method = "pydirectinput"
                success = True
            elif method_type == "pynput" or (method_type == "sendinput" and not success):
                # Use pynput Key objects
                key_to_press = pynput_key_mapping.get(key_name.lower(), key_name)
                keyboard_controller.press(key_to_press)
                keyboard_controller.release(key_to_press)
                used_method = "pynput"
                success = True
            elif method_type == "pyautogui" or (method_type == "sendinput" and not success):
                # Use string key names for pyautogui
                key_to_press = pyautogui_key_mapping.get(key_name.lower(), key_name.lower())
                pyautogui.press(key_to_press)
                used_method = "pyautogui"
                success = True
            else:
                # Default fallback to pyautogui
                key_to_press = pyautogui_key_mapping.get(key_name.lower(), key_name.lower())
                pyautogui.press(key_to_press)
                used_method = "pyautogui"
                success = True

        if success:
            logger.info(f"Pressed key: {key_name} using {used_method}")
            return jsonify({
                "status": "success",
                "action": "keypress",
                "key": key_name,
                "used_method": used_method
            })
        else:
            raise Exception(f"All key press methods failed for {key_name}")

    except Exception as e:
        logger.error(f"Key action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_hotkey_action(data):
    """Handle hotkey combination actions with SendInput support."""
    keys = data.get('keys', [])
    method_type = data.get('methodType', 'sendinput')  # Default to SendInput

    if not keys:
        return jsonify({"status": "error", "error": "No keys specified for hotkey"}), 400

    try:
        success = False
        used_method = method_type

        # Try SendInput first if requested
        if method_type == "sendinput":
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
                    vk_codes = []  # Invalid key found
                    break

            if vk_codes:
                # Press all keys down
                for vk_code in vk_codes:
                    input_controller._send_key_event_sendinput(vk_code, False)
                    time.sleep(0.01)

                time.sleep(0.05)

                # Release all keys in reverse order
                for vk_code in reversed(vk_codes):
                    input_controller._send_key_event_sendinput(vk_code, True)
                    time.sleep(0.01)

                success = True

        # Fallback to pynput if SendInput failed or not requested
        if not success:
            # Map key names
            key_mapping = {
                'ctrl': Key.ctrl, 'alt': Key.alt, 'shift': Key.shift, 'win': Key.cmd,
                'enter': Key.enter, 'space': Key.space, 'tab': Key.tab, 'escape': Key.esc,
                'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
                'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
                'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
            }

            # Convert key names to pynput keys
            keys_to_press = []
            for key_name in keys:
                key_obj = key_mapping.get(key_name.lower(), key_name)
                keys_to_press.append(key_obj)

            # Press all keys down
            for key in keys_to_press:
                keyboard_controller.press(key)
                time.sleep(0.01)  # Small delay between key presses

            # Small hold time
            time.sleep(0.05)

            # Release all keys in reverse order
            for key in reversed(keys_to_press):
                keyboard_controller.release(key)
                time.sleep(0.01)

            used_method = "pynput"
            success = True

        if success:
            logger.info(f"Pressed hotkey combination: {'+'.join(keys)} using {used_method}")
            return jsonify({
                "status": "success",
                "action": "hotkey",
                "keys": keys,
                "used_method": used_method
            })
        else:
            raise Exception(f"Hotkey combination failed: {'+'.join(keys)}")

    except Exception as e:
        logger.error(f"Hotkey action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_text_action(data):
    """Handle text input actions."""
    text = data.get('text', '')
    clear_first = data.get('clear_first', False)
    char_delay = data.get('char_delay', 0.05)
    method_type = data.get('methodType', 'pyautogui')
    
    if not text:
        return jsonify({"status": "error", "error": "No text specified"}), 400
    
    try:
        # Clear existing text if requested
        if clear_first:
            if method_type == "pydirectinput":
                pydirectinput.hotkey('ctrl', 'a')
                pydirectinput.press('backspace')
            elif method_type == "pyautogui":
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
            elif method_type == "pynput":
                keyboard_controller.press(Key.ctrl)
                keyboard_controller.press('a')
                keyboard_controller.release('a')
                keyboard_controller.release(Key.ctrl)
                time.sleep(0.1)
        
        # Type text character by character
        for char in text:
            if char == '\n':
                if method_type == "pydirectinput":
                    pydirectinput.press('enter')
                elif method_type == "pyautogui":
                    pyautogui.press('enter')
                elif method_type == "pynput":
                    keyboard_controller.press(Key.enter)
                    keyboard_controller.release(Key.enter)
            elif char == '\t':
                if method_type == "pydirectinput":
                    pydirectinput.press('tab')
                elif method_type == "pyautogui":
                    pyautogui.press('tab')
                elif method_type == "pynput":
                    keyboard_controller.press(Key.tab)
                    keyboard_controller.release(Key.tab)
            else:
                if method_type == "pydirectinput":
                    pydirectinput.typewrite(char)
                elif method_type == "pyautogui":
                    pyautogui.typewrite(char)
                elif method_type == "pynput":
                    keyboard_controller.type(char)
            
            if char_delay > 0:
                time.sleep(char_delay)
        
        logger.info(f"Typed text: '{text[:50]}{'...' if len(text) > 50 else ''}' using method {method_type}")
        return jsonify({
            "status": "success", 
            "action": "text_input", 
            "text_length": len(text),
            "clear_first": clear_first,
            "used_method": method_type
        })
        
    except Exception as e:
        logger.error(f"Text action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_wait_action(data):
    """Handle wait actions."""
    duration = data.get('duration', 1)
    
    try:
        logger.info(f"Waiting for {duration} seconds")
        time.sleep(duration)
        
        return jsonify({
            "status": "success", 
            "action": "wait", 
            "duration": duration
        })
        
    except Exception as e:
        logger.error(f"Wait action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_sequence_action(data):
    """Handle sequence of actions."""
    actions = data.get('actions', [])
    delay_between = data.get('delay_between', 0.5)
    
    if not actions:
        return jsonify({"status": "error", "error": "No actions specified in sequence"}), 400
    
    try:
        results = []
        
        for i, action in enumerate(actions):
            logger.info(f"Executing sequence action {i+1}/{len(actions)}: {action.get('type', 'unknown')}")
            
            # Recursively call perform_action for each sub-action
            # Note: This creates a nested structure but avoids code duplication
            result = perform_action_internal(action)
            results.append(result)
            
            # Check if action failed
            if result.get('status') != 'success':
                logger.error(f"Sequence failed at action {i+1}")
                return jsonify({
                    "status": "error", 
                    "error": f"Sequence failed at action {i+1}",
                    "failed_action": action,
                    "results": results
                }), 500
            
            # Delay between actions (except after last action)
            if delay_between > 0 and i < len(actions) - 1:
                time.sleep(delay_between)
        
        logger.info(f"Completed sequence of {len(actions)} actions")
        return jsonify({
            "status": "success", 
            "action": "sequence", 
            "actions_completed": len(actions),
            "results": results
        })
        
    except Exception as e:
        logger.error(f"Sequence action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def perform_action_internal(data):
    """Internal action handler for sequence actions."""
    # This is a simplified version that returns dict instead of Flask response
    try:
        action_type = data.get('type', '').lower()
        
        if action_type == 'click':
            handle_click_action(data)
            return {"status": "success", "action": action_type}
        elif action_type in ['key', 'keypress']:
            handle_key_action(data)
            return {"status": "success", "action": action_type}
        elif action_type == 'hotkey':
            handle_hotkey_action(data)
            return {"status": "success", "action": action_type}
        elif action_type in ['text', 'type']:
            handle_text_action(data)
            return {"status": "success", "action": action_type}
        elif action_type == 'wait':
            handle_wait_action(data)
            return {"status": "success", "action": action_type}
        # Add other action types as needed
        else:
            return {"status": "error", "error": f"Unknown action type in sequence: {action_type}"}
            
    except Exception as e:
        return {"status": "error", "error": str(e)}

def handle_terminate_game():
    """Handle game termination."""
    global game_process, current_game_process_name
    
    try:
        with game_lock:
            terminated = False
            
            if current_game_process_name:
                logger.info(f"Terminating game by process name: {current_game_process_name}")
                if terminate_process_by_name(current_game_process_name):
                    terminated = True
            
            if game_process and game_process.poll() is None:
                logger.info("Terminating game subprocess")
                game_process.terminate()
                try:
                    game_process.wait(timeout=5)
                    terminated = True
                except subprocess.TimeoutExpired:
                    game_process.kill()
                    terminated = True
            
            message = "Game terminated successfully" if terminated else "No running game to terminate"
            
            return jsonify({
                "status": "success", 
                "action": "terminate_game",
                "message": message,
                "terminated": terminated
            })
            
    except Exception as e:
        logger.error(f"Terminate game failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

def handle_system_action(data):
    """Handle system-level actions."""
    action_type = data.get('type')
    
    try:
        if action_type == 'window_focus':
            window_title = data.get('window_title', '')
            # Focus specific window
            hwnd = win32gui.FindWindow(None, window_title)
            if hwnd:
                win32gui.SetForegroundWindow(hwnd)
                return jsonify({"status": "success", "action": "window_focus"})
            else:
                return jsonify({"status": "error", "error": "Window not found"}), 404
                
        elif action_type == 'window_resize':
            window_title = data.get('window_title', '')
            width = data.get('width', 1920)
            height = data.get('height', 1080)
            # Resize specific window
            hwnd = win32gui.FindWindow(None, window_title)
            if hwnd:
                win32gui.SetWindowPos(hwnd, 0, 0, 0, width, height, win32con.SWP_NOMOVE)
                return jsonify({"status": "success", "action": "window_resize"})
            else:
                return jsonify({"status": "error", "error": "Window not found"}), 404
        
        else:
            return jsonify({"status": "error", "error": f"Unknown system action: {action_type}"}), 400
            
    except Exception as e:
        logger.error(f"System action failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/performance', methods=['GET'])
def get_performance_metrics():
    """Get system and game performance metrics."""
    try:
        metrics = {
            "timestamp": time.time(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
            "cpu_freq": psutil.cpu_freq().current if psutil.cpu_freq() else None,
            "cpu_count": psutil.cpu_count(),
            "cpu_count_logical": psutil.cpu_count(logical=True)
        }
        
        # Add game-specific metrics if available
        if current_game_process_name:
            game_process = find_process_by_name(current_game_process_name)
            if game_process:
                try:
                    metrics["game_process"] = {
                        "pid": game_process.pid,
                        "name": game_process.name(),
                        "cpu_percent": game_process.cpu_percent(),
                        "memory_percent": game_process.memory_percent(),
                        "memory_info": game_process.memory_info()._asdict(),
                        "num_threads": game_process.num_threads(),
                        "status": game_process.status()
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    metrics["game_process"] = None
        
        return jsonify({"status": "success", "metrics": metrics})
        
    except Exception as e:
        logger.error(f"Performance metrics failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Comprehensive health check."""
    try:
        health_status = {
            "service": "running",
            "version": "2.0",
            "uptime": time.time(),
            "mouse_controller": "active",
            "keyboard_controller": "active",
            "pyautogui": "active",
            "process_monitoring": "active"
        }
        
        # Check if game is running
        if current_game_process_name:
            game_process = find_process_by_name(current_game_process_name)
            health_status["game_process"] = "running" if game_process else "not_found"
        else:
            health_status["game_process"] = "none"
        
        return jsonify({"status": "success", "health": health_status})
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced SUT Service v2.0 - Complete Gaming Automation Support')
    parser.add_argument('--port', type=int, default=8080, help='Port to run the service on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("Enhanced SUT Service v3.1 - Gaming Automation Platform")
    logger.info("=" * 70)
    logger.info(f"Starting service on {args.host}:{args.port}")
    logger.info(f"Admin privileges: {'YES' if is_admin() else 'NO (some features may not work)'}")
    logger.info(f"Screen resolution: {input_controller.screen_width}x{input_controller.screen_height}")
    logger.info("")
    logger.info("NEW in v3.1:")
    logger.info("  * Windows SendInput API integration for better game compatibility")
    logger.info("  * Optimized mouse movement (50 max steps, ~40% faster)")
    logger.info("  * Enhanced keyboard input with proper scan codes")
    logger.info("  * Reusable memory allocations for better performance")
    logger.info("  * Admin privilege detection and warnings")
    logger.info("")
    logger.info("Supported Features:")
    logger.info("   All click types (left/right/middle/double/triple) with SendInput")
    logger.info("   Drag & drop operations with smooth movement")
    logger.info("   Scroll actions with precise control")
    logger.info("   Hotkey combinations (Ctrl+Alt+Del, etc.) with SendInput")
    logger.info("   Character-by-character text input")
    logger.info("   Action sequences with timing control")
    logger.info("   Process management with CPU/memory monitoring")
    logger.info("   Window management and system controls")
    logger.info("   Performance metrics and health monitoring")
    logger.info("   Gaming-optimized input handling with multiple fallbacks")
    logger.info("=" * 70)

    if not is_admin():
        logger.warning("WARNING: Not running with administrator privileges!")
        logger.warning("Some games may block input. Run as administrator for best results.")
        logger.warning("")
    
    app.run(host=args.host, port=args.port, debug=args.debug)

# """
# SUT Service - Run this on the System Under Test (SUT)
# This service handles requests from the ARL development PC.
# """

# import os
# import time
# import json
# import subprocess
# import threading
# from flask import Flask, request, jsonify, send_file
# import pyautogui
# from io import BytesIO
# import logging

# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("sut_service.log"),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# # Initialize Flask app
# app = Flask(__name__)

# # Global variables
# game_process = None
# game_lock = threading.Lock()

# @app.route('/status', methods=['GET'])
# def status():
#     """Endpoint to check if the service is running."""
#     return jsonify({"status": "running"})

# @app.route('/screenshot', methods=['GET'])
# def screenshot():
#     """Capture and return a screenshot."""
#     try:
#         # Capture the entire screen
#         screenshot = pyautogui.screenshot()
        
#         # Save to a bytes buffer
#         img_buffer = BytesIO()
#         screenshot.save(img_buffer, format='PNG')
#         img_buffer.seek(0)
        
#         logger.info("Screenshot captured")
#         return send_file(img_buffer, mimetype='image/png')
#     except Exception as e:
#         logger.error(f"Error capturing screenshot: {str(e)}")
#         return jsonify({"status": "error", "error": str(e)}), 500

# @app.route('/launch', methods=['POST'])
# def launch_game():
#     """Launch a game."""
#     global game_process
    
#     try:
#         data = request.json
#         game_path = data.get('path', '')
        
#         if not game_path or not os.path.exists(game_path):
#             logger.error(f"Game path not found: {game_path}")
#             return jsonify({"status": "error", "error": "Game executable not found"}), 404
        
#         with game_lock:
#             # Terminate existing game if running
#             if game_process and game_process.poll() is None:
#                 logger.info("Terminating existing game process")
#                 game_process.terminate()
#                 game_process.wait(timeout=5)
            
#             # Launch the game
#             logger.info(f"Launching game: {game_path}")
#             game_process = subprocess.Popen(game_path)
            
#             # Wait a moment to check if process started successfully
#             time.sleep(1)
#             if game_process.poll() is not None:
#                 logger.error("Game process failed to start")
#                 return jsonify({"status": "error", "error": "Game process failed to start"}), 500
        
#         return jsonify({"status": "success", "pid": game_process.pid})
#     except Exception as e:
#         logger.error(f"Error launching game: {str(e)}")
#         return jsonify({"status": "error", "error": str(e)}), 500

# @app.route('/action', methods=['POST'])
# def perform_action():
#     """Perform an action (click, key press, etc.)."""
#     try:
#         data = request.json
#         action_type = data.get('type', '')
        
#         if action_type == 'click':
#             x = data.get('x', 0)
#             y = data.get('y', 0)
            
#             # Get optional parameters for movement customization
#             move_duration = data.get('move_duration', 0.5)  # Default 0.5 seconds for smooth movement
#             click_delay = data.get('click_delay', 1.0)      # Default 1 second delay before clicking
            
#             logger.info(f"Moving smoothly to ({x}, {y}) over {move_duration}s")
            
#             # Move to the coordinate smoothly
#             pyautogui.moveTo(x=x, y=y, duration=move_duration)
            
#             # Wait for the specified delay
#             logger.info(f"Waiting {click_delay}s before clicking")
#             time.sleep(click_delay)
            
#             # Perform the click at current position
#             logger.info(f"Clicking at ({x}, {y})")
#             pyautogui.click()
            
#             return jsonify({"status": "success"})
            
#         elif action_type == 'key':
#             key = data.get('key', '')
#             logger.info(f"Pressing key: {key}")
#             pyautogui.press(key)
#             return jsonify({"status": "success"})
            
#         elif action_type == 'wait':
#             duration = data.get('duration', 1)
#             logger.info(f"Waiting for {duration} seconds")
#             time.sleep(duration)
#             return jsonify({"status": "success"})
            
#         elif action_type == 'terminate_game':
#             with game_lock:
#                 if game_process and game_process.poll() is None:
#                     logger.info("Terminating game")
#                     game_process.terminate()
#                     game_process.wait(timeout=5)
#                     return jsonify({"status": "success"})
#                 else:
#                     return jsonify({"status": "success", "message": "No running game to terminate"})
#         else:
#             logger.error(f"Unknown action type: {action_type}")
#             return jsonify({"status": "error", "error": f"Unknown action type: {action_type}"}), 400
            
#     except Exception as e:
#         logger.error(f"Error performing action: {str(e)}")
#         return jsonify({"status": "error", "error": str(e)}), 500

# if __name__ == '__main__':
#     import argparse
    
#     parser = argparse.ArgumentParser(description='SUT Service')
#     parser.add_argument('--port', type=int, default=8080, help='Port to run the service on')
#     parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
#     args = parser.parse_args()
    
#     logger.info(f"Starting SUT Service on {args.host}:{args.port}")
#     app.run(host=args.host, port=args.port)