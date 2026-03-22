"""
Diode optimization pass for relay circuits.

Identifies relay stages that implement pure AND/OR logic (no inversion)
and replaces them with cheaper passive diode circuits.

Key insight: diodes can implement AND (series) and OR (parallel/wired-OR)
but cannot invert. A Boolean function is diode-implementable if and only
if it is monotone (unate) -- each variable appears in only one polarity.

The optimizer:
1. Extracts the Boolean function implemented by each relay subcircuit
2. Checks if the function is monotone (unate)
3. If yes, synthesizes a diode AND/OR replacement
4. Reports potential relay savings
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class DiodeGate:
    """A single diode logic gate."""
    gate_type: str  # "AND" or "OR"
    inputs: list[str]  # net names
    output: str


@dataclass
class DiodeReplacement:
    """A proposed replacement of relay logic with diode logic."""
    original_relays: list[str]      # relay names being replaced
    diode_gates: list[DiodeGate]    # replacement diode circuit
    diode_count: int                # number of diodes needed
    relay_savings: int              # relays eliminated
    function_name: str              # human-readable description


def is_monotone_positive(truth_table: dict[tuple[int, ...], int],
                          var_index: int) -> bool:
    """
    Check if a function is monotone increasing in a variable.
    f(x=0) <= f(x=1) for all other variable assignments.
    """
    n = len(next(iter(truth_table.keys())))
    for bits, val in truth_table.items():
        if bits[var_index] == 0:
            # Find the corresponding row with this var = 1
            bits_1 = list(bits)
            bits_1[var_index] = 1
            val_1 = truth_table.get(tuple(bits_1), 0)
            if val > val_1:  # f(x=0) > f(x=1) means NOT monotone positive
                return False
    return True


def is_monotone_negative(truth_table: dict[tuple[int, ...], int],
                          var_index: int) -> bool:
    """
    Check if a function is monotone decreasing in a variable.
    f(x=0) >= f(x=1) for all other variable assignments.
    """
    n = len(next(iter(truth_table.keys())))
    for bits, val in truth_table.items():
        if bits[var_index] == 0:
            bits_1 = list(bits)
            bits_1[var_index] = 1
            val_1 = truth_table.get(tuple(bits_1), 0)
            if val < val_1:
                return False
    return True


def is_unate(truth_table: dict[tuple[int, ...], int],
             variables: list[str]) -> dict[str, str] | None:
    """
    Check if a function is unate (monotone in each variable).

    Returns a dict mapping variable -> polarity ("pos", "neg", "indep")
    if the function is unate, or None if it requires inversion (binate).
    """
    if not truth_table:
        return {}

    n = len(variables)
    polarities: dict[str, str] = {}

    for i, var in enumerate(variables):
        pos = is_monotone_positive(truth_table, i)
        neg = is_monotone_negative(truth_table, i)

        if pos and neg:
            polarities[var] = "indep"  # function doesn't depend on this var
        elif pos:
            polarities[var] = "pos"
        elif neg:
            polarities[var] = "neg"
        else:
            return None  # binate in this variable, needs inversion

    return polarities


def analyze_function(truth_table: dict[tuple[int, ...], int],
                      variables: list[str]) -> dict:
    """
    Analyze a Boolean function for diode implementability.

    Returns a dict with:
    - 'unate': bool - whether the function can be implemented with diodes
    - 'polarities': dict or None - variable polarities if unate
    - 'function_type': str - human-readable description
    - 'diode_circuit': list of DiodeGate if implementable
    """
    polarities = is_unate(truth_table, variables)

    if polarities is None:
        # Try to identify common binate functions
        func_type = _identify_function(truth_table, variables)
        return {
            "unate": False,
            "polarities": None,
            "function_type": func_type,
            "diode_circuit": None,
            "explanation": (
                f"Function '{func_type}' is binate (requires inversion). "
                f"Cannot be replaced with diodes alone - needs at least one relay."
            ),
        }

    # Function is unate - synthesize diode circuit
    active_vars = {v: p for v, p in polarities.items() if p != "indep"}

    if not active_vars:
        func_type = "constant"
        return {
            "unate": True,
            "polarities": polarities,
            "function_type": func_type,
            "diode_circuit": [],
            "explanation": "Constant function - no logic needed.",
        }

    # Determine if AND or OR based on function structure
    func_type, gates = _synthesize_diode_circuit(truth_table, variables, active_vars)

    diode_count = sum(len(g.inputs) for g in gates)
    return {
        "unate": True,
        "polarities": polarities,
        "function_type": func_type,
        "diode_circuit": gates,
        "diode_count": diode_count,
        "explanation": (
            f"Function '{func_type}' is monotone. "
            f"Can be implemented with {diode_count} diode(s) instead of relay(s). "
            f"Variable polarities: {active_vars}"
        ),
    }


def _identify_function(truth_table: dict[tuple[int, ...], int],
                        variables: list[str]) -> str:
    """Try to identify a common Boolean function by its truth table."""
    n = len(variables)
    outputs = tuple(truth_table[bits] for bits in sorted(truth_table.keys()))

    if n == 2:
        known = {
            (0, 0, 0, 1): "AND",
            (0, 1, 1, 1): "OR",
            (0, 1, 1, 0): "XOR",
            (1, 0, 0, 1): "XNOR",
            (1, 1, 1, 0): "NAND",
            (1, 0, 0, 0): "NOR",
        }
        return known.get(outputs, "unknown-2var")
    elif n == 3:
        # Check for majority
        if outputs == (0, 0, 0, 1, 0, 1, 1, 1):
            return "majority"
        # Check for XOR
        if outputs == (0, 1, 1, 0, 1, 0, 0, 1):
            return "3-XOR"

    return f"unknown-{n}var"


def _synthesize_diode_circuit(
    truth_table: dict[tuple[int, ...], int],
    variables: list[str],
    active_vars: dict[str, str],
) -> tuple[str, list[DiodeGate]]:
    """
    Synthesize a diode AND/OR circuit for a unate function.

    Uses the fact that any unate function can be expressed as
    a sum of products (OR of ANDs) using only positive/negative literals.
    """
    n = len(variables)

    # Find minterms (input combos where output = 1)
    minterms = [bits for bits, val in sorted(truth_table.items()) if val == 1]

    if not minterms:
        return "constant-0", []

    all_ones = all(v == 1 for v in truth_table.values())
    if all_ones:
        return "constant-1", []

    # Simple cases
    pos_vars = [v for v, p in active_vars.items() if p == "pos"]
    neg_vars = [v for v, p in active_vars.items() if p == "neg"]

    # Check for pure AND: output=1 only when all active vars are in correct polarity
    if len(minterms) == 1:
        # Single minterm - pure AND
        inputs = []
        for v in pos_vars:
            inputs.append(v)
        for v in neg_vars:
            inputs.append(f"~{v}")
        gate = DiodeGate(gate_type="AND", inputs=inputs, output="Y")
        return "AND", [gate]

    # Check for pure OR: output=0 only when all active vars are in wrong polarity
    maxterms = [bits for bits, val in sorted(truth_table.items()) if val == 0]
    if len(maxterms) == 1:
        inputs = []
        for v in pos_vars:
            inputs.append(v)
        for v in neg_vars:
            inputs.append(f"~{v}")
        gate = DiodeGate(gate_type="OR", inputs=inputs, output="Y")
        return "OR", [gate]

    # General case: sum of products
    # Each minterm becomes an AND gate, then OR them together
    and_gates = []
    for mi, bits in enumerate(minterms):
        inputs = []
        for j, v in enumerate(variables):
            if v in active_vars:
                if active_vars[v] == "pos" and bits[j] == 1:
                    inputs.append(v)
                elif active_vars[v] == "neg" and bits[j] == 0:
                    inputs.append(f"~{v}")
        if inputs:
            and_gate = DiodeGate(
                gate_type="AND", inputs=inputs,
                output=f"_and_{mi}")
            and_gates.append(and_gate)

    if len(and_gates) == 1:
        and_gates[0].output = "Y"
        return "AND", and_gates

    or_gate = DiodeGate(
        gate_type="OR",
        inputs=[g.output for g in and_gates],
        output="Y")
    return "AND-OR", and_gates + [or_gate]


def suggest_optimizations(
    truth_tables: dict[str, dict],
    variables: list[str],
) -> list[str]:
    """
    Analyze multiple functions and suggest which can use diodes.

    Returns human-readable suggestions.
    """
    suggestions = []
    for name, tt in truth_tables.items():
        result = analyze_function(tt, variables)
        if result["unate"]:
            suggestions.append(
                f"  {name}: {result['explanation']}")
        else:
            suggestions.append(
                f"  {name}: RELAY REQUIRED - {result['explanation']}")
    return suggestions
