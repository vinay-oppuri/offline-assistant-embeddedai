import ctypes
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import ImageGrab
import screen_brightness_control as sbc

from assistant.executor_common import (
    BRIGHTNESS_STEP,
    VOLUME_STEP,
    BaseExecutor,
    clamp,
)
from assistant.parser import APP_MAP


try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL

    _devices = AudioUtilities.GetSpeakers()
    if hasattr(_devices, "EndpointVolume"):
        _volume_ctrl = _devices.EndpointVolume
    else:
        _interface = _devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        _volume_ctrl = _interface.QueryInterface(IAudioEndpointVolume)
    VOLUME_AVAILABLE = True
    VOLUME_ERROR = ""
except Exception as e:
    VOLUME_AVAILABLE = False
    _volume_ctrl = None
    VOLUME_ERROR = str(e)
    print(f"[executor] pycaw not available - volume control disabled: {e}")


WINDOWS_APP_PATHS: dict[str, list[str]] = {
    "brave": [
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "firefox": [
        r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
        r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    "code": [
        r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
    ],
    "spotify": [
        r"%AppData%\Spotify\Spotify.exe",
    ],
    "discord": [
        r"%LocalAppData%\Discord\Update.exe",
    ],
    "slack": [
        r"%LocalAppData%\slack\slack.exe",
    ],
    "vlc": [
        r"%ProgramFiles%\VideoLAN\VLC\vlc.exe",
        r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe",
    ],
    "obs": [
        r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe",
    ],
    "zoom": [
        r"%AppData%\Zoom\bin\Zoom.exe",
    ],
    "teams": [
        r"%LocalAppData%\Microsoft\Teams\current\Teams.exe",
    ],
    "whatsapp": [
        r"%LocalAppData%\WhatsApp\WhatsApp.exe",
        r"%LocalAppData%\Microsoft\WindowsApps\WhatsApp.exe",
    ],
}

WINDOWS_STORE_APPS: dict[str, str] = {
    "whatsapp": r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
}


def _expand_existing_path(path: str) -> str | None:
    expanded = os.path.expandvars(path)
    return expanded if Path(expanded).exists() else None


def _resolve_app_command(app_key: str) -> list[str] | None:
    exe = APP_MAP.get(app_key)
    if exe:
        resolved = shutil.which(exe)
        if resolved:
            return [resolved]

    for candidate in WINDOWS_APP_PATHS.get(app_key, []):
        resolved = _expand_existing_path(candidate)
        if resolved:
            return [resolved]

    store_app = WINDOWS_STORE_APPS.get(app_key)
    if store_app:
        return ["explorer.exe", store_app]

    return None


class WindowsExecutor(BaseExecutor):
    def speak(self, msg: str) -> None:
        safe_msg = msg.replace("'", "''")
        os.system(
            "PowerShell -Command \"Add-Type -AssemblyName System.Speech; "
            f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe_msg}')\""
        )

    def volume_up(self) -> str:
        if not VOLUME_AVAILABLE or _volume_ctrl is None:
            return f"Volume control not available: {VOLUME_ERROR or 'unknown error'}"
        cur = _volume_ctrl.GetMasterVolumeLevelScalar()
        new = clamp(cur + VOLUME_STEP, 0.0, 1.0)
        _volume_ctrl.SetMasterVolumeLevelScalar(new, None)
        return f"Volume up - {int(new * 100)}%"

    def volume_down(self) -> str:
        if not VOLUME_AVAILABLE or _volume_ctrl is None:
            return f"Volume control not available: {VOLUME_ERROR or 'unknown error'}"
        cur = _volume_ctrl.GetMasterVolumeLevelScalar()
        new = clamp(cur - VOLUME_STEP, 0.0, 1.0)
        _volume_ctrl.SetMasterVolumeLevelScalar(new, None)
        return f"Volume down - {int(new * 100)}%"

    def mute_toggle(self) -> str:
        if not VOLUME_AVAILABLE or _volume_ctrl is None:
            return f"Volume control not available: {VOLUME_ERROR or 'unknown error'}"
        is_muted = _volume_ctrl.GetMute()
        _volume_ctrl.SetMute(not is_muted, None)
        return "Unmuted." if is_muted else "Muted."

    def brightness_up(self) -> str:
        try:
            cur = sbc.get_brightness(display=0)[0]
            new = clamp(cur + BRIGHTNESS_STEP, 0, 100)
            sbc.set_brightness(new, display=0)
            return f"Brightness up - {new}%"
        except Exception as e:
            return f"Brightness error: {e}"

    def brightness_down(self) -> str:
        try:
            cur = sbc.get_brightness(display=0)[0]
            new = clamp(cur - BRIGHTNESS_STEP, 0, 100)
            sbc.set_brightness(new, display=0)
            return f"Brightness down - {new}%"
        except Exception as e:
            return f"Brightness error: {e}"

    def open_app(self, app_key: str | None) -> str:
        if not app_key or app_key not in APP_MAP:
            return f"App not recognised: {app_key!r}"
        command = _resolve_app_command(app_key)
        if not command:
            return (
                f"Could not find {app_key}. Install it, add it to PATH, "
                "or add its full path in WINDOWS_APP_PATHS."
            )
        try:
            subprocess.Popen(command)
            return f"Opening {app_key}."
        except Exception as e:
            return f"Could not open {app_key}: {e}"

    def open_file(self, path: str | None = None) -> str:
        if path and Path(path).exists():
            os.startfile(path)
            return f"Opening {path}"
        subprocess.Popen("explorer.exe")
        return "Opening file explorer."

    def take_screenshot(self) -> str:
        shots_dir = Path.home() / "Pictures" / "Jarvis Screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        fname = shots_dir / f"screenshot_{int(time.time())}.png"
        img = ImageGrab.grab()
        img.save(fname)
        return f"Screenshot saved to {fname}"

    def lock_screen(self) -> str:
        ctypes.windll.user32.LockWorkStation()
        return "Locking screen."

    def shutdown_pc(self) -> str:
        os.system("shutdown /s /t 5")
        return "Shutting down in 5 seconds."

    def restart_pc(self) -> str:
        os.system("shutdown /r /t 5")
        return "Restarting in 5 seconds."
