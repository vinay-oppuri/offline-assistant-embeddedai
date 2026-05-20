import os
import threading
import time
import webbrowser
from pathlib import Path

import psutil

from assistant.parser import ParsedCommand

VOLUME_STEP = 0.08
BRIGHTNESS_STEP = 10


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


class BaseExecutor:
    def speak(self, msg: str) -> None:
        print(msg)

    def speak_async(self, msg: str) -> None:
        threading.Thread(target=self.speak, args=(msg,), daemon=True).start()

    def volume_up(self) -> str:
        return "Volume control is not available on this backend."

    def volume_down(self) -> str:
        return "Volume control is not available on this backend."

    def mute_toggle(self) -> str:
        return "Mute control is not available on this backend."

    def brightness_up(self) -> str:
        return "Brightness control is not available on this backend."

    def brightness_down(self) -> str:
        return "Brightness control is not available on this backend."

    def open_app(self, app_key: str | None) -> str:
        return f"App launching is not available on this backend: {app_key!r}"

    def open_file(self, path: str | None = None) -> str:
        if path and Path(path).exists():
            return f"File exists but this backend cannot open it: {path}"
        return "File opening is not available on this backend."

    def take_screenshot(self) -> str:
        return "Screenshots are not available on this backend."

    def lock_screen(self) -> str:
        return "Screen locking is not available on this backend."

    def shutdown_pc(self) -> str:
        return "Shutdown is not available on this backend."

    def restart_pc(self) -> str:
        return "Restart is not available on this backend."

    def system_info(self) -> str:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return (
            f"CPU: {cpu}% | "
            f"RAM: {ram.percent}% used ({ram.used // 1024**3}GB / {ram.total // 1024**3}GB) | "
            f"Disk: {disk.percent}% used ({disk.free // 1024**3}GB free)"
        )

    def web_search(self, query: str | None) -> str:
        if not query:
            return "No search query provided."
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Searching for: {query}"

    def set_timer(self, seconds: int | None) -> str:
        if not seconds:
            return "Could not parse timer duration."
        label = f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"

        def _ring():
            time.sleep(seconds)
            self.speak(f"Timer done - {label} elapsed.")

        threading.Thread(target=_ring, daemon=True).start()
        return f"Timer set for {label}."

    def execute(self, cmd: ParsedCommand) -> str:
        match cmd.intent:
            case "volume_up":
                result = self.volume_up()
            case "volume_down":
                result = self.volume_down()
            case "mute" | "unmute":
                result = self.mute_toggle()
            case "brightness_up":
                result = self.brightness_up()
            case "brightness_down":
                result = self.brightness_down()
            case "open_app":
                result = self.open_app(cmd.app)
            case "open_file":
                result = self.open_file(cmd.query)
            case "screenshot":
                result = self.take_screenshot()
            case "lock":
                result = self.lock_screen()
            case "system_info":
                result = self.system_info()
            case "search":
                result = self.web_search(cmd.query)
            case "timer":
                result = self.set_timer(cmd.duration_seconds)
            case "shutdown":
                result = self.shutdown_pc()
            case "restart":
                result = self.restart_pc()
            case _:
                result = f"Sorry, I didn't catch that - heard: {cmd.raw!r}"

        print(f"[Jarvis] {result}")
        self.speak_async(result)
        return result


class ForwardingExecutor(BaseExecutor):
    def execute(self, cmd: ParsedCommand) -> str:
        result = (
            "Forward-only profile: "
            f"intent={cmd.intent!r}, app={cmd.app!r}, query={cmd.query!r}, "
            f"duration_seconds={cmd.duration_seconds!r}"
        )
        print(f"[Jarvis] {result}")
        return result


def shell_available(command: str) -> bool:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    extensions = [""] if os.name != "nt" else os.environ.get("PATHEXT", "").split(os.pathsep)
    for path in paths:
        for ext in extensions:
            candidate = Path(path) / f"{command}{ext}"
            if candidate.exists():
                return True
    return False
