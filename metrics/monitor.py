import psutil
import time
import os
from dataclasses import dataclass, field


class MetricsMonitor:

    def __init__(self):

        self.process = psutil.Process(os.getpid())

    def start_timer(self):

        self.start_time = time.time()

    def stop_timer(self):

        latency = time.time() - self.start_time
        return latency

    def memory_usage(self):

        return self.process.memory_info().rss / (1024 * 1024)

    def cpu_usage(self):

        return psutil.cpu_percent(interval=0.1)


@dataclass
class BenchmarkReport:
    timings: dict[str, float] = field(default_factory=dict)
    memory_mb: dict[str, float] = field(default_factory=dict)
    cpu_percent: dict[str, float] = field(default_factory=dict)

    def add_timing(self, name: str, seconds: float) -> None:
        self.timings[name] = seconds

    def add_sample(self, name: str, monitor: MetricsMonitor) -> None:
        self.memory_mb[name] = monitor.memory_usage()
        self.cpu_percent[name] = monitor.cpu_usage()

    def format(self) -> str:
        parts: list[str] = []
        for name, value in self.timings.items():
            parts.append(f"{name}={value:.3f}s")
        for name, value in self.memory_mb.items():
            parts.append(f"{name}_mem={value:.1f}MB")
        for name, value in self.cpu_percent.items():
            parts.append(f"{name}_cpu={value:.1f}%")
        return " | ".join(parts)
