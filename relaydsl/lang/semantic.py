"""
Semantic analysis for RelayDSL.

Builds a symbol table, resolves net references, validates connections,
and prepares the AST for simulation or instance elaboration.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .ast_nodes import (
    Program, Component, Testbench, Import,
    PortDecl, WireDecl, WireDef, RelayDecl, DiodeDecl,
    CapacitorDecl, FuseDecl, BusDecl,
    ConnectStmt, InstanceStmt, TimingStmt, NetRef,
    VectorStmt, DriveStmt, WaitStmt, AssertStmt, CheckStmt, ForLoop,
)
from .errors import SemanticError, SourceLocation


# --- Symbol kinds ---

@dataclass
class PortSymbol:
    name: str
    direction: str  # "in", "out", "inout"
    loc: SourceLocation


@dataclass
class WireSymbol:
    name: str
    init: Optional[str]  # "HIGH", "LOW", "FLOAT", or None
    loc: SourceLocation


@dataclass
class RelaySymbol:
    name: str
    poles: int  # number of contact pairs
    loc: SourceLocation

    def valid_subnets(self) -> set[str]:
        """Return all valid dotted sub-references for this relay."""
        nets = {"coil"}
        for i in range(1, self.poles + 1):
            nets.add(f"c{i}")
            nets.add(f"c{i}.common")
            nets.add(f"c{i}.no")
            nets.add(f"c{i}.nc")
        return nets

    def all_net_names(self) -> list[str]:
        """Return all fully qualified net names for this relay."""
        names = [f"{self.name}.coil"]
        for i in range(1, self.poles + 1):
            names.append(f"{self.name}.c{i}.common")
            names.append(f"{self.name}.c{i}.no")
            names.append(f"{self.name}.c{i}.nc")
        return names


@dataclass
class DiodeSymbol:
    name: str
    loc: SourceLocation


@dataclass
class CapacitorSymbol:
    name: str
    decay: Optional[float]
    loc: SourceLocation


@dataclass
class FuseSymbol:
    name: str
    state: str
    loc: SourceLocation


@dataclass
class BusSymbol:
    name: str
    width: int
    loc: SourceLocation

    def all_net_names(self) -> list[str]:
        return [f"{self.name}[{i}]" for i in range(self.width)]


@dataclass
class InstanceSymbol:
    name: str
    component_name: str
    count: Optional[int]  # array instance
    loc: SourceLocation


Symbol = (PortSymbol | WireSymbol | RelaySymbol | DiodeSymbol |
          CapacitorSymbol | FuseSymbol | BusSymbol | InstanceSymbol)


# --- Analyzed component ---

@dataclass
class AnalyzedComponent:
    """A component after semantic analysis."""
    name: str
    ports: dict[str, PortSymbol] = field(default_factory=dict)
    wires: dict[str, WireSymbol] = field(default_factory=dict)
    relays: dict[str, RelaySymbol] = field(default_factory=dict)
    diodes: dict[str, DiodeSymbol] = field(default_factory=dict)
    capacitors: dict[str, CapacitorSymbol] = field(default_factory=dict)
    fuses: dict[str, FuseSymbol] = field(default_factory=dict)
    buses: dict[str, BusSymbol] = field(default_factory=dict)
    instances: dict[str, InstanceSymbol] = field(default_factory=dict)
    connections: list[ConnectStmt] = field(default_factory=list)
    timing_overrides: dict[str, TimingStmt] = field(default_factory=dict)
    all_nets: set[str] = field(default_factory=set)
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))

    def is_valid_net(self, name: str) -> bool:
        return name in self.all_nets


@dataclass
class AnalyzedTestbench:
    """A testbench after semantic analysis."""
    name: str
    target: str
    target_component: AnalyzedComponent
    statements: list
    loc: SourceLocation


# --- Semantic Analyzer ---

class SemanticAnalyzer:
    """
    Performs semantic analysis on a parsed program.

    Phase 1: Build component registry
    Phase 2: Analyze each component (symbols, nets, validation)
    Phase 3: Analyze testbenches
    """

    def __init__(self):
        self.components: dict[str, Component] = {}
        self.analyzed: dict[str, AnalyzedComponent] = {}
        self.testbenches: list[AnalyzedTestbench] = []
        self.errors: list[SemanticError] = []
        self.warnings: list[str] = []

    def analyze(self, program: Program) -> list[SemanticError]:
        """Analyze a full program. Returns list of errors (empty = success)."""
        # Phase 1: Register all components
        for item in program.items:
            if isinstance(item, Component):
                if item.name in self.components:
                    self.errors.append(SemanticError(
                        f"Duplicate component name '{item.name}'", item.loc))
                else:
                    self.components[item.name] = item

        # Phase 2: Analyze each component
        for name, comp in self.components.items():
            analyzed = self._analyze_component(comp)
            self.analyzed[name] = analyzed

        # Phase 3: Analyze testbenches
        for item in program.items:
            if isinstance(item, Testbench):
                self._analyze_testbench(item)

        return self.errors

    def _error(self, msg: str, loc: SourceLocation):
        self.errors.append(SemanticError(msg, loc))

    def _warn(self, msg: str, loc: SourceLocation):
        self.warnings.append(f"{loc}: warning: {msg}")

    # --- Component Analysis ---

    def _analyze_component(self, comp: Component) -> AnalyzedComponent:
        ac = AnalyzedComponent(name=comp.name, loc=comp.loc)

        # Pass 1: Collect all declarations (build symbol table)
        for member in comp.members:
            if isinstance(member, PortDecl):
                self._declare_ports(ac, member)
            elif isinstance(member, WireDecl):
                self._declare_wires(ac, member)
            elif isinstance(member, RelayDecl):
                self._declare_relays(ac, member)
            elif isinstance(member, DiodeDecl):
                self._declare_diodes(ac, member)
            elif isinstance(member, CapacitorDecl):
                self._declare_capacitors(ac, member)
            elif isinstance(member, FuseDecl):
                self._declare_fuses(ac, member)
            elif isinstance(member, BusDecl):
                self._declare_bus(ac, member)
            elif isinstance(member, InstanceStmt):
                self._declare_instance(ac, member)
            elif isinstance(member, TimingStmt):
                self._process_timing(ac, member)

        # Build the complete net set
        self._build_net_set(ac)

        # Pass 2: Validate connections
        for member in comp.members:
            if isinstance(member, ConnectStmt):
                self._validate_connect(ac, member)
                ac.connections.append(member)

        # Pass 3: Structural checks
        self._check_unconnected_coils(ac)
        self._check_instance_ports(ac)

        return ac

    def _check_name_conflict(self, ac: AnalyzedComponent, name: str,
                              loc: SourceLocation) -> bool:
        """Check if name is already declared. Returns True if conflict."""
        for table in (ac.ports, ac.wires, ac.relays, ac.diodes,
                      ac.capacitors, ac.fuses, ac.buses, ac.instances):
            if name in table:
                self._error(f"Duplicate name '{name}' in component '{ac.name}'", loc)
                return True
        return False

    def _declare_ports(self, ac: AnalyzedComponent, decl: PortDecl):
        for name in decl.names:
            if not self._check_name_conflict(ac, name, decl.loc):
                ac.ports[name] = PortSymbol(name=name, direction=decl.direction,
                                            loc=decl.loc)
        # Also register bus port groups for width-matching
        for pd in decl.port_defs:
            if pd.width is not None:
                # Register the bus name as a known bus-port
                if not hasattr(ac, 'bus_ports'):
                    ac.bus_ports = {}
                ac.bus_ports[pd.name] = pd.width

    def _declare_wires(self, ac: AnalyzedComponent, decl: WireDecl):
        for wire_def in decl.wires:
            if not self._check_name_conflict(ac, wire_def.name, decl.loc):
                ac.wires[wire_def.name] = WireSymbol(
                    name=wire_def.name, init=wire_def.init, loc=decl.loc)

    def _declare_relays(self, ac: AnalyzedComponent, decl: RelayDecl):
        for name in decl.names:
            if not self._check_name_conflict(ac, name, decl.loc):
                ac.relays[name] = RelaySymbol(
                    name=name, poles=decl.poles, loc=decl.loc)

    def _declare_diodes(self, ac: AnalyzedComponent, decl: DiodeDecl):
        for name in decl.names:
            if not self._check_name_conflict(ac, name, decl.loc):
                ac.diodes[name] = DiodeSymbol(name=name, loc=decl.loc)

    def _declare_capacitors(self, ac: AnalyzedComponent, decl: CapacitorDecl):
        for name in decl.names:
            if not self._check_name_conflict(ac, name, decl.loc):
                ac.capacitors[name] = CapacitorSymbol(
                    name=name, decay=decl.decay, loc=decl.loc)

    def _declare_fuses(self, ac: AnalyzedComponent, decl: FuseDecl):
        for name in decl.names:
            if not self._check_name_conflict(ac, name, decl.loc):
                ac.fuses[name] = FuseSymbol(
                    name=name, state=decl.state, loc=decl.loc)

    def _declare_bus(self, ac: AnalyzedComponent, decl: BusDecl):
        if not self._check_name_conflict(ac, decl.name, decl.loc):
            ac.buses[decl.name] = BusSymbol(
                name=decl.name, width=decl.width, loc=decl.loc)

    def _declare_instance(self, ac: AnalyzedComponent, stmt: InstanceStmt):
        if not self._check_name_conflict(ac, stmt.name, stmt.loc):
            ac.instances[stmt.name] = InstanceSymbol(
                name=stmt.name, component_name=stmt.component,
                count=stmt.count, loc=stmt.loc)

    def _process_timing(self, ac: AnalyzedComponent, stmt: TimingStmt):
        if stmt.relay_name not in ac.relays:
            self._error(
                f"Timing override for unknown relay '{stmt.relay_name}'",
                stmt.loc)
        else:
            ac.timing_overrides[stmt.relay_name] = stmt

    # --- Net set construction ---

    def _build_net_set(self, ac: AnalyzedComponent):
        """Build the complete set of valid net names for this component."""
        nets = set()

        # Ports are nets
        for name in ac.ports:
            nets.add(name)

        # Wires are nets
        for name in ac.wires:
            nets.add(name)

        # Relays generate sub-nets
        for relay in ac.relays.values():
            for net_name in relay.all_net_names():
                nets.add(net_name)

        # Diodes have anode/cathode sub-nets
        for name in ac.diodes:
            nets.add(f"{name}.anode")
            nets.add(f"{name}.cathode")

        # Capacitors are nets (terminal name)
        for name in ac.capacitors:
            nets.add(name)

        # Fuses have terminal sub-nets
        for name in ac.fuses:
            nets.add(f"{name}.a")
            nets.add(f"{name}.b")

        # Buses expand to indexed nets
        for bus in ac.buses.values():
            for net_name in bus.all_net_names():
                nets.add(net_name)

        # Instance ports generate prefixed nets
        for inst in ac.instances.values():
            if inst.component_name in self.analyzed:
                target = self.analyzed[inst.component_name]
                for port_name in target.ports:
                    nets.add(f"{inst.name}.{port_name}")
            elif inst.component_name in self.components:
                # Not yet analyzed - will be checked in a later pass
                pass
            # else: error caught in _check_instance_ports

        ac.all_nets = nets

    # --- Net reference resolution ---

    def _resolve_net_ref(self, ac: AnalyzedComponent, ref: NetRef) -> str | None:
        """
        Resolve a NetRef to a net name string, validating it exists.
        Returns the resolved name or None on error.
        """
        name = str(ref)  # e.g., "R1.c1.common" or "mybus[3]"

        # Direct match
        if name in ac.all_nets:
            return name

        # Check if it's a relay sub-reference
        if len(ref.parts) >= 2:
            relay_name = ref.parts[0]
            if relay_name in ac.relays:
                relay = ac.relays[relay_name]
                sub_path = ".".join(ref.parts[1:])
                if sub_path in relay.valid_subnets():
                    full_name = f"{relay_name}.{sub_path}"
                    if full_name in ac.all_nets:
                        return full_name
                else:
                    self._error(
                        f"Invalid relay reference '{name}': "
                        f"relay '{relay_name}' ({relay.poles}PDT) has no sub-net '{sub_path}'. "
                        f"Valid: {sorted(relay.valid_subnets())}",
                        ref.loc)
                    return None

        # Check if it's an instance port reference
        if len(ref.parts) == 2:
            inst_name = ref.parts[0]
            if inst_name in ac.instances:
                full_name = f"{inst_name}.{ref.parts[1]}"
                if full_name in ac.all_nets:
                    return full_name
                # Instance might not be analyzed yet
                inst = ac.instances[inst_name]
                if inst.component_name in self.analyzed:
                    target = self.analyzed[inst.component_name]
                    if ref.parts[1] not in target.ports:
                        self._error(
                            f"Instance '{inst_name}' of '{inst.component_name}' "
                            f"has no port '{ref.parts[1]}'",
                            ref.loc)
                return full_name  # allow it, will be validated later

        # Bus index
        if ref.index is not None and len(ref.parts) == 1:
            bus_name = ref.parts[0]
            if bus_name in ac.buses:
                bus = ac.buses[bus_name]
                if 0 <= ref.index < bus.width:
                    return f"{bus_name}[{ref.index}]"
                else:
                    self._error(
                        f"Bus index {ref.index} out of range for "
                        f"'{bus_name}[{bus.width}]'",
                        ref.loc)
                    return None

        self._error(f"Unknown net '{name}' in component '{ac.name}'", ref.loc)
        return None

    # --- Connection validation ---

    def _validate_connect(self, ac: AnalyzedComponent, stmt: ConnectStmt):
        """Validate a connect statement."""
        src = self._resolve_net_ref(ac, stmt.source)
        tgt = self._resolve_net_ref(ac, stmt.target)

        if src and tgt and src == tgt:
            self._warn(f"Net '{src}' connected to itself", stmt.loc)

        # Check port direction (advisory, not enforced for relay circuits
        # since relay contacts are bidirectional)
        if src and tgt and not stmt.has_diode:
            self._check_direction_hint(ac, stmt.source, stmt.target, stmt.loc)

    def _check_direction_hint(self, ac: AnalyzedComponent,
                               src_ref: NetRef, tgt_ref: NetRef,
                               loc: SourceLocation):
        """Advisory check: warn if connecting two outputs together."""
        src_name = src_ref.parts[0] if src_ref.parts else ""
        tgt_name = tgt_ref.parts[0] if tgt_ref.parts else ""

        src_port = ac.ports.get(src_name)
        tgt_port = ac.ports.get(tgt_name)

        if (src_port and tgt_port and
                src_port.direction == "out" and tgt_port.direction == "out"):
            self._warn(
                f"Connecting two output ports '{src_name}' and '{tgt_name}' - "
                f"potential driver conflict",
                loc)

    # --- Structural checks ---

    def _check_unconnected_coils(self, ac: AnalyzedComponent):
        """Warn about relay coils that are never connected."""
        connected_nets = set()
        for conn in ac.connections:
            connected_nets.add(str(conn.source))
            connected_nets.add(str(conn.target))

        for relay in ac.relays.values():
            coil_net = f"{relay.name}.coil"
            if coil_net not in connected_nets:
                self._warn(
                    f"Relay '{relay.name}' coil is not connected to anything",
                    relay.loc)

    def _check_instance_ports(self, ac: AnalyzedComponent):
        """Validate that instances reference known components."""
        for inst in ac.instances.values():
            if (inst.component_name not in self.components and
                    inst.component_name not in self.analyzed):
                self._error(
                    f"Instance '{inst.name}' references unknown component "
                    f"'{inst.component_name}'",
                    inst.loc)

    # --- Testbench analysis ---

    def _analyze_testbench(self, tb: Testbench):
        if tb.target not in self.analyzed:
            if tb.target not in self.components:
                self._error(
                    f"Testbench '{tb.name}' targets unknown component '{tb.target}'",
                    tb.loc)
                return
            # Might need to analyze it first
            if tb.target not in self.analyzed:
                self._error(
                    f"Testbench '{tb.name}' targets component '{tb.target}' "
                    f"which failed analysis",
                    tb.loc)
                return

        target_comp = self.analyzed[tb.target]

        # Validate testbench statements
        for stmt in tb.statements:
            self._validate_tb_statement(target_comp, stmt)

        self.testbenches.append(AnalyzedTestbench(
            name=tb.name,
            target=tb.target,
            target_component=target_comp,
            statements=tb.statements,
            loc=tb.loc,
        ))

    def _validate_tb_statement(self, comp: AnalyzedComponent, stmt):
        """Validate a testbench statement against the target component."""
        if isinstance(stmt, VectorStmt):
            for assign in stmt.inputs:
                if assign.name not in comp.ports:
                    self._error(
                        f"Vector references unknown port '{assign.name}'",
                        stmt.loc)
                elif comp.ports[assign.name].direction == "out":
                    self._error(
                        f"Vector drives output port '{assign.name}'",
                        stmt.loc)
            for expect in stmt.outputs:
                if expect.name not in comp.ports:
                    self._error(
                        f"Vector checks unknown port '{expect.name}'",
                        stmt.loc)
        elif isinstance(stmt, DriveStmt):
            net_name = str(stmt.net)
            if (net_name not in comp.ports and
                    not comp.is_valid_net(net_name)):
                self._error(
                    f"Drive references unknown net '{net_name}'",
                    stmt.loc)
        elif isinstance(stmt, AssertStmt):
            net_name = str(stmt.net)
            if (net_name not in comp.ports and
                    not comp.is_valid_net(net_name)):
                self._error(
                    f"Assert references unknown net '{net_name}'",
                    stmt.loc)
        elif isinstance(stmt, CheckStmt):
            net_name = str(stmt.net)
            if (net_name not in comp.ports and
                    not comp.is_valid_net(net_name)):
                self._error(
                    f"Check references unknown net '{net_name}'",
                    stmt.loc)
        elif isinstance(stmt, ForLoop):
            for body_stmt in stmt.body:
                self._validate_tb_statement(comp, body_stmt)


# --- Convenience ---

def analyze(program: Program) -> tuple[SemanticAnalyzer, list[SemanticError]]:
    """Analyze a program. Returns (analyzer, errors)."""
    sa = SemanticAnalyzer()
    errors = sa.analyze(program)
    return sa, errors


def analyze_source(source: str, filename: str = "<input>") -> tuple[SemanticAnalyzer, list[SemanticError]]:
    """Parse and analyze source code. Returns (analyzer, errors)."""
    from .parser import parse
    program = parse(source, filename)
    return analyze(program)
