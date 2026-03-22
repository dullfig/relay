from __future__ import annotations
from dataclasses import dataclass, field
from .nets import Net, WireState, NetResolver
from .components import RelayModel, DiodeModel, CapacitorModel, FuseModel, Contact
from .events import EventQueue
from .trace import TraceRecorder
from .timing import RelayTiming, TIMING_STANDARD, convert_time
from ..lang.errors import SimulationError
from ..lang.ast_nodes import (
    Component, ConnectStmt, RelayDecl, DiodeDecl, CapacitorDecl,
    FuseDecl, WireDecl, PortDecl, BusDecl, NetRef,
)


class SimEngine:
    """
    Event-driven relay circuit simulator.

    Supports two modes:
    - zero_delay: ideal logic, all relays switch instantly (for functional verification)
    - timed: realistic delays for energize/de-energize/bounce
    """

    def __init__(self, timing_mode: str = "zero_delay"):
        self.timing_mode = timing_mode
        self.time: float = 0.0
        self.nets: dict[str, Net] = {}
        self.relays: dict[str, RelayModel] = {}
        self.diodes: dict[str, DiodeModel] = {}
        self.capacitors: dict[str, CapacitorModel] = {}
        self.fuses: dict[str, FuseModel] = {}
        self.connections: list[tuple[str, str]] = []  # permanent wire connections
        self.events = EventQueue()
        self.trace = TraceRecorder()
        self.port_map: dict[str, str] = {}  # port name -> net name

    def get_or_create_net(self, name: str) -> Net:
        if name not in self.nets:
            self.nets[name] = Net(name=name)
        return self.nets[name]

    def resolve_net_ref(self, ref: NetRef) -> str:
        """Resolve a NetRef to a net name string."""
        if len(ref.parts) == 1:
            return ref.parts[0]
        # Dotted reference: e.g., R1.coil, R1.c1.common
        return ".".join(ref.parts)

    def load_component(self, comp: Component):
        """Load a component definition into the simulator."""
        for member in comp.members:
            if isinstance(member, PortDecl):
                for name in member.names:
                    self.get_or_create_net(name)
                    self.port_map[name] = name
            elif isinstance(member, WireDecl):
                for wire_def in member.wires:
                    net = self.get_or_create_net(wire_def.name)
                    if wire_def.init:
                        state = WireState.from_str(wire_def.init)
                        net.drive(f"init:{wire_def.name}", state)
            elif isinstance(member, RelayDecl):
                for name in member.names:
                    self._create_relay(name, num_contacts=member.poles)
            elif isinstance(member, DiodeDecl):
                for name in member.names:
                    # Diodes are connected via connect statements
                    pass
            elif isinstance(member, CapacitorDecl):
                for name in member.names:
                    net = self.get_or_create_net(name)
                    cap = CapacitorModel(
                        name=name,
                        terminal=name,
                        decay_time=member.decay if member.decay else 100.0,
                    )
                    self.capacitors[name] = cap
            elif isinstance(member, FuseDecl):
                for name in member.names:
                    # Fuse terminals are connected via connect statements
                    pass
            elif isinstance(member, BusDecl):
                for i in range(member.width):
                    self.get_or_create_net(f"{member.name}[{i}]")
            elif isinstance(member, ConnectStmt):
                src = self.resolve_net_ref(member.source)
                tgt = self.resolve_net_ref(member.target)
                self.get_or_create_net(src)
                self.get_or_create_net(tgt)
                if member.has_diode:
                    diode_name = f"_diode_{src}_to_{tgt}"
                    diode = DiodeModel(
                        name=diode_name,
                        anode_net=src,
                        cathode_net=tgt,
                    )
                    self.diodes[diode_name] = diode
                else:
                    self.connections.append((src, tgt))

    def _create_relay(self, name: str, num_contacts: int = 2):
        """Create a relay with its associated nets. Default DPDT (2 contacts)."""
        coil_net = f"{name}.coil"
        self.get_or_create_net(coil_net)

        contacts = []
        for ci in range(1, num_contacts + 1):
            common = f"{name}.c{ci}.common"
            no = f"{name}.c{ci}.no"
            nc = f"{name}.c{ci}.nc"
            self.get_or_create_net(common)
            self.get_or_create_net(no)
            self.get_or_create_net(nc)
            contacts.append(Contact(common=common, no=no, nc=nc))

        relay = RelayModel(name=name, coil_net=coil_net, contacts=contacts)
        self.relays[name] = relay

    def drive(self, net_name: str, state: WireState):
        """External drive: set a net to a given state."""
        net = self.get_or_create_net(net_name)
        if state == WireState.FLOAT:
            net.release(f"external:{net_name}")
        else:
            net.drive(f"external:{net_name}", state)
        self.propagate()

    def read(self, net_name: str) -> WireState:
        """Read the resolved state of a net."""
        if net_name in self.nets:
            return self.nets[net_name].state
        return WireState.FLOAT

    def propagate(self):
        """
        Resolve all net states considering relay contacts, diodes,
        and permanent connections. Iterate until stable.
        """
        max_iterations = 100
        for iteration in range(max_iterations):
            # 0. Release cap drivers before resolution
            # Caps are passive - they re-assert in step 3 if needed
            for cap in self.capacitors.values():
                if cap.terminal in self.nets:
                    self.nets[cap.terminal].release(f"cap:{cap.name}")

            # 1. Collect all closed contacts
            closed = list(self.connections)  # permanent wires

            for relay in self.relays.values():
                closed.extend(relay.closed_contacts())

            for fuse in self.fuses.values():
                contact = fuse.closed_contact()
                if contact:
                    closed.append(contact)

            # 2. Resolve net groups via union-find
            resolver = NetResolver(self.nets)
            old_states = {name: net.state for name, net in self.nets.items()}
            resolver.resolve_all(closed)

            # 3. Apply capacitor logic
            # Caps are passive storage: they yield to active drivers.
            # To detect external drivers in the connected group (union-find),
            # we temporarily remove the cap driver and re-resolve.
            for cap in self.capacitors.values():
                if cap.terminal in self.nets:
                    term_net = self.nets[cap.terminal]

                    # Remove cap driver temporarily
                    term_net.release(f"cap:{cap.name}")

                    # Re-resolve without cap to see if anything else drives
                    resolver2 = NetResolver(self.nets)
                    resolver2.resolve_all(closed)
                    ext_state = term_net.state

                    if ext_state in (WireState.HIGH, WireState.LOW):
                        # External driver present - cap charges
                        cap.write(ext_state, self.time)
                    else:
                        # No external driver - cap drives stored charge
                        stored = cap.read(self.time)
                        if stored != WireState.FLOAT:
                            term_net.drive(f"cap:{cap.name}", stored)
                        # else: cap is discharged, stays released

            # 4. Apply diode logic
            for diode in self.diodes.values():
                anode_state = self.nets[diode.anode_net].state
                cathode_net = self.nets[diode.cathode_net]
                if anode_state == WireState.HIGH:
                    cathode_net.drive(f"diode:{diode.name}", WireState.HIGH)
                else:
                    cathode_net.release(f"diode:{diode.name}")

            # 5. Re-resolve after cap/diode updates
            resolver.resolve_all(closed)

            # 6. Check relay coils and update energized state
            changed = False
            for relay in self.relays.values():
                coil_state = self.nets[relay.coil_net].state
                should_be_energized = (coil_state == WireState.HIGH)

                if should_be_energized != relay.energized:
                    if self.timing_mode == "zero_delay":
                        relay.energized = should_be_energized
                        changed = True
                    else:
                        delay = (relay.energize_delay if should_be_energized
                                 else relay.deenergize_delay)
                        target_state = should_be_energized
                        self.events.schedule(
                            self.time + delay,
                            f"{'energize' if target_state else 'deenergize'} {relay.name}",
                            lambda r=relay, s=target_state: setattr(r, 'energized', s),
                        )

            # 6. Record trace for changed nets
            for name, net in self.nets.items():
                old = old_states.get(name, WireState.FLOAT)
                if net.state != old:
                    self.trace.record(self.time, name, old, net.state)

            if not changed:
                break
        else:
            raise SimulationError(
                "Oscillation detected: net states not converging after "
                f"{max_iterations} iterations"
            )

    def step(self, until: float):
        """Advance simulation time, processing events."""
        while not self.events.is_empty():
            next_time = self.events.peek_time()
            if next_time is not None and next_time <= until:
                event = self.events.pop()
                if event:
                    self.time = event.time
                    event.action()
                    self.propagate()
            else:
                break
        self.time = until

    def run_vectors(self, vectors: list, port_names_in: list[str],
                    port_names_out: list[str]) -> list[dict]:
        """
        Run a list of test vectors (input dicts) and return output states.
        Each vector is a dict of {port_name: "0" or "1"}.
        """
        results = []
        for vec_inputs in vectors:
            # Apply inputs
            for name, value in vec_inputs.items():
                state = WireState.HIGH if value in ("1", "HIGH") else WireState.LOW
                self.drive(name, state)

            # Read outputs
            outputs = {}
            for name in port_names_out:
                outputs[name] = self.read(name)
            results.append(outputs)

        return results

    def dump_state(self) -> dict[str, str]:
        """Return current state of all nets for debugging."""
        return {name: str(net.state) for name, net in sorted(self.nets.items())}

    def dump_relays(self) -> dict[str, str]:
        """Return current state of all relays for debugging."""
        return {name: ("ON" if r.energized else "OFF")
                for name, r in sorted(self.relays.items())}
