import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PassiveBrowsingScenario:
    dwell_seconds: float

    def wait_remaining(self, started: float, sleep: Callable[[float], None]) -> dict[str, float]:
        """Include read+write time in the target dwell, not only the sleep."""
        elapsed = time.monotonic() - started
        remaining = max(0.0, self.dwell_seconds - elapsed)
        sleep(remaining)
        return {"target_seconds": self.dwell_seconds, "requested_wait_seconds": remaining,
                "measured_seconds": time.monotonic() - started,
                "overrun_seconds": max(0.0, elapsed - self.dwell_seconds)}
