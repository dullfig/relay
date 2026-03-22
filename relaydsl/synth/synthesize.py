"""
Shannon Expansion Synthesizer for Relay Circuits.

Takes a boolean function (truth table) and synthesizes a relay circuit
that implements it using minimal relays.

Each relay is a multiplexer: coil selects between NC (coil=0) and NO (coil=1).
Cascading relays implements Shannon expansion:
  f(x1,...,xn) = x1 ? f|x1=1 : f|x1=0

The synthesizer:
1. Tries all variable orderings for the coil assignments
2. Builds a mux tree via recursive cofactoring
3. Identifies leaf values (constants 0/1, remaining variables, complements)
4. Picks the ordering that minimizes relay count
5. Generates a relay circuit with physical contact assignments
"""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import permutations
from typing import Optional


# --- Truth Table ---

@dataclass
class TruthTable:
    """A boolean function as a mapping from input bits to output bit."""
    variables: list[str]
    rows: dict[tuple[int, ...], int]  # (v0, v1, ...) -> output

    @staticmethod
    def from_function(variables: list[str], func) -> TruthTable:
        """Build truth table from a Python function."""
        rows = {}
        n = len(variables)
        for i in range(2 ** n):
            bits = tuple((i >> (n - 1 - j)) & 1 for j in range(n))
            kwargs = dict(zip(variables, bits))
            rows[bits] = 1 if func(**kwargs) else 0
        return TruthTable(variables=variables, rows=rows)

    def cofactor(self, var: str, value: int) -> TruthTable:
        """Compute cofactor: restrict variable to a fixed value."""
        idx = self.variables.index(var)
        remaining_vars = [v for v in self.variables if v != var]
        new_rows = {}
        for bits, out in self.rows.items():
            if bits[idx] == value:
                new_bits = tuple(b for j, b in enumerate(bits) if j != idx)
                new_rows[new_bits] = out
        return TruthTable(variables=remaining_vars, rows=new_rows)

    def is_constant(self) -> Optional[int]:
        """If all outputs are the same, return that value. Else None."""
        values = set(self.rows.values())
        if len(values) == 1:
            return values.pop()
        return None

    def is_single_variable(self) -> Optional[str]:
        """If function equals a single variable (positive literal), return it."""
        if len(self.variables) != 1:
            # Check if function depends on only one variable
            for var in self.variables:
                c0 = self.cofactor(var, 0)
                c1 = self.cofactor(var, 1)
                if c0.is_constant() == 0 and c1.is_constant() == 1:
                    return var
            return None
        # Single variable truth table
        bits_0 = (0,)
        bits_1 = (1,)
        if self.rows.get(bits_0) == 0 and self.rows.get(bits_1) == 1:
            return self.variables[0]
        return None

    def is_complement(self) -> Optional[str]:
        """If function equals NOT(variable), return the variable name."""
        if len(self.variables) != 1:
            for var in self.variables:
                c0 = self.cofactor(var, 0)
                c1 = self.cofactor(var, 1)
                if c0.is_constant() == 1 and c1.is_constant() == 0:
                    return var
            return None
        bits_0 = (0,)
        bits_1 = (1,)
        if self.rows.get(bits_0) == 1 and self.rows.get(bits_1) == 0:
            return self.variables[0]
        return None

    def depends_on(self, var: str) -> bool:
        """Check if the function actually depends on this variable."""
        c0 = self.cofactor(var, 0)
        c1 = self.cofactor(var, 1)
        return c0.rows != c1.rows

    def __repr__(self) -> str:
        lines = [f"TruthTable({self.variables})"]
        for bits, out in sorted(self.rows.items()):
            assigns = " ".join(f"{v}={b}" for v, b in zip(self.variables, bits))
            lines.append(f"  {assigns} -> {out}")
        return "\n".join(lines)


# --- Mux Tree ---

@dataclass
class Leaf:
    """Leaf of the mux tree: a constant or a variable reference."""
    value: str  # "0", "1", or a variable name
    negated: bool = False  # True if this is NOT(variable)

    def __repr__(self) -> str:
        if self.negated:
            return f"~{self.value}"
        return self.value

    @staticmethod
    def zero() -> Leaf:
        return Leaf("0")

    @staticmethod
    def one() -> Leaf:
        return Leaf("1")

    @staticmethod
    def var(name: str) -> Leaf:
        return Leaf(name)

    @staticmethod
    def complement(name: str) -> Leaf:
        return Leaf(name, negated=True)


