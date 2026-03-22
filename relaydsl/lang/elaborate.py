"""
Instance elaboration for RelayDSL.

Flattens hierarchical component instances into a single-level netlist
by prefixing all internal names and wiring ports through to parent nets.

Example:
    component Adder { port in A, B; port out S; relay R1; ... }
    component Top {
        instance add0 = Adder(A=x, B=y, S=sum);
    }

Elaborates to a flat netlist where:
    - R1 in add0 becomes "add0.R1"
    - R1.coil becomes "add0.R1.coil"
    - Port A of add0 is aliased to parent net "x"
    - etc.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from .ast_nodes import (
    Program, Component, PortDecl, WireDecl, WireDef, RelayDecl,
    DiodeDecl, CapacitorDecl, FuseDecl, BusDecl,
    ConnectStmt, InstanceStmt, InstanceArg, TimingStmt, NetRef,
)
from .errors import SemanticError, SourceLocation


@dataclass
class FlatNet:
    """A net in the flattened netlist."""
    name: str
    init: str | None = None  # "HIGH", "LOW", "FLOAT"


@dataclass
class FlatRelay:
    """A relay in the flattened netlist."""
    name: str
    coil_net: str
    poles: int
    contacts: list[tuple[str, str, str]]  # [(common, no, nc), ...]


@dataclass
class FlatDiode:
    """A diode in the flattened netlist."""
    name: str
    anode: str
    cathode: str


@dataclass
class FlatCapacitor:
    name: str
    terminal: str
    decay: float


@dataclass
class FlatFuse:
    name: str
    terminal_a: str
    terminal_b: str
    intact: bool


@dataclass
class FlatConnection:
    """A permanent wire between two nets."""
    net_a: str
    net_b: str
    has_diode: bool = False


@dataclass
class FlatNetlist:
    """A fully elaborated, flat netlist ready for simulation."""
    name: str
    ports: dict[str, str] = field(default_factory=dict)  # port_name -> direction
    nets: dict[str, FlatNet] = field(default_factory=dict)
    relays: dict[str, FlatRelay] = field(default_factory=dict)
    diodes: dict[str, FlatDiode] = field(default_factory=dict)
    capacitors: dict[str, FlatCapacitor] = field(default_factory=dict)
    fuses: dict[str, FlatFuse] = field(default_factory=dict)
    connections: list[FlatConnection] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (net_a, net_b) = same net

    def add_net(self, name: str, init: str | None = None):
        if name not in self.nets:
            self.nets[name] = FlatNet(name=name, init=init)

    def summary(self) -> str:
        lines = [
            f"FlatNetlist '{self.name}':",
            f"  Ports: {len(self.ports)}",
            f"  Nets: {len(self.nets)}",
            f"  Relays: {len(self.relays)}",
            f"  Diodes: {len(self.diodes)}",
            f"  Capacitors: {len(self.capacitors)}",
            f"  Fuses: {len(self.fuses)}",
            f"  Connections: {len(self.connections)}",
            f"  Port aliases: {len(self.aliases)}",
        ]
        return "\n".join(lines)


class Elaborator:
    """
    Flattens a hierarchical component design into a single-level netlist.

    Usage:
        elaborator = Elaborator(components)
        flat = elaborator.elaborate("TopLevel")
    """

    def __init__(self, components: dict[str, Component]):
        self.components = components
        self.errors: list[SemanticError] = []

    def elaborate(self, top_name: str) -> FlatNetlist:
        """Elaborate a top-level component into a flat netlist."""
        if top_name not in self.components:
            raise SemanticError(f"Component '{top_name}' not found")

        flat = FlatNetlist(name=top_name)
        self._elaborate_component(
            self.components[top_name], prefix="", flat=flat, port_bindings={})
        return flat

    def _elaborate_component(
        self,
        comp: Component,
        prefix: str,
        flat: FlatNetlist,
        port_bindings: dict[str, str],
    ):
        """
        Elaborate a component into the flat netlist.

        Args:
            comp: the component to elaborate
            prefix: name prefix for all internal nets (e.g., "add0." for instance add0)
            flat: the flat netlist being built
            port_bindings: maps port_name -> parent_net_name for this instance
        """
        def prefixed(name: str) -> str:
            """Apply prefix to an internal net name."""
            if prefix:
                return f"{prefix}{name}"
            return name

        def resolve_ref(ref: NetRef) -> str:
            """Resolve a NetRef to a flat net name."""
            raw = str(ref)

            # If this is a port and we have a binding, use the parent net
            if ref.parts[0] in port_bindings and len(ref.parts) == 1:
                return port_bindings[ref.parts[0]]

            # If this references a sub-instance port, it'll be handled
            # when that instance is elaborated
            return prefixed(raw)

        # Pass 1: Declare all nets from ports, wires, relays, etc.
        for member in comp.members:
            if isinstance(member, PortDecl):
                for name in member.names:
                    if name in port_bindings:
                        # Port is bound to a parent net - create alias
                        flat.aliases.append((port_bindings[name], prefixed(name)))
                        flat.add_net(prefixed(name))
                    else:
                        # Top-level port - no binding
                        flat.add_net(prefixed(name))
                    if not prefix:
                        flat.ports[name] = member.direction

            elif isinstance(member, WireDecl):
                for wire_def in member.wires:
                    flat.add_net(prefixed(wire_def.name), init=wire_def.init)

            elif isinstance(member, RelayDecl):
                for name in member.names:
                    rname = prefixed(name)
                    coil = f"{rname}.coil"
                    flat.add_net(coil)
                    contacts = []
                    for ci in range(1, member.poles + 1):
                        common = f"{rname}.c{ci}.common"
                        no = f"{rname}.c{ci}.no"
                        nc = f"{rname}.c{ci}.nc"
                        flat.add_net(common)
                        flat.add_net(no)
                        flat.add_net(nc)
                        contacts.append((common, no, nc))
                    flat.relays[rname] = FlatRelay(
                        name=rname, coil_net=coil,
                        poles=member.poles, contacts=contacts)

            elif isinstance(member, DiodeDecl):
                for name in member.names:
                    dname = prefixed(name)
                    flat.add_net(f"{dname}.anode")
                    flat.add_net(f"{dname}.cathode")
                    flat.diodes[dname] = FlatDiode(
                        name=dname,
                        anode=f"{dname}.anode",
                        cathode=f"{dname}.cathode")

            elif isinstance(member, CapacitorDecl):
                for name in member.names:
                    cname = prefixed(name)
                    flat.add_net(cname)
                    flat.capacitors[cname] = FlatCapacitor(
                        name=cname, terminal=cname,
                        decay=member.decay if member.decay else 100.0)

            elif isinstance(member, FuseDecl):
                for name in member.names:
                    fname = prefixed(name)
                    flat.add_net(f"{fname}.a")
                    flat.add_net(f"{fname}.b")
                    flat.fuses[fname] = FlatFuse(
                        name=fname,
                        terminal_a=f"{fname}.a",
                        terminal_b=f"{fname}.b",
                        intact=(member.state == "INTACT"))

            elif isinstance(member, BusDecl):
                for i in range(member.width):
                    flat.add_net(prefixed(f"{member.name}[{i}]"))

        # Pass 2: Process connections
        for member in comp.members:
            if isinstance(member, ConnectStmt):
                src = resolve_ref(member.source)
                tgt = resolve_ref(member.target)
                flat.add_net(src)
                flat.add_net(tgt)
                if member.has_diode:
                    diode_name = f"{prefix}_diode_{src}_to_{tgt}"
                    flat.diodes[diode_name] = FlatDiode(
                        name=diode_name, anode=src, cathode=tgt)
                else:
                    flat.connections.append(FlatConnection(
                        net_a=src, net_b=tgt))

        # Pass 3: Elaborate sub-instances
        for member in comp.members:
            if isinstance(member, InstanceStmt):
                self._elaborate_instance(member, prefix, flat, comp)

    def _elaborate_instance(
        self,
        inst: InstanceStmt,
        parent_prefix: str,
        flat: FlatNetlist,
        parent_comp: Component,
    ):
        """Elaborate a sub-instance."""
        if inst.component not in self.components:
            self.errors.append(SemanticError(
                f"Instance '{inst.name}' references unknown component "
                f"'{inst.component}'", inst.loc))
            return

        child_comp = self.components[inst.component]
        inst_prefix = f"{parent_prefix}{inst.name}." if parent_prefix else f"{inst.name}."

        # Build port bindings from instance arguments
        # Handles both scalar and bus bindings:
        #   Scalar: A=signal    -> bindings["A"] = "signal"
        #   Bus:    A=data[0..3] -> bindings["A[0]"]="data[0]", bindings["A[1]"]="data[1]", etc.
        bindings: dict[str, str] = {}

        # Find bus port widths in the child component
        child_bus_ports: dict[str, int] = {}
        for member in child_comp.members:
            if isinstance(member, PortDecl):
                for pd in member.port_defs:
                    if pd.width is not None:
                        child_bus_ports[pd.name] = pd.width

        for arg in inst.args:
            if arg.value.is_slice:
                # Bus binding: A=data[0..3]
                # Expand into per-bit bindings
                parent_refs = arg.value.expand_slice()
                width = arg.value.slice_width

                # Check if child port is a bus port
                if arg.name in child_bus_ports:
                    child_width = child_bus_ports[arg.name]
                    if width != child_width:
                        self.errors.append(SemanticError(
                            f"Bus width mismatch: port '{arg.name}' is {child_width} bits "
                            f"but slice '{arg.value}' is {width} bits",
                            inst.loc))
                        continue
                    for i, pref in enumerate(parent_refs):
                        child_net = f"{arg.name}[{i}]"
                        parent_net = str(pref)
                        if parent_prefix:
                            parent_net = f"{parent_prefix}{parent_net}"
                        bindings[child_net] = parent_net
                else:
                    # Maybe individual ports named arg.name0, arg.name1, ...
                    # Try numeric suffix: A0, A1, A2, A3
                    for i, pref in enumerate(parent_refs):
                        child_net = f"{arg.name}{i}"
                        parent_net = str(pref)
                        if parent_prefix:
                            parent_net = f"{parent_prefix}{parent_net}"
                        bindings[child_net] = parent_net
            elif arg.name in child_bus_ports and arg.value.index is None:
                # Bus-to-bus shorthand: A=data (both are buses of same width)
                child_width = child_bus_ports[arg.name]
                parent_base = str(arg.value)
                for i in range(child_width):
                    child_net = f"{arg.name}[{i}]"
                    parent_net = f"{parent_base}[{i}]"
                    if parent_prefix:
                        parent_net = f"{parent_prefix}{parent_net}"
                    bindings[child_net] = parent_net
            else:
                # Scalar binding
                parent_net = str(arg.value)
                if parent_prefix:
                    parent_net = f"{parent_prefix}{parent_net}"
                bindings[arg.name] = parent_net

        # Handle array instances
        if inst.count is not None:
            for i in range(inst.count):
                array_prefix = f"{parent_prefix}{inst.name}[{i}]."
                # Array instances don't have individual port bindings in the current syntax
                self._elaborate_component(
                    child_comp, prefix=array_prefix, flat=flat, port_bindings={})
        else:
            self._elaborate_component(
                child_comp, prefix=inst_prefix, flat=flat, port_bindings=bindings)


def elaborate(program: Program, top_name: str) -> FlatNetlist:
    """Convenience: elaborate a program's top-level component."""
    components = {item.name: item for item in program.items
                  if isinstance(item, Component)}
    elaborator = Elaborator(components)
    return elaborator.elaborate(top_name)


