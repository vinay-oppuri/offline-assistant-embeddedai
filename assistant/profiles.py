import os
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class DeploymentProfile:
    name: str
    model_path: str
    listen_timeout_seconds: float
    action_backend: str
    command_forwarding: bool = False


MODEL_PATH = "models/vosk-model-small-en-us-0.15"

PROFILES: dict[str, DeploymentProfile] = {
    "desktop": DeploymentProfile(
        name="desktop",
        model_path=MODEL_PATH,
        listen_timeout_seconds=3.0,
        action_backend="auto",
    ),
    "raspberry-pi": DeploymentProfile(
        name="raspberry-pi",
        model_path=MODEL_PATH,
        listen_timeout_seconds=2.5,
        action_backend="linux",
    ),
    "microcontroller": DeploymentProfile(
        name="microcontroller",
        model_path=MODEL_PATH,
        listen_timeout_seconds=2.0,
        action_backend="forward",
        command_forwarding=True,
    ),
}


def current_profile() -> DeploymentProfile:
    profile_name = os.getenv("JARVIS_PROFILE", "desktop").strip().lower()
    return PROFILES.get(profile_name, PROFILES["desktop"])


def resolve_action_backend(profile: DeploymentProfile | None = None) -> str:
    profile = profile or current_profile()
    if profile.action_backend != "auto":
        return profile.action_backend
    return "windows" if platform.system().lower() == "windows" else "linux"