@dataclass
class MuxNode:
    """
    Internal node: a relay contact acting as 2:1 mux.
    select = relay coil variable
    nc = output when coil is de-energized (select=0)
    no = output when coil is energized (select=1)
    """
    select: str  # variable driving the coil
    nc: MuxNode | Leaf = field(default_factory=Leaf.zero)  # normally closed (select=0)
    no: MuxNode | Leaf = field(default_factory=Leaf.zero)  # normally open (select=1)

    def depth(self) -> int:
        d_nc = self.nc.depth() if isinstance(self.nc, MuxNode) else 0
        d_no = self.no.depth() if isinstance(self.no, MuxNode) else 0
        return 1 + max(d_nc, d_no)

    def contact_count(self) -> int:
        """Count total contacts (mux nodes) in the tree."""
        count = 1
        if isinstance(self.nc, MuxNode):
            count += self.nc.contact_count()
        if isinstance(self.no, MuxNode):
            count += self.no.contact_count()
        return count

    def relay_coils(self) -> set[str]:
        """Return set of unique coil variables (= number of physical relays)."""
        coils = {self.select}
        if isinstance(self.nc, MuxNode):
            coils |= self.nc.relay_coils()
        if isinstance(self.no, MuxNode):
            coils |= self.no.relay_coils()
        return coils

    def relay_count(self) -> int:
        return len(self.relay_coils())

    def __repr__(self) -> str:
        return f"Mux({self.select}: 0->{self.nc}, 1->{self.no})"


# --- Shannon Expansion ---

def _classify_leaf(tt: TruthTable) -> Leaf:
    """Convert a terminal truth table to a Leaf node."""
    const = tt.is_constant()
    if const is not None:
        return Leaf.zero() if const == 0 else Leaf.one()

    pos = tt.is_single_variable()
    if pos is not None:
        return Leaf.var(pos)

    neg = tt.is_complement()
    if neg is not None:
        return Leaf.complement(neg)

    return None  # not a simple leaf, needs further expansion


def expand(tt: TruthTable, var_order: list[str]) -> MuxNode | Leaf:
    """
    Build a mux tree by Shannon expansion in the given variable order.

    Each variable in var_order becomes a relay coil (select line).
    The expansion recurses until cofactors reduce to constants or
    single literals.
    """
    # Base case: can we represent this as a leaf?
    leaf = _classify_leaf(tt)
    if leaf is not None:
        return leaf

    # No variables left to expand on?
    if not var_order:
        # Shouldn't happen if truth table is well-formed
        const = tt.is_constant()
        if const is not None:
            return Leaf.zero() if const == 0 else Leaf.one()
        raise ValueError(f"Cannot reduce truth table to leaf: {tt}")

    # Pick the next variable to expand on
    select_var = var_order[0]
    remaining = var_order[1:]

    # Skip if function doesn't depend on this variable
    if not tt.depends_on(select_var):
        return expand(tt.cofactor(select_var, 0), remaining)

    # Shannon expansion: f = select ? f|select=1 : f|select=0
    cofactor_0 = tt.cofactor(select_var, 0)
    cofactor_1 = tt.cofactor(select_var, 1)

    nc = expand(cofactor_0, remaining)  # select=0
    no = expand(cofactor_1, remaining)  # select=1

    # Optimization: if both branches are identical, skip this mux
    if isinstance(nc, Leaf) and isinstance(no, Leaf):
        if nc.value == no.value and nc.negated == no.negated:
            return nc

    return MuxNode(select=select_var, nc=nc, no=no)


# --- Optimal Synthesis ---

@dataclass
class SynthResult:
    """Result of synthesis: a mux tree for each output."""
    outputs: dict[str, MuxNode | Leaf]  # output_name -> mux tree
    var_order: list[str]
    relay_count: int
    contact_count: int

    def relay_coils(self) -> set[str]:
        coils = set()
        for tree in self.outputs.values():
            if isinstance(tree, MuxNode):
                coils |= tree.relay_coils()
        return coils


