"""Test the Shannon expansion synthesizer.

The ultimate test: give it the carry function (majority),
and see if it discovers the Zuse adder wiring.
"""
import pytest
from relaydsl.synth.synthesize import (
    TruthTable, expand, synthesize, generate_circuit,
    synthesize_and_generate, Leaf, MuxNode,
)


class TestTruthTable:
    def test_majority(self):
        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )
        assert tt.rows[(0, 0, 0)] == 0
        assert tt.rows[(1, 1, 0)] == 1
        assert tt.rows[(1, 0, 1)] == 1
        assert tt.rows[(1, 1, 1)] == 1

    def test_cofactor(self):
        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )
        # Cofactor A=0: majority(0, B, Cin) = B & Cin
        c0 = tt.cofactor("A", 0)
        assert c0.variables == ["B", "Cin"]
        assert c0.rows[(0, 0)] == 0
        assert c0.rows[(0, 1)] == 0
        assert c0.rows[(1, 0)] == 0
        assert c0.rows[(1, 1)] == 1

        # Cofactor A=1: majority(1, B, Cin) = B | Cin
        c1 = tt.cofactor("A", 1)
        assert c1.rows[(0, 0)] == 0
        assert c1.rows[(0, 1)] == 1
        assert c1.rows[(1, 0)] == 1
        assert c1.rows[(1, 1)] == 1

    def test_constant_detection(self):
        tt = TruthTable(variables=["X"], rows={(0,): 1, (1,): 1})
        assert tt.is_constant() == 1

    def test_variable_detection(self):
        tt = TruthTable(variables=["X"], rows={(0,): 0, (1,): 1})
        assert tt.is_single_variable() == "X"

    def test_complement_detection(self):
        tt = TruthTable(variables=["X"], rows={(0,): 1, (1,): 0})
        assert tt.is_complement() == "X"


class TestShannonExpansion:
    def test_expand_constant(self):
        tt = TruthTable(variables=["X"], rows={(0,): 1, (1,): 1})
        result = expand(tt, ["X"])
        assert isinstance(result, Leaf)
        assert result.value == "1"

    def test_expand_identity(self):
        tt = TruthTable(variables=["X"], rows={(0,): 0, (1,): 1})
        result = expand(tt, ["X"])
        assert isinstance(result, Leaf)
        assert result.value == "X"

    def test_expand_and(self):
        """A AND B should expand to: A ? B : 0"""
        tt = TruthTable.from_function(["A", "B"], lambda A, B: A & B)
        result = expand(tt, ["A", "B"])
        assert isinstance(result, MuxNode)
        assert result.select == "A"
        # NC (A=0): constant 0
        assert isinstance(result.nc, Leaf) and result.nc.value == "0"
        # NO (A=1): B
        assert isinstance(result.no, Leaf) and result.no.value == "B"

    def test_expand_or(self):
        """A OR B should expand to: A ? 1 : B"""
        tt = TruthTable.from_function(["A", "B"], lambda A, B: A | B)
        result = expand(tt, ["A", "B"])
        assert isinstance(result, MuxNode)
        assert result.select == "A"
        assert isinstance(result.nc, Leaf) and result.nc.value == "B"
        assert isinstance(result.no, Leaf) and result.no.value == "1"

    def test_expand_xor(self):
        """A XOR B should expand to: A ? ~B : B"""
        tt = TruthTable.from_function(["A", "B"], lambda A, B: A ^ B)
        result = expand(tt, ["A", "B"])
        assert isinstance(result, MuxNode)
        assert result.select == "A"
        # NC (A=0): B
        assert isinstance(result.nc, Leaf) and result.nc.value == "B"
        # NO (A=1): ~B
        assert isinstance(result.no, Leaf) and result.no.value == "B" and result.no.negated

    def test_expand_majority(self):
        """majority(A, B, Cin) - the carry function.

        Expanded as A first, then B:
          A=0: B & Cin = B ? Cin : 0
          A=1: B | Cin = B ? 1 : Cin

        So the tree should be:
          Mux(A:
            NC=Mux(B: NC=0, NO=Cin)      <- A=0: B ? Cin : 0
            NO=Mux(B: NC=Cin, NO=1))      <- A=1: B ? 1 : Cin
        """
        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )
        result = expand(tt, ["A", "B", "Cin"])

        assert isinstance(result, MuxNode)
        assert result.select == "A"

        # A=0 branch: B ? Cin : 0
        nc = result.nc
        assert isinstance(nc, MuxNode)
        assert nc.select == "B"
        assert isinstance(nc.nc, Leaf) and nc.nc.value == "0"
        assert isinstance(nc.no, Leaf) and nc.no.value == "Cin"

        # A=1 branch: B ? 1 : Cin
        no = result.no
        assert isinstance(no, MuxNode)
        assert no.select == "B"
        assert isinstance(no.nc, Leaf) and no.nc.value == "Cin"
        assert isinstance(no.no, Leaf) and no.no.value == "1"

        # This IS the Zuse adder wiring!
        print("\n=== Majority (Carry) Shannon Expansion ===")
        print(f"Tree: {result}")
        print(f"Relay coils: {result.relay_coils()}")
        print(f"Relay count: {result.relay_count()}")
        print(f"Contact count: {result.contact_count()}")


