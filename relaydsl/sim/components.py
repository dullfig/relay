from __future__ import annotations
from dataclasses import dataclass, field
from .nets import Net, WireState


@dataclass
class Contact:
    """One changeover contact of a DPDT relay."""
    common: str   # net name
    no: str       # normally open net name
    nc: str       # normally closed net name


@dataclass
class RelayModel:
    """
    DPDT relay with coil and two changeover contacts.

    When de-energized: common connects to NC (normally closed)
    When energized: common connects to NO (normally open)
    """
    name: str
    coil_net: str           # net name driving the coil
    contacts: list[Contact] = field(default_factory=list)  # typically 2 for DPDT
    energized: bool = False

    # Timing parameters (ms) - defaults from AGN20012 datasheet
    energize_delay: float = 4.0
    deenergize_delay: float = 4.0
    bounce_duration: float = 1.5

    def closed_contacts(self) -> list[tuple[str, str]]:
        """Return list of (net_a, net_b) pairs for currently closed contacts."""
        result = []
        for contact in self.contacts:
            if self.energized:
                result.append((contact.common, contact.no))
            else:
                result.append((contact.common, contact.nc))
        return result

    def __repr__(self) -> str:
        state = "ON" if self.energized else "OFF"
        return f"Relay({self.name}, {state})"


@dataclass
class DiodeModel:
    """
    Diode: conducts from anode to cathode only.

    If anode is HIGH, cathode sees HIGH (through diode).
    Anode never sees cathode's state (unidirectional).
    """
    name: str
    anode_net: str
    cathode_net: str
    forward_drop: float = 0.6  # volts, for tracking chain depth

    def __repr__(self) -> str:
        return f"Diode({self.name}, {self.anode_net} ->| {self.cathode_net})"


@dataclass
class CapacitorModel:
    """
    Capacitor for DRAM-like storage.

    Stores charge when written (driven HIGH or LOW).
    Charge decays to FLOAT after decay_time ms.
    """
    name: str
    terminal: str          # net name (other terminal assumed ground)
    charge: WireState = WireState.FLOAT
    decay_time: float = 100.0    # ms
    last_write_time: float = 0.0

    def read(self, current_time: float) -> WireState:
        """Read the capacitor's current state, accounting for decay."""
        if self.charge == WireState.FLOAT:
            return WireState.FLOAT
        elapsed = current_time - self.last_write_time
        if elapsed >= self.decay_time:
            self.charge = WireState.FLOAT
            return WireState.FLOAT
        return self.charge

    def write(self, state: WireState, current_time: float):
        """Write a state to the capacitor (refresh)."""
        self.charge = state
        self.last_write_time = current_time

    def __repr__(self) -> str:
        return f"Cap({self.name}, charge={self.charge})"


@dataclass
class FuseModel:
    """
    Programmable fuse: a connection that can be blown (opened).

    When intact: bidirectional wire between terminal_a and terminal_b.
    When blown: open circuit.
    """
    name: str
    terminal_a: str   # net name
    terminal_b: str   # net name
    intact: bool = True

    def closed_contact(self) -> tuple[str, str] | None:
        """Return the connection if intact, None if blown."""
        if self.intact:
            return (self.terminal_a, self.terminal_b)
        return None

    def blow(self):
        """Program this fuse (destroy the connection)."""
        self.intact = False

    def __repr__(self) -> str:
        state = "INTACT" if self.intact else "BLOWN"
        return f"Fuse({self.name}, {state})"