def synthesize(
    truth_tables: dict[str, TruthTable],
    complementary_inputs: dict[str, str] | None = None,
    max_relays: int | None = None,
) -> SynthResult:
    """
    Synthesize relay circuits for one or more boolean functions.

    Args:
        truth_tables: mapping of output_name -> TruthTable
        complementary_inputs: mapping of var -> complement_var
            e.g. {"CarryIn": "CarryInNeg"} means CarryInNeg is always NOT(CarryIn)
        max_relays: optional upper bound to prune search

    Returns:
        SynthResult with the best (minimum relay) implementation found.
    """
    if not truth_tables:
        raise ValueError("No truth tables provided")

    # All truth tables must share the same variables
    all_vars = None
    for name, tt in truth_tables.items():
        if all_vars is None:
            all_vars = list(tt.variables)
        else:
            if set(tt.variables) != set(all_vars):
                raise ValueError(
                    f"Output '{name}' has different variables: "
                    f"{tt.variables} vs {all_vars}"
                )

    # Remove complementary inputs from the expansion variables
    # (they'll be available as leaf values but won't be relay coils)
    comp_inputs = complementary_inputs or {}
    complement_vars = set(comp_inputs.values())  # the "neg" versions
    expand_vars = [v for v in all_vars if v not in complement_vars]

    best_result: SynthResult | None = None

    # Try all permutations of expansion variable order
    for perm in permutations(expand_vars):
        var_order = list(perm)

        outputs = {}
        total_contacts = 0
        all_coils: set[str] = set()

        for name, tt in truth_tables.items():
            tree = expand(tt, var_order)
            outputs[name] = tree
            if isinstance(tree, MuxNode):
                total_contacts += tree.contact_count()
                all_coils |= tree.relay_coils()

        relay_count = len(all_coils)

        if max_relays is not None and relay_count > max_relays:
            continue

        if best_result is None or relay_count < best_result.relay_count:
            best_result = SynthResult(
                outputs=outputs,
                var_order=var_order,
                relay_count=relay_count,
                contact_count=total_contacts,
            )
        elif relay_count == best_result.relay_count:
            # Tie-break: fewer contacts
            if total_contacts < best_result.contact_count:
                best_result = SynthResult(
                    outputs=outputs,
                    var_order=var_order,
                    relay_count=relay_count,
                    contact_count=total_contacts,
                )

    if best_result is None:
        raise ValueError("No valid synthesis found within constraints")

    return best_result


# --- Code Generation ---

@dataclass
class ContactAssignment:
    """A physical relay contact assignment."""
    relay_name: str      # which relay (named after coil variable)
    contact_num: int     # contact number on that relay
    common: str          # net connected to common
    nc: str              # net connected to NC
    no: str              # net connected to NO


@dataclass
class RelayCircuit:
    """A complete relay circuit ready for simulation or fabrication."""
    relays: dict[str, list[ContactAssignment]]  # relay_name -> contacts
    inputs: list[str]
    outputs: list[str]
    internal_nets: list[str]
    connections: list[tuple[str, str]]  # (net_a, net_b) permanent wires

    def to_relay_dsl(self, component_name: str) -> str:
        """Generate .relay source code for this circuit."""
        lines = [f"component {component_name} {{"]

        # Ports
        if self.inputs:
            lines.append(f"    port in {', '.join(self.inputs)};")
        if self.outputs:
            lines.append(f"    port out {', '.join(self.outputs)};")

        # Constants
        lines.append("    wire vcc = HIGH;")
        lines.append("    wire gnd = LOW;")
        lines.append("")

        # Relays
        if self.relays:
            lines.append(f"    relay {', '.join(sorted(self.relays.keys()))};")
            lines.append("")

        # Coil connections
        for relay_name in sorted(self.relays.keys()):
            lines.append(f"    # {relay_name} coil")
            lines.append(f"    connect {relay_name} -> {relay_name}.coil;")
            lines.append("")

        # Contact connections
        for relay_name in sorted(self.relays.keys()):
            contacts = self.relays[relay_name]
            for ca in contacts:
                lines.append(f"    # {relay_name} contact {ca.contact_num}: "
                             f"NC={ca.nc}, NO={ca.no}")
                lines.append(f"    connect {ca.nc} -> {relay_name}.c{ca.contact_num}.nc;")
                lines.append(f"    connect {ca.no} -> {relay_name}.c{ca.contact_num}.no;")
                lines.append(f"    connect {relay_name}.c{ca.contact_num}.common -> {ca.common};")
            lines.append("")

        lines.append("}")
        return "\n".join(lines)

    def summary(self) -> str:
        total_contacts = sum(len(c) for c in self.relays.values())
        lines = [
            f"Relays: {len(self.relays)} "
            f"(coils: {', '.join(sorted(self.relays.keys()))})",
            f"Contacts: {total_contacts}",
            f"Inputs: {', '.join(self.inputs)}",
            f"Outputs: {', '.join(self.outputs)}",
        ]
        return "\n".join(lines)


