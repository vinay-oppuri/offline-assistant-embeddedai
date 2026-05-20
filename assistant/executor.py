from assistant.executor_common import BaseExecutor, ForwardingExecutor
from assistant.parser import ParsedCommand
from assistant.profiles import current_profile, resolve_action_backend

_EXECUTOR: BaseExecutor | None = None


def get_executor() -> BaseExecutor:
    global _EXECUTOR
    if _EXECUTOR is not None:
        return _EXECUTOR

    profile = current_profile()
    backend = resolve_action_backend(profile)

    if backend == "forward" or profile.command_forwarding:
        _EXECUTOR = ForwardingExecutor()
    elif backend == "windows":
        from assistant.executor_windows import WindowsExecutor

        _EXECUTOR = WindowsExecutor()
    elif backend == "linux":
        from assistant.executor_linux import LinuxExecutor

        _EXECUTOR = LinuxExecutor()
    else:
        _EXECUTOR = BaseExecutor()

    print(f"[executor] profile={profile.name} backend={backend}")
    return _EXECUTOR


def execute(cmd: ParsedCommand) -> str:
    return get_executor().execute(cmd)
