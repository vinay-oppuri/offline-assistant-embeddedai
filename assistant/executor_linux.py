import subprocess
import time
from pathlib import Path

from assistant.executor_common import BRIGHTNESS_STEP, VOLUME_STEP, BaseExecutor, shell_available
from assistant.parser import APP_MAP

LINUX_APP_MAP: dict[str, str] = {
    **APP_MAP,
    "brave": "brave-browser",
    "chrome": "google-chrome",
    "edge": "microsoft-edge",
    "terminal": "x-terminal-emulator",
    "explorer": "xdg-open",
    "code": "code",
}


class LinuxExecutor(BaseExecutor):
    def _run(self, command: list[str]) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                return True, completed.stdout.strip()
            return False, completed.stderr.strip() or completed.stdout.strip()
        except Exception as e:
            return False, str(e)

    def speak(self, msg: str) -> None:
        if shell_available("espeak"):
            subprocess.run(["espeak", msg], check=False)
        else:
            print(msg)

    def volume_up(self) -> str:
        step = str(int(VOLUME_STEP * 100))
        if shell_available("pactl"):
            ok, err = self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{step}%"])
            return "Volume up." if ok else f"Volume error: {err}"
        if shell_available("amixer"):
            ok, err = self._run(["amixer", "set", "Master", f"{step}%+"])
            return "Volume up." if ok else f"Volume error: {err}"
        return "Volume control requires pactl or amixer."

    def volume_down(self) -> str:
        step = str(int(VOLUME_STEP * 100))
        if shell_available("pactl"):
            ok, err = self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{step}%"])
            return "Volume down." if ok else f"Volume error: {err}"
        if shell_available("amixer"):
            ok, err = self._run(["amixer", "set", "Master", f"{step}%-"])
            return "Volume down." if ok else f"Volume error: {err}"
        return "Volume control requires pactl or amixer."

    def mute_toggle(self) -> str:
        if shell_available("pactl"):
            ok, err = self._run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            return "Toggled mute." if ok else f"Mute error: {err}"
        if shell_available("amixer"):
            ok, err = self._run(["amixer", "set", "Master", "toggle"])
            return "Toggled mute." if ok else f"Mute error: {err}"
        return "Mute control requires pactl or amixer."

    def brightness_up(self) -> str:
        if shell_available("brightnessctl"):
            ok, err = self._run(["brightnessctl", "set", f"+{BRIGHTNESS_STEP}%"])
            return "Brightness up." if ok else f"Brightness error: {err}"
        return "Brightness control requires brightnessctl."

    def brightness_down(self) -> str:
        if shell_available("brightnessctl"):
            ok, err = self._run(["brightnessctl", "set", f"{BRIGHTNESS_STEP}%-"])
            return "Brightness down." if ok else f"Brightness error: {err}"
        return "Brightness control requires brightnessctl."

    def open_app(self, app_key: str | None) -> str:
        if not app_key or app_key not in LINUX_APP_MAP:
            return f"App not recognised: {app_key!r}"
        exe = LINUX_APP_MAP[app_key].removesuffix(".exe")
        try:
            subprocess.Popen([exe])
            return f"Opening {app_key}."
        except Exception as e:
            return f"Could not open {app_key}: {e}"

    def open_file(self, path: str | None = None) -> str:
        target = path if path and Path(path).exists() else str(Path.home())
        if shell_available("xdg-open"):
            subprocess.Popen(["xdg-open", target])
            return f"Opening {target}."
        return "File opening requires xdg-open."

    def take_screenshot(self) -> str:
        shots_dir = Path.home() / "Pictures" / "Jarvis Screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        fname = shots_dir / f"screenshot_{int(time.time())}.png"
        if shell_available("gnome-screenshot"):
            ok, err = self._run(["gnome-screenshot", "-f", str(fname)])
            return f"Screenshot saved to {fname}" if ok else f"Screenshot error: {err}"
        if shell_available("scrot"):
            ok, err = self._run(["scrot", str(fname)])
            return f"Screenshot saved to {fname}" if ok else f"Screenshot error: {err}"
        return "Screenshots require gnome-screenshot or scrot."

    def lock_screen(self) -> str:
        for command in (
            ["loginctl", "lock-session"],
            ["xdg-screensaver", "lock"],
            ["gnome-screensaver-command", "-l"],
        ):
            if shell_available(command[0]):
                ok, err = self._run(command)
                return "Locking screen." if ok else f"Lock error: {err}"
        return "Screen locking requires loginctl, xdg-screensaver, or gnome-screensaver-command."

    def shutdown_pc(self) -> str:
        ok, err = self._run(["systemctl", "poweroff"])
        return "Shutting down." if ok else f"Shutdown error: {err}"

    def restart_pc(self) -> str:
        ok, err = self._run(["systemctl", "reboot"])
        return "Restarting." if ok else f"Restart error: {err}"
