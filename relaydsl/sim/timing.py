"""
Timing model for relay circuits.

Models relay energize/de-energize delays and contact bounce.
Times are in milliseconds.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RelayTiming:
    """Timing parameters for a relay."""
    energize_delay: float = 10.0      # ms: coil current to contact closure
    deenergize_delay: float = 8.0     # ms: coil off to contact release
    bounce_count: int = 3             # number of bounces after transition
    bounce_interval: float = 0.5      # ms: initial interval between bounces

    def bounce_schedule(self, start_time: float) -> list[float]:
        """
        Return times at which the contact toggles during bounce.

        Bounces decrease in interval (damped oscillation).
        Each time in the list is a toggle: closed->open->closed->...
        """
        times = []
        t = start_time
        for i in range(self.bounce_count):
            # Exponentially decreasing bounce intervals
            interval = self.bounce_interval * (0.6 ** i)
            t += interval
            times.append(t)
        return times

    def settle_time(self, energizing: bool) -> float:
        """Total time from coil transition to fully settled contacts."""
        base = self.energize_delay if energizing else self.deenergize_delay
        if self.bounce_count > 0:
            # Add bounce duration
            total_bounce = sum(
                self.bounce_interval * (0.6 ** i)
                for i in range(self.bounce_count)
            )
            return base + total_bounce
        return base


# Default timing for common relay types
TIMING_FAST = RelayTiming(
    energize_delay=5.0, deenergize_delay=3.0,
    bounce_count=2, bounce_interval=0.3)

TIMING_STANDARD = RelayTiming(
    energize_delay=10.0, deenergize_delay=8.0,
    bounce_count=3, bounce_interval=0.5)

TIMING_SLOW = RelayTiming(
    energize_delay=20.0, deenergize_delay=15.0,
    bounce_count=4, bounce_interval=0.8)


def ms_to_ticks(ms: float, tick_period: float = 1.0) -> float:
    """Convert milliseconds to simulation ticks."""
    return ms / tick_period


def convert_time(value: float, unit: str) -> float:
    """Convert a time value to milliseconds."""
    if unit == "ms":
        return value
    elif unit == "us":
        return value / 1000.0
    elif unit == "ns":
        return value / 1_000_000.0
    elif unit == "ticks":
        # 1 tick = 1 relay switching time = 10ms default
        return value * 10.0
    else:
        raise ValueError(f"Unknown time unit: {unit}")
