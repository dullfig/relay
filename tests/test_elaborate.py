"""Test instance elaboration - flattening hierarchical designs."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.elaborate import Elaborator, elaborate, load_flat_into_engine, FlatNetlist
from relaydsl.lang.ast_nodes import Component
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState


class TestBasicElaboration:
    def test_flat_component_no_instances(self):
        """A component with no instances should elaborate trivially."""
        program = parse("""
            component Simple {
                port in A, B;
                port out Y;
                wire mid;
                relay R1;
                connect A -> R1.coil;
                connect B -> R1.c1.nc;
                connect mid -> R1.c1.no;
                connect R1.c1.common -> Y;
            }
        """)
        flat = elaborate(program, "Simple")
        assert "A" in flat.nets
        assert "B" in flat.nets
        assert "Y" in flat.nets
        assert "R1" in flat.relays
        assert flat.relays["R1"].poles == 2
        assert len(flat.connections) == 4

    def test_single_instance(self):
        """Test elaborating a component with one sub-instance."""
        program = parse("""
            component Inner {
                port in X;
                port out Y;
                relay R1;
                connect X -> R1.coil;
                connect X -> R1.c1.nc;
                connect R1.c1.common -> Y;
            }

            component Outer {
                port in A;
                port out B;
                instance sub = Inner(X=A, Y=B);
            }
        """)
        flat = elaborate(program, "Outer")

        # Inner's relay should be prefixed
        assert "sub.R1" in flat.relays
        # Inner's ports should be aliased to outer nets
        assert any(("A" in a and "sub.X" in b) or ("A" in b and "sub.X" in a)
                    for a, b in flat.aliases)

    def test_prefixed_nets(self):
        """All internal nets of instances should be prefixed."""
        program = parse("""
            component Cell {
                port in D;
                port out Q;
                wire internal;
                relay R1;
                connect D -> R1.coil;
                connect internal -> R1.c1.nc;
                connect R1.c1.common -> Q;
            }

            component Top {
                port in X;
                port out Y;
                instance c0 = Cell(D=X, Q=Y);
            }
        """)
        flat = elaborate(program, "Top")

        assert "c0.internal" in flat.nets
        assert "c0.R1" in flat.relays
        assert "c0.R1.coil" in flat.nets
        assert "c0.R1.c1.common" in flat.nets

    def test_multiple_instances(self):
        """Test two instances of the same component."""
        program = parse("""
            component Inv {
                port in A;
                port out Y;
                relay R1;
                connect A -> R1.coil;
            }

            component Top {
                port in X1, X2;
                port out Y1, Y2;
                instance inv1 = Inv(A=X1, Y=Y1);
                instance inv2 = Inv(A=X2, Y=Y2);
            }
        """)
        flat = elaborate(program, "Top")

        assert "inv1.R1" in flat.relays
        assert "inv2.R1" in flat.relays
        # Two separate relays
        assert flat.relays["inv1.R1"].coil_net == "inv1.R1.coil"
        assert flat.relays["inv2.R1"].coil_net == "inv2.R1.coil"


class TestElaborateAndSimulate:
    """Test that elaborated circuits simulate correctly."""

    def test_simple_relay_through_elaboration(self):
        """A relay circuit should work the same whether loaded directly or elaborated."""
        program = parse("""
            component Mux {
                port in Sel, D0, D1;
                port out Y;
                relay R1;
                connect Sel -> R1.coil;
                connect D0 -> R1.c1.nc;
                connect D1 -> R1.c1.no;
                connect R1.c1.common -> Y;
            }
        """)
        flat = elaborate(program, "Mux")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # Sel=0: Y should follow D0
        engine.drive("Sel", WireState.LOW)
        engine.drive("D0", WireState.HIGH)
        engine.drive("D1", WireState.LOW)
        assert engine.read("Y") == WireState.HIGH

        # Sel=1: Y should follow D1
        engine.drive("Sel", WireState.HIGH)
        assert engine.read("Y") == WireState.LOW

    def test_chained_instances(self):
        """Two inverters chained: NOT(NOT(X)) = X."""
        program = parse("""
            component Buf {
                port in A;
                port out Y;
                wire vcc = HIGH;
                wire gnd = LOW;
                relay R1;
                connect A -> R1.coil;
                connect gnd -> R1.c1.nc;
                connect vcc -> R1.c1.no;
                connect R1.c1.common -> Y;
            }

            component DoubleBuf {
                port in X;
                port out Z;
                wire mid;
                instance b1 = Buf(A=X, Y=mid);
                instance b2 = Buf(A=mid, Y=Z);
            }
        """)
        flat = elaborate(program, "DoubleBuf")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # Double buffer: X=1 -> mid=1 -> Z=1
        engine.drive("X", WireState.HIGH)
        assert engine.read("Z") == WireState.HIGH

        engine.drive("X", WireState.LOW)
        assert engine.read("Z") == WireState.LOW


class TestZuseAdderElaboration:
    """Test elaborating the Zuse adder from the example file."""

    def _load_zuse_program(self):
        import os
        filepath = os.path.join(os.path.dirname(__file__),
                                "..", "examples", "zuse_adder.relay")
        with open(filepath) as f:
            source = f.read()
        return parse(source, filepath)

    def test_elaborate_single_adder(self):
        program = self._load_zuse_program()
        flat = elaborate(program, "ZuseAdder")

        assert len(flat.relays) == 2
        assert "R1" in flat.relays
        assert "R2" in flat.relays
        assert flat.relays["R1"].poles == 4

    def test_simulate_elaborated_adder(self):
        """Simulate the Zuse adder through the elaboration path."""
        program = self._load_zuse_program()
        flat = elaborate(program, "ZuseAdder")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # Test all 8 cases
        cases = [
            (0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (1, 1, 0, 1),
            (0, 0, 1, 0), (1, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1),
        ]
        for a, b, cin, expected_cout in cases:
            eng = SimEngine()
            load_flat_into_engine(flat, eng)
            eng.drive("A", WireState.HIGH if a else WireState.LOW)
            eng.drive("B", WireState.HIGH if b else WireState.LOW)
            eng.drive("CarryIn", WireState.HIGH if cin else WireState.LOW)
            eng.drive("CarryInNeg", WireState.LOW if cin else WireState.HIGH)

            cout = eng.read("CarryOut")
            expected = WireState.HIGH if expected_cout else WireState.LOW
            assert cout == expected, (
                f"A={a} B={b} Cin={cin}: CarryOut expected {expected} got {cout}")


class TestFourBitAdder:
    """THE BIG TEST: 4-bit adder from chained Zuse adders."""

    def _build_4bit_program(self):
        """Build a program with ZuseAdder + FourBitAdder."""
        import os
        zuse_path = os.path.join(os.path.dirname(__file__),
                                  "..", "examples", "zuse_adder.relay")
        four_path = os.path.join(os.path.dirname(__file__),
                                  "..", "examples", "four_bit_adder.relay")

        with open(zuse_path) as f:
            zuse_src = f.read()
        with open(four_path) as f:
            four_src = f.read()

        # Strip the import and testbench from four_bit_adder, combine sources
        four_lines = []
        for line in four_src.split("\n"):
            if line.strip().startswith("import"):
                continue
            four_lines.append(line)
        four_clean = "\n".join(four_lines)

        # Parse combined source (ZuseAdder first, then FourBitAdder)
        # Only take the component definition from zuse, not its testbench
        combined = zuse_src + "\n" + four_clean
        return parse(combined, "<combined>")

    def test_elaborate_4bit(self):
        """Test that the 4-bit adder elaborates with correct structure."""
        program = self._build_4bit_program()
        flat = elaborate(program, "FourBitAdder")

        print(f"\n{flat.summary()}")

        # Should have 4 instances * 2 relays = 8 relays
        assert len(flat.relays) == 8, (
            f"Expected 8 relays, got {len(flat.relays)}: "
            f"{sorted(flat.relays.keys())}")

        # Check that all relay names are properly prefixed
        for name in flat.relays:
            assert name.startswith("add"), f"Unexpected relay name: {name}"

    def test_4bit_addition(self):
        """Test actual 4-bit addition through elaboration + simulation."""
        program = self._build_4bit_program()
        flat = elaborate(program, "FourBitAdder")

        def add_4bit(a: int, b: int, cin: int = 0) -> tuple[int, int]:
            """Simulate 4-bit addition, return (sum, carry_out)."""
            engine = SimEngine()
            load_flat_into_engine(flat, engine)

            # Drive inputs
            for i in range(4):
                engine.drive(f"A{i}", WireState.HIGH if (a >> i) & 1 else WireState.LOW)
                engine.drive(f"B{i}", WireState.HIGH if (b >> i) & 1 else WireState.LOW)
            engine.drive("Cin", WireState.HIGH if cin else WireState.LOW)
            engine.drive("CinNeg", WireState.LOW if cin else WireState.HIGH)

            # Read carry out
            cout = 1 if engine.read("Cout") == WireState.HIGH else 0
            return cout

        # Test a selection of additions
        test_cases = [
            (0, 0, 0, 0),    # 0+0=0, carry=0
            (1, 1, 0, 0),    # 1+1=2, carry=0
            (5, 3, 0, 0),    # 5+3=8=01000, carry=0
            (15, 1, 0, 1),   # 15+1=16=10000, carry=1
            (15, 15, 0, 1),  # 15+15=30=11110, carry=1
            (7, 7, 0, 0),    # 7+7=14=01110, carry=0
            (8, 8, 0, 1),    # 8+8=16=10000, carry=1
            (0, 0, 1, 0),    # 0+0+1=1, carry=0
            (15, 0, 1, 1),   # 15+0+1=16, carry=1
        ]

        print("\n=== 4-Bit Adder Test Results ===")
        all_passed = True
        for a, b, cin, expected_cout in test_cases:
            actual_cout = add_4bit(a, b, cin)
            status = "OK" if actual_cout == expected_cout else "FAIL"
            if actual_cout != expected_cout:
                all_passed = False
            expected_sum = a + b + cin
            print(f"  {a:2d} + {b:2d} + {cin} = {expected_sum:2d} "
                  f"(Cout={actual_cout}, expected={expected_cout}) [{status}]")

        assert all_passed, "Some 4-bit additions failed!"

    def test_exhaustive_4bit(self):
        """Test ALL 256 possible 4-bit additions (no carry in)."""
        program = self._build_4bit_program()
        flat = elaborate(program, "FourBitAdder")

        failures = []
        for a in range(16):
            for b in range(16):
                engine = SimEngine()
                load_flat_into_engine(flat, engine)

                for i in range(4):
                    engine.drive(f"A{i}", WireState.HIGH if (a >> i) & 1 else WireState.LOW)
                    engine.drive(f"B{i}", WireState.HIGH if (b >> i) & 1 else WireState.LOW)
                engine.drive("Cin", WireState.LOW)
                engine.drive("CinNeg", WireState.HIGH)

                actual_cout = 1 if engine.read("Cout") == WireState.HIGH else 0
                expected_cout = 1 if (a + b) >= 16 else 0

                if actual_cout != expected_cout:
                    failures.append(
                        f"{a}+{b}={a+b}: Cout={actual_cout} expected={expected_cout}")

        if failures:
            print(f"\nFailed {len(failures)} of 256:")
            for f in failures[:10]:
                print(f"  {f}")
        assert not failures, f"{len(failures)} failures"
        print(f"\nAll 256 additions passed!")
