import os
import subprocess
import threading
import time
import webbrowser
import ctypes
from pathlib import Path

import psutil
from PIL import ImageGrab          # pip install pillow
import screen_brightness_control as sbc  # pip install screen-brightness-control

from assistant.parser import ParsedCommand, APP_MAP

# Volume control via Windows COM (pycaw)
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    _devices = AudioUtilities.GetSpeakers()
    _interface = _devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    _volume_ctrl = _interface.QueryInterface(IAudioEndpointVolume)
    VOLUME_AVAILABLE = True
except Exception:
    VOLUME_AVAILABLE = False
    print("[executor] pycaw not available — volume control disabled")

VOLUME_STEP = 0.08      # 8% per command
BRIGHTNESS_STEP = 10    # 10% per command


# ── helpers ────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))

def _say(msg: str):
    """Simple TTS via Windows SAPI — replace with your TTS module if you have one."""
    # Escape single quotes for PowerShell (replace ' with '')
    safe_msg = msg.replace("'", "''")
    os.system(f'PowerShell -Command "Add-Type –AssemblyName System.Speech; '
              f'(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'{safe_msg}\')"')

def _speak_async(msg: str):
    threading.Thread(target=_say, args=(msg,), daemon=True).start()


# ── 10 command handlers ─────────────────────────────────────────────────────

def volume_up() -> str:
    if not VOLUME_AVAILABLE:
        return "Volume control not available."
    cur = _volume_ctrl.GetMasterVolumeLevelScalar()
    _volume_ctrl.SetMasterVolumeLevelScalar(_clamp(cur + VOLUME_STEP, 0.0, 1.0), None)
    return f"Volume up — {int(_clamp(cur + VOLUME_STEP, 0.0, 1.0) * 100)}%"

def volume_down() -> str:
    if not VOLUME_AVAILABLE:
        return "Volume control not available."
    cur = _volume_ctrl.GetMasterVolumeLevelScalar()
    _volume_ctrl.SetMasterVolumeLevelScalar(_clamp(cur - VOLUME_STEP, 0.0, 1.0), None)
    return f"Volume down — {int(_clamp(cur - VOLUME_STEP, 0.0, 1.0) * 100)}%"

def mute_toggle() -> str:
    if not VOLUME_AVAILABLE:
        return "Volume control not available."
    is_muted = _volume_ctrl.GetMute()
    _volume_ctrl.SetMute(not is_muted, None)
    return "Unmuted." if is_muted else "Muted."

def brightness_up() -> str:
    try:
        cur = sbc.get_brightness(display=0)[0]
        new = _clamp(cur + BRIGHTNESS_STEP, 0, 100)
        sbc.set_brightness(new, display=0)
        return f"Brightness up — {new}%"
    except Exception as e:
        return f"Brightness error: {e}"

def brightness_down() -> str:
    try:
        cur = sbc.get_brightness(display=0)[0]
        new = _clamp(cur - BRIGHTNESS_STEP, 0, 100)
        sbc.set_brightness(new, display=0)
        return f"Brightness down — {new}%"
    except Exception as e:
        return f"Brightness error: {e}"

def open_app(app_key: str | None) -> str:
    if not app_key or app_key not in APP_MAP:
        return f"App not recognised: {app_key!r}"
    exe = APP_MAP[app_key]
    try:
        subprocess.Popen(exe, shell=True)
        return f"Opening {app_key}."
    except Exception as e:
        return f"Could not open {app_key}: {e}"

def open_file(path: str | None = None) -> str:
    """Opens a file in its default app, or opens Explorer if no path given."""
    if path and Path(path).exists():
        os.startfile(path)
        return f"Opening {path}"
    else:
        subprocess.Popen("explorer.exe")
        return "Opening file explorer."

def take_screenshot() -> str:
    shots_dir = Path.home() / "Pictures" / "Jarvis Screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    fname = shots_dir / f"screenshot_{int(time.time())}.png"
    img = ImageGrab.grab()
    img.save(fname)
    return f"Screenshot saved to {fname}"

def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Locking screen."

def system_info() -> str:
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return (
        f"CPU: {cpu}% | "
        f"RAM: {ram.percent}% used ({ram.used // 1024**3}GB / {ram.total // 1024**3}GB) | "
        f"Disk: {disk.percent}% used ({disk.free // 1024**3}GB free)"
    )

def web_search(query: str | None) -> str:
    if not query:
        return "No search query provided."
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(url)
    return f"Searching for: {query}"

def set_timer(seconds: int | None) -> str:
    if not seconds:
        return "Could not parse timer duration."
    label = f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"
    def _ring():
        time.sleep(seconds)
        _say(f"Timer done — {label} elapsed.")
    threading.Thread(target=_ring, daemon=True).start()
    return f"Timer set for {label}."

def shutdown_pc() -> str:
    os.system("shutdown /s /t 5")
    return "Shutting down in 5 seconds."

def restart_pc() -> str:
    os.system("shutdown /r /t 5")
    return "Restarting in 5 seconds."


# ── main dispatch ───────────────────────────────────────────────────────────

def execute(cmd: ParsedCommand) -> str:
    result = ""
    match cmd.intent:
        case "volume_up":       result = volume_up()
        case "volume_down":     result = volume_down()
        case "mute" | "unmute": result = mute_toggle()
        case "brightness_up":   result = brightness_up()
        case "brightness_down": result = brightness_down()
        case "open_app":        result = open_app(cmd.app)
        case "open_file":       result = open_file(cmd.query)
        case "screenshot":      result = take_screenshot()
        case "lock":            result = lock_screen()
        case "system_info":     result = system_info()
        case "search":          result = web_search(cmd.query)
        case "timer":           result = set_timer(cmd.duration_seconds)
        case "shutdown":        result = shutdown_pc()
        case "restart":         result = restart_pc()
        case _:                 result = f"Sorry, I didn't catch that — heard: {cmd.raw!r}"

    print(f"[Jarvis] {result}")
    _speak_async(result)
    return result