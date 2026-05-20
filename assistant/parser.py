import re
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

GRAMMAR_EXTRA_WORDS = {
    "close", "max", "min", "percent", "second", "seconds", "minute", "minutes",
    "yes", "no", "okay", "cancel", "visual", "studio", "word", "excel", "steam",
    "opera", "file", "folder", "show", "computer", "status", "capture", "screen",
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


def _contains_phrase(text: str, phrase: str) -> bool:
    """Match a phrase on word boundaries so 'start' does not match 'restart'."""
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _exact_match_intent(text: str) -> str | None:
    """Prefer explicit phrase matches before fuzzy matching."""
    phrases: list[tuple[str, str]] = []
    for intent, intent_phrases in INTENTS.items():
        for phrase in intent_phrases:
            phrases.append((intent, phrase))

    for intent, phrase in sorted(phrases, key=lambda item: len(item[1]), reverse=True):
        if _contains_phrase(text, phrase):
            return intent
    return None


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


def match_intent(text: str) -> str | None:
    """Match command intent with exact phrase priority, then fuzzy fallback."""
    return _exact_match_intent(text) or _fuzzy_match_intent(text)


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


def build_grammar_vocab() -> list[str]:
    """Build Vosk grammar from parser-owned commands so STT and parsing stay synced."""
    vocab: set[str] = {"[unk]"}

    for phrases in INTENTS.values():
        for phrase in phrases:
            vocab.add(phrase)
            vocab.update(phrase.split())

    for app_name in APP_MAP:
        vocab.add(app_name)
        vocab.update(app_name.split())

    vocab.update(WORD_NUMBERS.keys())
    vocab.update(GRAMMAR_EXTRA_WORDS)

    return sorted(vocab)


def parse(text: str) -> ParsedCommand:
    text = text.lower().strip()
    intent = match_intent(text)

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