class TestSynthesizer:
    """Test the full synthesis pipeline."""

    def test_synthesize_majority(self):
        """Synthesize the carry function and verify minimum relay count."""
        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )
        result = synthesize({"CarryOut": tt})

        # Should find a 2-relay solution
        assert result.relay_count == 2
        print(f"\nBest variable order: {result.var_order}")
        print(f"Relay count: {result.relay_count}")
        print(f"Contact count: {result.contact_count}")

    def test_synthesize_carry_with_complement(self):
        """Synthesize both CarryOut and CarryOutNeg."""
        carry = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )
        carry_neg = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: not ((A & B) | (A & Cin) | (B & Cin)),
        )
        result = synthesize(
            {"CarryOut": carry, "CarryOutNeg": carry_neg},
            complementary_inputs={"Cin": "CinNeg"},
        )

        # Both outputs should share the same 2 relay coils
        assert result.relay_count == 2
        coils = result.relay_coils()
        print(f"\nDual-output synthesis:")
        print(f"Relay coils: {coils}")
        print(f"Contact count: {result.contact_count}")
        for name, tree in result.outputs.items():
            print(f"  {name}: {tree}")

    def test_generate_circuit_majority(self):
        """Generate a full relay circuit for the carry function."""
        circuit, source = synthesize_and_generate(
            functions={
                "CarryOut": lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
            },
            variables=["A", "B", "Cin"],
            component_name="SynthCarry",
        )

        print(f"\n=== Synthesized Carry Circuit ===")
        print(circuit.summary())
        print(f"\n{source}")

        assert circuit.relays  # should have relays
        assert len(circuit.relays) == 2

    def test_generate_full_zuse_adder(self):
        """THE BIG TEST: synthesize both carry outputs and generate DSL code."""
        circuit, source = synthesize_and_generate(
            functions={
                "CarryOut": lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
                "CarryOutNeg": lambda A, B, Cin: not ((A & B) | (A & Cin) | (B & Cin)),
            },
            variables=["A", "B", "Cin"],
            complementary_inputs={"Cin": "CinNeg"},
            component_name="ZuseAdderSynthesized",
        )

        print(f"\n{'='*60}")
        print(f"SYNTHESIZED ZUSE ADDER")
        print(f"{'='*60}")
        print(circuit.summary())
        print(f"\nGenerated DSL:")
        print(source)
        print(f"{'='*60}")

        # Verify: 2 relays, shared coils
        assert len(circuit.relays) == 2

        # Verify correctness by simulating
        from relaydsl.sim.engine import SimEngine
        from relaydsl.sim.nets import WireState

        engine = SimEngine()
        # Manually build the synthesized circuit in the engine
        for relay_name in circuit.relays:
            num_contacts = len(circuit.relays[relay_name])
            engine._create_relay(relay_name, num_contacts=num_contacts)
            engine.connections.append((relay_name, f"{relay_name}.coil"))

        # Create all nets
        for name in circuit.inputs + circuit.outputs + circuit.internal_nets:
            engine.get_or_create_net(name)

        # Wire constants
        engine.get_or_create_net("vcc").drive("const:vcc", WireState.HIGH)
        engine.get_or_create_net("gnd").drive("const:gnd", WireState.LOW)

        # Wire contacts
        for relay_name, contacts in circuit.relays.items():
            for ca in contacts:
                engine.connections.append((ca.nc, f"{relay_name}.c{ca.contact_num}.nc"))
                engine.connections.append((ca.no, f"{relay_name}.c{ca.contact_num}.no"))
                engine.connections.append((f"{relay_name}.c{ca.contact_num}.common", ca.common))

        # Test all 8 input combinations
        test_cases = [
            (0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (1, 1, 0, 1),
            (0, 0, 1, 0), (1, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1),
        ]
        for a, b, cin, expected in test_cases:
            engine2 = SimEngine()
            for rn in circuit.relays:
                nc = len(circuit.relays[rn])
                engine2._create_relay(rn, num_contacts=nc)
                engine2.connections.append((rn, f"{rn}.coil"))
            for name in circuit.inputs + circuit.outputs + circuit.internal_nets:
                engine2.get_or_create_net(name)
            engine2.get_or_create_net("vcc").drive("const:vcc", WireState.HIGH)
            engine2.get_or_create_net("gnd").drive("const:gnd", WireState.LOW)
            for rn, contacts in circuit.relays.items():
                for ca in contacts:
                    engine2.connections.append((ca.nc, f"{rn}.c{ca.contact_num}.nc"))
                    engine2.connections.append((ca.no, f"{rn}.c{ca.contact_num}.no"))
                    engine2.connections.append((f"{rn}.c{ca.contact_num}.common", ca.common))

            engine2.drive("A", WireState.HIGH if a else WireState.LOW)
            engine2.drive("B", WireState.HIGH if b else WireState.LOW)
            engine2.drive("Cin", WireState.HIGH if cin else WireState.LOW)
            engine2.drive("CinNeg", WireState.LOW if cin else WireState.HIGH)

            cout = engine2.read("CarryOut")
            cout_neg = engine2.read("CarryOutNeg")
            expected_state = WireState.HIGH if expected else WireState.LOW
            expected_neg = WireState.LOW if expected else WireState.HIGH

            assert cout == expected_state, (
                f"A={a} B={b} Cin={cin}: CarryOut expected {expected_state} got {cout}"
            )
            assert cout_neg == expected_neg, (
                f"A={a} B={b} Cin={cin}: CarryOutNeg expected {expected_neg} got {cout_neg}"
            )

        print("\nAll 8 test vectors PASSED!")


class TestAlternativeCircuits:
    """Explore: are there other clever circuits besides the Zuse wiring?"""

    def test_all_orderings_majority(self):
        """Try all variable orderings and see what circuits emerge."""
        from itertools import permutations

        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin),
        )

        print("\n=== All possible 2-relay majority circuits ===")
        seen = set()
        for perm in permutations(["A", "B", "Cin"]):
            tree = expand(tt, list(perm))
            sig = repr(tree)
            if sig not in seen:
                seen.add(sig)
                print(f"\nOrder {perm}:")
                print(f"  {tree}")
                if isinstance(tree, MuxNode):
                    # Show the leaf (data) inputs
                    _print_leaves(tree, indent="  ")

    def test_sum_function(self):
        """Synthesize XOR (sum) and see how many relays it needs."""
        tt = TruthTable.from_function(
            ["A", "B", "Cin"],
            lambda A, B, Cin: A ^ B ^ Cin,
        )
        result = synthesize({"Sum": tt}, complementary_inputs={"Cin": "CinNeg"})
        print(f"\n=== Sum (3-input XOR) ===")
        print(f"Relay count: {result.relay_count}")
        print(f"Contact count: {result.contact_count}")
        for name, tree in result.outputs.items():
            print(f"  {name}: {tree}")

    def test_full_adder_all_outputs(self):
        """Synthesize Sum + CarryOut + CarryOutNeg together."""
        result = synthesize(
            {
                "Sum": TruthTable.from_function(
                    ["A", "B", "Cin"], lambda A, B, Cin: A ^ B ^ Cin),
                "CarryOut": TruthTable.from_function(
                    ["A", "B", "Cin"],
                    lambda A, B, Cin: (A & B) | (A & Cin) | (B & Cin)),
                "CarryOutNeg": TruthTable.from_function(
                    ["A", "B", "Cin"],
                    lambda A, B, Cin: not ((A & B) | (A & Cin) | (B & Cin))),
            },
            complementary_inputs={"Cin": "CinNeg"},
        )
        print(f"\n=== Full Adder (Sum + Carry + CarryNeg) ===")
        print(f"Relay count: {result.relay_count}")
        print(f"Contact count: {result.contact_count}")
        print(f"Variable order: {result.var_order}")
        for name, tree in result.outputs.items():
            print(f"  {name}: {tree}")


def _print_leaves(node, indent=""):
    """Helper to print the leaf values of a mux tree."""
    if isinstance(node, Leaf):
        print(f"{indent}-> {node}")
    elif isinstance(node, MuxNode):
        print(f"{indent}{node.select}=0:")
        _print_leaves(node.nc, indent + "  ")
        print(f"{indent}{node.select}=1:")
        _print_leaves(node.no, indent + "  ")