def generate_circuit(
    result: SynthResult,
    output_names: list[str],
    input_names: list[str],
    complementary_inputs: dict[str, str] | None = None,
) -> RelayCircuit:
    """
    Convert a SynthResult into a physical RelayCircuit.

    Maps mux tree nodes to relay contacts, allocating contact numbers
    on each relay (grouped by coil variable).
    """
    comp_inputs = complementary_inputs or {}
    all_inputs = list(input_names)
    for neg_var in comp_inputs.values():
        if neg_var not in all_inputs:
            all_inputs.append(neg_var)

    relays: dict[str, list[ContactAssignment]] = {}
    internal_nets: list[str] = []
    net_counter = [0]

    def fresh_net(hint: str = "n") -> str:
        net_counter[0] += 1
        name = f"_{hint}_{net_counter[0]}"
        internal_nets.append(name)
        return name

    def leaf_net(leaf: Leaf) -> str:
        """Map a leaf to a net name."""
        if leaf.value == "0":
            return "gnd"
        elif leaf.value == "1":
            return "vcc"
        elif leaf.negated:
            # Look up complement variable name
            if leaf.value in comp_inputs:
                return comp_inputs[leaf.value]
            else:
                return f"~{leaf.value}"  # needs external complement
        else:
            return leaf.value

    def allocate(node: MuxNode | Leaf, output_net: str):
        """Recursively allocate contacts for a mux tree."""
        if isinstance(node, Leaf):
            # Leaf: just a wire connection, no contact needed
            # The output_net IS the leaf net
            # This case is handled by the parent
            return

        relay_name = node.select
        if relay_name not in relays:
            relays[relay_name] = []

        contact_num = len(relays[relay_name]) + 1

        # Determine NC and NO nets
        if isinstance(node.nc, Leaf):
            nc_net = leaf_net(node.nc)
        else:
            nc_net = fresh_net(f"{relay_name}_c{contact_num}_nc")
            allocate(node.nc, nc_net)

        if isinstance(node.no, Leaf):
            no_net = leaf_net(node.no)
        else:
            no_net = fresh_net(f"{relay_name}_c{contact_num}_no")
            allocate(node.no, no_net)

        relays[relay_name].append(ContactAssignment(
            relay_name=relay_name,
            contact_num=contact_num,
            common=output_net,
            nc=nc_net,
            no=no_net,
        ))

    # Allocate contacts for each output
    for out_name in output_names:
        tree = result.outputs[out_name]
        if isinstance(tree, Leaf):
            # Output is just a wire to a constant or input
            pass  # handled as a simple connection
        else:
            allocate(tree, out_name)

    return RelayCircuit(
        relays=relays,
        inputs=all_inputs,
        outputs=output_names,
        internal_nets=internal_nets,
        connections=[],
    )


# --- Convenience ---

def synthesize_and_generate(
    functions: dict[str, callable],
    variables: list[str],
    complementary_inputs: dict[str, str] | None = None,
    component_name: str = "Synthesized",
) -> tuple[RelayCircuit, str]:
    """
    End-to-end: Python functions -> relay circuit + DSL source.

    Example:
        circuit, source = synthesize_and_generate(
            functions={
                "CarryOut": lambda A, B, CarryIn: (A & B) | (A & CarryIn) | (B & CarryIn),
                "CarryOutNeg": lambda A, B, CarryIn: not ((A & B) | (A & CarryIn) | (B & CarryIn)),
            },
            variables=["A", "B", "CarryIn"],
            complementary_inputs={"CarryIn": "CarryInNeg"},
            component_name="ZuseAdder",
        )
    """
    # Build truth tables
    truth_tables = {}
    for name, func in functions.items():
        truth_tables[name] = TruthTable.from_function(variables, func)

    # Synthesize
    result = synthesize(truth_tables, complementary_inputs)

    # Determine all input names
    comp = complementary_inputs or {}
    input_names = list(variables)
    for neg in comp.values():
        if neg not in input_names:
            input_names.append(neg)

    # Generate circuit
    circuit = generate_circuit(
        result,
        output_names=list(functions.keys()),
        input_names=input_names,
        complementary_inputs=complementary_inputs,
    )

    # Generate DSL
    source = circuit.to_relay_dsl(component_name)

    return circuit, source
