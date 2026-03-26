from dataclasses import dataclass
from rapidfuzz import process, fuzz

# All known app executable names (what to pass to subprocess)
APP_MAP: dict[str, str] = {
    "brave":         "brave.exe",
    "chrome":        "chrome.exe",
    "firefox":       "firefox.exe",
    "edge":          "msedge.exe",
    "notepad":       "notepad.exe",
    "calculator":    "calc.exe",
    "terminal":      "wt.exe",        # Windows Terminal
    "explorer":      "explorer.exe",
    "spotify":       "spotify.exe",
    "discord":       "discord.exe",
    "slack":         "slack.exe",
    "code":          "code.exe",      # VS Code
    "vlc":           "vlc.exe",
    "obs":           "obs64.exe",
    "zoom":          "zoom.exe",
    "teams":         "teams.exe",
    "whatsapp":      "whatsapp.exe"
}

# Intent keywords
INTENTS = {
    "volume_up":        ["volume up", "increase volume", "louder", "turn up"],
    "volume_down":      ["volume down", "decrease volume", "quieter", "turn down"],
    "mute":             ["mute", "silence", "quiet"],
    "unmute":           ["unmute"],
    "brightness_up":    ["brightness up", "increase brightness", "brighter"],
    "brightness_down":  ["brightness down", "decrease brightness", "dimmer"],
    "open_app":         ["open", "launch", "start"],
    "open_file":        ["open file", "open folder", "show file"],
    "screenshot":       ["screenshot", "capture screen", "take screenshot"],
    "lock":             ["lock", "lock screen", "lock computer"],
    "system_info":      ["system info", "system status", "cpu", "ram", "memory", "disk"],
    "search":           ["search", "google", "look up", "find"],
    "timer":            ["timer", "set timer", "remind me in"],
    "shutdown":         ["shutdown", "turn off", "power off"],
    "restart":          ["restart", "reboot"],
}

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60,
}


@dataclass
class ParsedCommand:
    intent: str
    app: str | None = None
    query: str | None = None
    duration_seconds: int | None = None
    raw: str = ""


def _fuzzy_match_app(word: str) -> str | None:
    """Return the best matching app key, or None if confidence too low."""
    result = process.extractOne(
        word,
        APP_MAP.keys(),
        scorer=fuzz.WRatio,
        score_cutoff=72,   # tune: lower = more permissive, higher = stricter
    )
    return result[0] if result else None


def _fuzzy_match_intent(text: str) -> str | None:
    """Match text against all intent trigger phrases."""
    best_intent, best_score = None, 0
    for intent, phrases in INTENTS.items():
        for phrase in phrases:
            score = fuzz.partial_ratio(phrase, text)
            if score > best_score:
                best_score = score
                best_intent = intent
    return best_intent if best_score >= 65 else None


def _extract_timer_seconds(text: str) -> int | None:
    tokens = text.split()
    for i, tok in enumerate(tokens):
        num = WORD_NUMBERS.get(tok) or (int(tok) if tok.isdigit() else None)
        if num is None:
            continue
        unit = tokens[i + 1] if i + 1 < len(tokens) else ""
        if "minute" in unit:
            return num * 60
        return num  # assume seconds
    return None


def parse(text: str) -> ParsedCommand:
    text = text.lower().strip()
    intent = _fuzzy_match_intent(text)

    if intent == "open_app":
        # Look for app name in the tokens that follow the trigger word
        tokens = text.split()
        trigger_idx = next(
            (i for i, t in enumerate(tokens) if t in ("open", "launch", "start")), 0
        )
        candidate_tokens = tokens[trigger_idx + 1:]
        app = None
        for tok in candidate_tokens:
            app = _fuzzy_match_app(tok)
            if app:
                break
        return ParsedCommand(intent="open_app", app=app, raw=text)

    if intent == "search":
        # Everything after "search" / "google" is the query
        for kw in ("search", "google", "look up", "find"):
            if kw in text:
                query = text.split(kw, 1)[-1].strip()
                return ParsedCommand(intent="search", query=query, raw=text)

    if intent == "timer":
        secs = _extract_timer_seconds(text)
        return ParsedCommand(intent="timer", duration_seconds=secs, raw=text)

    return ParsedCommand(intent=intent or "unknown", raw=text)