def load_flat_into_engine(flat: FlatNetlist, engine) -> None:
    """
    Load a FlatNetlist into a SimEngine.

    This bridges elaboration and simulation - takes the flat netlist
    and creates all the nets, relays, connections etc. in the engine.
    """
    from ..sim.nets import WireState
    from ..sim.components import RelayModel, DiodeModel, CapacitorModel, FuseModel, Contact

    # Create all nets
    for name, fnet in flat.nets.items():
        net = engine.get_or_create_net(name)
        if fnet.init:
            state = WireState.from_str(fnet.init)
            net.drive(f"init:{name}", state)

    # Create relays
    for rname, frelay in flat.relays.items():
        contacts = []
        for common, no, nc in frelay.contacts:
            contacts.append(Contact(common=common, no=no, nc=nc))
        relay = RelayModel(name=rname, coil_net=frelay.coil_net, contacts=contacts)
        engine.relays[rname] = relay

    # Create diodes
    for dname, fdiode in flat.diodes.items():
        engine.diodes[dname] = DiodeModel(
            name=dname, anode_net=fdiode.anode, cathode_net=fdiode.cathode)

    # Create capacitors
    for cname, fcap in flat.capacitors.items():
        engine.capacitors[cname] = CapacitorModel(
            name=cname, terminal=fcap.terminal, decay_time=fcap.decay)

    # Create fuses
    for fname, ffuse in flat.fuses.items():
        engine.fuses[fname] = FuseModel(
            name=fname, terminal_a=ffuse.terminal_a,
            terminal_b=ffuse.terminal_b, intact=ffuse.intact)

    # Add connections
    for conn in flat.connections:
        engine.connections.append((conn.net_a, conn.net_b))

    # Add port aliases as connections (same electrical node)
    for a, b in flat.aliases:
        engine.get_or_create_net(a)
        engine.get_or_create_net(b)
        engine.connections.append((a, b))

    # Store port map
    for port_name, direction in flat.ports.items():
        engine.port_map[port_name] = port_name
