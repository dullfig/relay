from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .errors import SourceLocation


@dataclass
class NetRef:
    """Reference to a net, e.g. R1.c1.common, mybus[3], or mybus[0..3]"""
    parts: list[str]
    index: Optional[int] = None
    end_index: Optional[int] = None  # if set, this is a range slice [index..end_index]
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))

    @property
    def is_slice(self) -> bool:
        return self.end_index is not None

    @property
    def slice_width(self) -> int:
        if self.end_index is not None and self.index is not None:
            return self.end_index - self.index + 1
        return 1

    def expand_slice(self) -> list[NetRef]:
        """Expand a bus slice into individual net refs."""
        if not self.is_slice:
            return [self]
        refs = []
        for i in range(self.index, self.end_index + 1):
            refs.append(NetRef(parts=list(self.parts), index=i, loc=self.loc))
        return refs

    def __str__(self) -> str:
        s = ".".join(self.parts)
        if self.is_slice:
            s += f"[{self.index}..{self.end_index}]"
        elif self.index is not None:
            s += f"[{self.index}]"
        return s


# --- Declarations ---

@dataclass
class PortDef:
    """A single port name with optional bus width."""
    name: str
    width: Optional[int] = None  # None = scalar, int = bus port


@dataclass
class PortDecl:
    direction: str  # "in", "out", "inout"
    names: list[str]  # kept for backward compat (scalar ports)
    port_defs: list[PortDef] = field(default_factory=list)  # new: with widths
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class WireDef:
    name: str
    init: Optional[str] = None  # "HIGH", "LOW", "FLOAT", or None


@dataclass
class WireDecl:
    wires: list[WireDef]
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class RelayDecl:
    names: list[str]
    poles: int = 2  # DPDT=2, 4PDT=4, etc.
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class DiodeDecl:
    names: list[str]
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class CapacitorDecl:
    names: list[str]
    decay: Optional[float] = None  # ms
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class FuseDecl:
    names: list[str]
    state: str = "INTACT"  # "INTACT" or "BLOWN"
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class BusDecl:
    name: str
    width: int
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


# --- Statements ---

@dataclass
class ConnectStmt:
    source: NetRef
    target: NetRef
    has_diode: bool = False  # True if ->| was used
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class InstanceArg:
    name: str
    value: NetRef


@dataclass
class InstanceStmt:
    name: str
    component: str
    args: list[InstanceArg] = field(default_factory=list)
    count: Optional[int] = None  # for array instances
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class TimingParam:
    kind: str  # "energize", "deenergize", "bounce"
    value: float
    unit: str  # "ms", "us", "ns", "ticks"


@dataclass
class TimingStmt:
    relay_name: str
    params: list[TimingParam]
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


# --- Testbench statements ---

@dataclass
class DriveStmt:
    net: NetRef
    value: str  # "HIGH", "LOW", "FLOAT"
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class WaitStmt:
    duration: float
    unit: str
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class AssertStmt:
    net: NetRef
    expected: str  # "HIGH", "LOW", "FLOAT"
    at_time: Optional[float] = None
    at_unit: Optional[str] = None
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class CheckStmt:
    net: NetRef
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class SignalAssign:
    name: str
    value: str  # "0" or "1"


@dataclass
class SignalExpect:
    name: str
    expected: str  # "0", "1", or "Z"


@dataclass
class VectorStmt:
    inputs: list[SignalAssign]
    outputs: list[SignalExpect]
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class ForLoop:
    var: str
    start: int
    end: int
    body: list  # list of testbench statements
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


# --- Top-level ---

Member = (PortDecl | WireDecl | RelayDecl | DiodeDecl | CapacitorDecl |
          FuseDecl | BusDecl | ConnectStmt | InstanceStmt | TimingStmt |
          AssertStmt)

TBStatement = (InstanceStmt | DriveStmt | WaitStmt | AssertStmt |
               CheckStmt | VectorStmt | ForLoop)


@dataclass
class Component:
    name: str
    members: list
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class Testbench:
    name: str
    target: str  # component name
    statements: list
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class Import:
    path: str
    loc: SourceLocation = field(default_factory=lambda: SourceLocation("<unknown>", 0, 0))


@dataclass
class Program:
    items: list  # list of Component | Testbench | Import
