"""Test bus ports and bus-to-port binding."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.elaborate import elaborate, load_flat_into_engine
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState


class TestBusPortParsing:
    def test_parse_bus_port(self):
        program = parse("""
            component Adder {
                port in A[4];
                port out S[4];
            }
        """)
        comp = program.items[0]
        port_decl = comp.members[0]
        # Should expand to A[0], A[1], A[2], A[3]
        assert port_decl.names == ["A[0]", "A[1]", "A[2]", "A[3]"]
        assert port_decl.port_defs[0].name == "A"
        assert port_decl.port_defs[0].width == 4

    def test_parse_mixed_ports(self):
        program = parse("""
            component Mixed {
                port in A[4], Cin;
                port out S[4], Cout;
            }
        """)
        comp = program.items[0]
        in_decl = comp.members[0]
        out_decl = comp.members[1]
        assert in_decl.names == ["A[0]", "A[1]", "A[2]", "A[3]", "Cin"]
        assert out_decl.names == ["S[0]", "S[1]", "S[2]", "S[3]", "Cout"]

    def test_parse_bus_slice(self):
        """Parse a net reference with range slice."""
        program = parse("""
            component Top {
                bus data[8];
                port in X;
                connect X -> data[0];
                connect X -> data[3];
            }
        """)
        # Should parse without error
        assert program.items[0].name == "Top"

    def test_parse_instance_with_slice(self):
        program = parse("""
            component Inner {
                port in A[4];
                port out Y;
            }
            component Outer {
                bus data[8];
                port out Y;
                instance sub = Inner(A=data[0..3], Y=Y);
            }
        """)
        comp = [c for c in program.items if c.name == "Outer"][0]
        inst = comp.members[2]  # instance statement
        assert inst.args[0].name == "A"
        assert inst.args[0].value.is_slice
        assert inst.args[0].value.index == 0
        assert inst.args[0].value.end_index == 3


class TestBusElaboration:
    def test_bus_port_binding_with_slice(self):
        """Test bus port bound via slice: A=data[0..3]"""
        program = parse("""
            component Nibble {
                port in D[4];
                port out Y;
                wire vcc = HIGH;
                relay R1;
                connect D[0] -> R1.coil;
                connect vcc -> R1.c1.no;
                connect R1.c1.common -> Y;
            }
            component Top {
                bus data[8];
                port out Y;
                instance nib = Nibble(D=data[0..3], Y=Y);
            }
        """)
        flat = elaborate(program, "Top")

        # Check that nib.D[0] is aliased to data[0]
        aliases_set = set()
        for a, b in flat.aliases:
            aliases_set.add((a, b))
            aliases_set.add((b, a))

        assert any("data[0]" in a and "nib.D[0]" in b
                    for a, b in aliases_set), f"Aliases: {flat.aliases}"

    def test_bus_port_simulation(self):
        """Simulate a component with bus port binding."""
        program = parse("""
            component Detector {
                port in D[4];
                port out AllHigh;
                wire vcc = HIGH;
                wire gnd = LOW;

                # AllHigh = D[0] (simplified - just check bit 0)
                relay R1;
                connect D[0] -> R1.coil;
                connect gnd -> R1.c1.nc;
                connect vcc -> R1.c1.no;
                connect R1.c1.common -> AllHigh;
            }
            component Top {
                bus input[4];
                port out Result;
                instance det = Detector(D=input[0..3], AllHigh=Result);
            }
        """)
        flat = elaborate(program, "Top")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # Drive input[0] high
        engine.drive("input[0]", WireState.HIGH)
        assert engine.read("Result") == WireState.HIGH

        engine.drive("input[0]", WireState.LOW)
        assert engine.read("Result") == WireState.LOW

    def test_bus_to_bus_shorthand(self):
        """Test bus=bus binding where both are same width."""
        program = parse("""
            component Inner {
                port in D[4];
                port out Q[4];
                connect D[0] -> Q[0];
                connect D[1] -> Q[1];
                connect D[2] -> Q[2];
                connect D[3] -> Q[3];
            }
            component Outer {
                port in X[4];
                port out Y[4];
                instance pass = Inner(D=X, Q=Y);
            }
        """)
        flat = elaborate(program, "Outer")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # Drive X[0..3] and check Y[0..3]
        for i in range(4):
            engine.drive(f"X[{i}]", WireState.HIGH if i % 2 == 0 else WireState.LOW)

        for i in range(4):
            expected = WireState.HIGH if i % 2 == 0 else WireState.LOW
            actual = engine.read(f"Y[{i}]")
            assert actual == expected, f"Y[{i}] expected {expected} got {actual}"

    def test_slice_to_scalar_ports(self):
        """Test binding a bus slice to individually-named ports (A0, A1...)."""
        program = parse("""
            component Adder {
                port in A0, A1, A2, A3;
                port out Sum;
                wire vcc = HIGH;
                wire gnd = LOW;
                # Just check A0 for simplicity
                relay R1;
                connect A0 -> R1.coil;
                connect gnd -> R1.c1.nc;
                connect vcc -> R1.c1.no;
                connect R1.c1.common -> Sum;
            }
            component Top {
                bus data[4];
                port out Y;
                instance add = Adder(A=data[0..3], Sum=Y);
            }
        """)
        flat = elaborate(program, "Top")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        # data[0] -> A0 -> controls relay -> Sum
        engine.drive("data[0]", WireState.HIGH)
        assert engine.read("Y") == WireState.HIGH

        engine.drive("data[0]", WireState.LOW)
        assert engine.read("Y") == WireState.LOW


class TestBusAdder:
    """Test a 4-bit adder using bus ports."""

    def test_bus_port_adder(self):
        """Build a 4-bit adder with bus ports and test it."""
        program = parse("""
            component FullAdd {
                port in A, B, Cin, CinNeg;
                port out Cout, CoutNeg;
                wire vcc = HIGH;
                wire gnd = LOW;
                relay(4) R1, R2;
                connect A -> R1.coil;
                connect gnd -> R1.c1.nc;
                connect Cin -> R1.c1.no;
                connect Cin -> R1.c2.nc;
                connect vcc -> R1.c2.no;
                connect vcc -> R1.c3.nc;
                connect CinNeg -> R1.c3.no;
                connect CinNeg -> R1.c4.nc;
                connect gnd -> R1.c4.no;
                connect B -> R2.coil;
                connect R1.c1.common -> R2.c1.nc;
                connect R1.c2.common -> R2.c1.no;
                connect R2.c1.common -> Cout;
                connect R1.c3.common -> R2.c2.nc;
                connect R1.c4.common -> R2.c2.no;
                connect R2.c2.common -> CoutNeg;
            }

            component Adder4Bus {
                port in A[4], B[4];
                port in Cin, CinNeg;
                port out Cout, CoutNeg;

                wire c0, c0n, c1, c1n, c2, c2n;

                instance a0 = FullAdd(A=A[0], B=B[0],
                    Cin=Cin, CinNeg=CinNeg, Cout=c0, CoutNeg=c0n);
                instance a1 = FullAdd(A=A[1], B=B[1],
                    Cin=c0, CinNeg=c0n, Cout=c1, CoutNeg=c1n);
                instance a2 = FullAdd(A=A[2], B=B[2],
                    Cin=c1, CinNeg=c1n, Cout=c2, CoutNeg=c2n);
                instance a3 = FullAdd(A=A[3], B=B[3],
                    Cin=c2, CinNeg=c2n, Cout=Cout, CoutNeg=CoutNeg);
            }

            component Top {
                bus x[4], y[4];
                port in Cin, CinNeg;
                port out Cout, CoutNeg;
                instance add = Adder4Bus(
                    A=x[0..3], B=y[0..3],
                    Cin=Cin, CinNeg=CinNeg,
                    Cout=Cout, CoutNeg=CoutNeg
                );
            }
        """)

        flat = elaborate(program, "Top")

        # Test 5 + 3 = 8
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        a, b = 5, 3
        for i in range(4):
            engine.drive(f"x[{i}]", WireState.HIGH if (a >> i) & 1 else WireState.LOW)
            engine.drive(f"y[{i}]", WireState.HIGH if (b >> i) & 1 else WireState.LOW)
        engine.drive("Cin", WireState.LOW)
        engine.drive("CinNeg", WireState.HIGH)

        cout = 1 if engine.read("Cout") == WireState.HIGH else 0
        expected_cout = 1 if (a + b) >= 16 else 0
        assert cout == expected_cout, f"{a}+{b}: Cout={cout} expected {expected_cout}"

        # Test 15 + 1 = 16 (carry out)
        engine2 = SimEngine()
        load_flat_into_engine(flat, engine2)
        a, b = 15, 1
        for i in range(4):
            engine2.drive(f"x[{i}]", WireState.HIGH if (a >> i) & 1 else WireState.LOW)
            engine2.drive(f"y[{i}]", WireState.HIGH if (b >> i) & 1 else WireState.LOW)
        engine2.drive("Cin", WireState.LOW)
        engine2.drive("CinNeg", WireState.HIGH)

        cout = 1 if engine2.read("Cout") == WireState.HIGH else 0
        assert cout == 1, f"15+1: Cout={cout} expected 1"
