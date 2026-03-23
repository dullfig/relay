"""
Timing model for relay circuits.

Default parameters based on the Panasonic AGN20012 (12V DPDT).
Datasheet: agn20009.pdf

AGN20012 key specs:
  - Footprint: 5.7mm x 10.6mm, height 9.0mm
  - Coil: 12V DC, 1028 ohm, 11.7mA, 140mW
  - Contact: 2 Form C (DPDT), 1A 30V DC
  - Operate time: 4ms max (excluding bounce)
  - Release time: 4ms max (excluding bounce)
  - Pickup: 75% of nominal voltage (9V)
  - Dropout: 10% of nominal voltage (1.2V)
  - Contact material: AgPd
  - Mechanical life: 50 million cycles
  - Weight: 1g

Times are in milliseconds.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RelaySpec:
    """Physical specifications for a relay part."""
    part_number: str = "AGN20012"
    coil_voltage: float = 12.0       # V DC
    coil_resistance: float = 1028.0  # ohm
    coil_current: float = 11.7       # mA
    coil_power: float = 140.0        # mW
    pickup_voltage: float = 9.0      # V (75% of nominal)
    dropout_voltage: float = 1.2     # V (10% of nominal)
    max_switching_voltage: float = 110.0   # V DC
    max_switching_current: float = 1.0     # A
    contact_resistance: float = 0.1  # ohm max initial
    footprint_w: float = 5.7         # mm
    footprint_h: float = 10.6        # mm
    height: float = 9.0              # mm
    weight: float = 1.0              # g
    poles: int = 2                    # DPDT = 2 Form C
    mechanical_life: int = 50_000_000  # cycles


# Default relay spec for the project
AGN20012 = RelaySpec()


@dataclass
class RelayTiming:
    """Timing parameters for a relay."""
    energize_delay: float = 4.0       # ms: coil current to contact closure
    deenergize_delay: float = 4.0     # ms: coil off to contact release
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


# Timing presets based on AGN datasheet
# AGN20012: 4ms operate, 4ms release
TIMING_AGN = RelayTiming(
    energize_delay=4.0, deenergize_delay=4.0,
    bounce_count=3, bounce_interval=0.5)

# Conservative (worst case + margin)
TIMING_AGN_WORST = RelayTiming(
    energize_delay=4.0, deenergize_delay=4.0,
    bounce_count=4, bounce_interval=0.8)

# Ideal (no bounce, for functional simulation)
TIMING_AGN_IDEAL = RelayTiming(
    energize_delay=4.0, deenergize_delay=4.0,
    bounce_count=0, bounce_interval=0.0)

# Legacy presets (for generic relays)
TIMING_FAST = RelayTiming(
    energize_delay=5.0, deenergize_delay=3.0,
    bounce_count=2, bounce_interval=0.3)

TIMING_STANDARD = RelayTiming(
    energize_delay=10.0, deenergize_delay=8.0,
    bounce_count=3, bounce_interval=0.5)

TIMING_SLOW = RelayTiming(
    energize_delay=20.0, deenergize_delay=15.0,
    bounce_count=4, bounce_interval=0.8)


@dataclass
class DRAMCellSpec:
    """Physical specs for a DRAM bit cell."""
    cap_value: float = 22.0          # uF
    cap_package: str = "1210"        # 3.2mm x 2.5mm
    cap_voltage_rating: float = 16.0 # V
    cap_dielectric: str = "ceramic"  # ceramic = hours of hold time
    diode_package: str = "0603"      # 1.6mm x 0.8mm
    diodes_per_cell: int = 2
    # Hold time above pickup (80% of 12V = 9.6V)
    hold_time_above_pickup: float = 7.0    # ms (with 22uF, 1440 ohm)
    hold_time_above_dropout: float = 73.0  # ms
    # Charge retention (ceramic cap, no load)
    retention_hours: float = 14.0    # hours above pickup with ceramic leakage
    # Cell footprint
    cell_width: float = 8.0          # mm (cap + diodes + spacing)
    cell_height: float = 3.2         # mm


# Default DRAM spec
DRAM_12V = DRAMCellSpec()


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
        # 1 tick = 1 AGN relay cycle = ~6ms (4ms operate + 2ms settle)
        return value * 6.0
    else:
        raise ValueError(f"Unknown time unit: {unit}")
