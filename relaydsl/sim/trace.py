"""
Trace recording and output for relay circuit simulation.

Supports:
- Text-based trace dump (human-readable)
- VCD (Value Change Dump) output for waveform viewers
- Filtered trace (show only specific nets)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from io import StringIO
from .nets import WireState


@dataclass
class TraceEvent:
    time: float
    net_name: str
    old_state: WireState
    new_state: WireState


class TraceRecorder:
    """Records net state changes during simulation."""

    def __init__(self, filter_nets: set[str] | None = None):
        self.events: list[TraceEvent] = []
        self.filter_nets = filter_nets  # None = record everything
        self.initial_states: dict[str, WireState] = {}

    def record_initial(self, net_name: str, state: WireState):
        self.initial_states[net_name] = state

    def record(self, time: float, net_name: str,
               old_state: WireState, new_state: WireState):
        if self.filter_nets and net_name not in self.filter_nets:
            return
        self.events.append(TraceEvent(time, net_name, old_state, new_state))

    def dump_text(self, indent: str = "") -> str:
        """Human-readable trace output."""
        lines = []
        for ev in self.events:
            lines.append(
                f"{indent}{ev.time:8.2f}ms  {ev.net_name}: "
                f"{ev.old_state.value} -> {ev.new_state.value}")
        return "\n".join(lines)

    def dump_table(self, nets: list[str] | None = None) -> str:
        """
        Tabular trace showing net states at each time point.
        Like a logic analyzer view.
        """
        if nets is None:
            nets = sorted(set(ev.net_name for ev in self.events))

        if not nets:
            return "(no events)"

        # Build timeline
        times = sorted(set(ev.time for ev in self.events))
        if not times:
            return "(no events)"

        # Track current state of each net
        current: dict[str, WireState] = {}
        for name in nets:
            current[name] = self.initial_states.get(name, WireState.FLOAT)

        # Build header
        max_name = max(len(n) for n in nets)
        header = " " * (max_name + 2) + "  ".join(f"{t:6.1f}" for t in times)
        lines = [header]
        lines.append("-" * len(header))

        # Build event index by time
        events_at: dict[float, dict[str, WireState]] = {}
        for ev in self.events:
            if ev.net_name in nets:
                if ev.time not in events_at:
                    events_at[ev.time] = {}
                events_at[ev.time][ev.net_name] = ev.new_state

        # Build rows
        for name in nets:
            state = self.initial_states.get(name, WireState.FLOAT)
            cells = []
            for t in times:
                if t in events_at and name in events_at[t]:
                    state = events_at[t][name]
                symbol = {"H": "  H   ", "L": "  L   ", "Z": "  Z   "}[state.value]
                cells.append(symbol)
            lines.append(f"{name:>{max_name}}  {''.join(cells)}")

        return "\n".join(lines)

    def to_vcd(self, timescale: str = "1ms") -> str:
        """
        Generate VCD (Value Change Dump) output.

        VCD is the standard format for waveform viewers like GTKWave.
        """
        out = StringIO()

        # Header
        out.write(f"$timescale {timescale} $end\n")
        out.write("$scope module top $end\n")

        # Collect all nets
        all_nets = sorted(set(ev.net_name for ev in self.events))
        if not all_nets:
            all_nets = sorted(self.initial_states.keys())

        # Assign VCD identifiers (single printable ASCII chars)
        net_ids: dict[str, str] = {}
        for i, name in enumerate(all_nets):
            # Use ASCII chars starting from '!'
            net_ids[name] = chr(33 + (i % 94))

        for name in all_nets:
            vid = net_ids[name]
            # Sanitize name for VCD (replace dots with underscores)
            safe_name = name.replace(".", "_").replace("[", "_").replace("]", "")
            out.write(f"$var wire 1 {vid} {safe_name} $end\n")

        out.write("$upscope $end\n")
        out.write("$enddefinitions $end\n")

        # Initial values
        out.write("#0\n")
        for name in all_nets:
            vid = net_ids[name]
            state = self.initial_states.get(name, WireState.FLOAT)
            vcd_val = _state_to_vcd(state)
            out.write(f"{vcd_val}{vid}\n")

        # Events grouped by time
        events_by_time: dict[float, list[TraceEvent]] = {}
        for ev in self.events:
            if ev.time not in events_by_time:
                events_by_time[ev.time] = []
            events_by_time[ev.time].append(ev)

        for time in sorted(events_by_time.keys()):
            # VCD times are integers; scale based on timescale
            out.write(f"#{int(time)}\n")
            for ev in events_by_time[time]:
                if ev.net_name in net_ids:
                    vid = net_ids[ev.net_name]
                    vcd_val = _state_to_vcd(ev.new_state)
                    out.write(f"{vcd_val}{vid}\n")

        return out.getvalue()


def _state_to_vcd(state: WireState) -> str:
    """Convert WireState to VCD value character."""
    if state == WireState.HIGH:
        return "1"
    elif state == WireState.LOW:
        return "0"
    else:
        return "z"
