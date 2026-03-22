from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from ..lang.errors import SimulationError


class WireState(Enum):
    HIGH = "H"
    LOW = "L"
    FLOAT = "Z"

    def __bool__(self) -> bool:
        return self == WireState.HIGH

    def __str__(self) -> str:
        return self.value

    @staticmethod
    def from_str(s: str) -> WireState:
        mapping = {
            "HIGH": WireState.HIGH, "H": WireState.HIGH, "1": WireState.HIGH,
            "LOW": WireState.LOW, "L": WireState.LOW, "0": WireState.LOW,
            "FLOAT": WireState.FLOAT, "Z": WireState.FLOAT,
        }
        if s in mapping:
            return mapping[s]
        raise ValueError(f"Unknown wire state: {s!r}")


@dataclass
class Net:
    """A named electrical net that can be driven by multiple sources."""
    name: str
    drivers: dict[str, WireState] = field(default_factory=dict)
    _resolved: WireState = field(default=WireState.FLOAT, init=False)

    @property
    def state(self) -> WireState:
        return self._resolved

    def resolve(self) -> WireState:
        """Resolve the net state from all drivers. Returns the new state."""
        active_high = False
        active_low = False
        for driver_id, state in self.drivers.items():
            if state == WireState.HIGH:
                active_high = True
            elif state == WireState.LOW:
                active_low = True

        if active_high and active_low:
            raise SimulationError(
                f"Net '{self.name}' has conflicting drivers: "
                f"{', '.join(f'{k}={v}' for k, v in self.drivers.items() if v != WireState.FLOAT)}"
            )

        if active_high:
            self._resolved = WireState.HIGH
        elif active_low:
            self._resolved = WireState.LOW
        else:
            self._resolved = WireState.FLOAT
        return self._resolved

    def drive(self, driver_id: str, state: WireState):
        self.drivers[driver_id] = state

    def release(self, driver_id: str):
        self.drivers.pop(driver_id, None)

    def __repr__(self) -> str:
        return f"Net({self.name!r}, state={self._resolved})"


class UnionFind:
    """Union-Find for dynamically grouping nets connected by closed contacts."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def make_set(self, x: str):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.make_set(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def connected(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> dict[str, set[str]]:
        """Return all equivalence groups."""
        result: dict[str, set[str]] = {}
        for x in self.parent:
            root = self.find(x)
            if root not in result:
                result[root] = set()
            result[root].add(x)
        return result


class NetResolver:
    """
    Resolves net states considering relay contact connections.

    Rebuilds net equivalence classes each propagation cycle based on
    which contacts are currently closed. Nets in the same equivalence
    class share a common resolved state.
    """

    def __init__(self, nets: dict[str, Net]):
        self.nets = nets

    def resolve_all(self, closed_contacts: list[tuple[str, str]]) -> dict[str, WireState]:
        """
        Given a list of closed contacts (pairs of net names),
        resolve all net states considering connectivity.
        """
        uf = UnionFind()

        # Initialize all nets
        for name in self.nets:
            uf.make_set(name)

        # Union connected nets
        for a, b in closed_contacts:
            if a in self.nets and b in self.nets:
                uf.union(a, b)

        # Resolve each equivalence group
        groups = uf.groups()
        result: dict[str, WireState] = {}

        for root, members in groups.items():
            # Collect all drivers from all nets in this group
            group_high = False
            group_low = False
            driver_details: list[str] = []

            for net_name in members:
                net = self.nets[net_name]
                for driver_id, state in net.drivers.items():
                    if state == WireState.HIGH:
                        group_high = True
                        driver_details.append(f"{net_name}.{driver_id}=H")
                    elif state == WireState.LOW:
                        group_low = True
                        driver_details.append(f"{net_name}.{driver_id}=L")

            if group_high and group_low:
                raise SimulationError(
                    f"Conflicting drivers in connected net group "
                    f"{{{', '.join(sorted(members))}}}: {', '.join(driver_details)}"
                )

            if group_high:
                state = WireState.HIGH
            elif group_low:
                state = WireState.LOW
            else:
                state = WireState.FLOAT

            for net_name in members:
                result[net_name] = state
                self.nets[net_name]._resolved = state

        return result
