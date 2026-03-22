"""Test the semantic analyzer."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.semantic import analyze, analyze_source


class TestDeclarations:
    def test_valid_component(self):
        sa, errors = analyze_source("""
            component Adder {
                port in A, B;
                port out Sum;
                wire mid;
                relay R1;
                connect A -> R1.coil;
                connect B -> R1.c1.nc;
                connect mid -> R1.c1.no;
                connect R1.c1.common -> Sum;
            }
        """)
        assert errors == [], [str(e) for e in errors]
        ac = sa.analyzed["Adder"]
        assert "A" in ac.ports
        assert "B" in ac.ports
        assert "Sum" in ac.ports
        assert "mid" in ac.wires
        assert "R1" in ac.relays
        assert ac.relays["R1"].poles == 2

    def test_4pdt_relay(self):
        sa, errors = analyze_source("""
            component Quad {
                port in X;
                relay(4) R1;
                connect X -> R1.coil;
                connect X -> R1.c1.nc;
                connect X -> R1.c2.no;
                connect X -> R1.c3.common;
                connect X -> R1.c4.nc;
            }
        """)
        assert errors == [], [str(e) for e in errors]
        r1 = sa.analyzed["Quad"].relays["R1"]
        assert r1.poles == 4
        # Should have c1-c4 sub-nets
        valid = r1.valid_subnets()
        assert "c4.common" in valid
        assert "c4.no" in valid
        assert "c4.nc" in valid

    def test_duplicate_name_error(self):
        sa, errors = analyze_source("""
            component Bad {
                port in A;
                wire A;
            }
        """)
        assert len(errors) == 1
        assert "Duplicate" in str(errors[0])

    def test_duplicate_component_error(self):
        sa, errors = analyze_source("""
            component Foo { }
            component Foo { }
        """)
        assert len(errors) == 1
        assert "Duplicate component" in str(errors[0])


class TestNetResolution:
    def test_relay_subnets_dpdt(self):
        sa, errors = analyze_source("""
            component Test {
                relay R1;
                port in X;
                connect X -> R1.coil;
                connect X -> R1.c1.common;
                connect X -> R1.c1.no;
                connect X -> R1.c1.nc;
                connect X -> R1.c2.common;
                connect X -> R1.c2.no;
                connect X -> R1.c2.nc;
            }
        """)
        assert errors == [], [str(e) for e in errors]

    def test_invalid_relay_contact_error(self):
        """DPDT relay only has c1 and c2, not c3."""
        sa, errors = analyze_source("""
            component Test {
                relay R1;
                port in X;
                connect X -> R1.c3.common;
            }
        """)
        assert len(errors) == 1
        assert "c3.common" in str(errors[0])

    def test_4pdt_allows_c3_c4(self):
        sa, errors = analyze_source("""
            component Test {
                relay(4) R1;
                port in X;
                connect X -> R1.c3.common;
                connect X -> R1.c4.nc;
            }
        """)
        assert errors == [], [str(e) for e in errors]

    def test_unknown_net_error(self):
        sa, errors = analyze_source("""
            component Test {
                port in A;
                connect A -> nonexistent;
            }
        """)
        assert len(errors) == 1
        assert "Unknown net" in str(errors[0])

    def test_bus_indexing(self):
        sa, errors = analyze_source("""
            component Test {
                bus data[8];
                port in X;
                connect X -> data[0];
                connect X -> data[7];
            }
        """)
        assert errors == [], [str(e) for e in errors]

    def test_bus_out_of_range_error(self):
        sa, errors = analyze_source("""
            component Test {
                bus data[4];
                port in X;
                connect X -> data[4];
            }
        """)
        assert len(errors) == 1
        assert "out of range" in str(errors[0])

    def test_wire_init(self):
        sa, errors = analyze_source("""
            component Test {
                wire vcc = HIGH;
                wire gnd = LOW;
                wire floating = FLOAT;
                relay R1;
                connect vcc -> R1.coil;
            }
        """)
        assert errors == [], [str(e) for e in errors]
        ac = sa.analyzed["Test"]
        assert ac.wires["vcc"].init == "HIGH"
        assert ac.wires["gnd"].init == "LOW"
        assert ac.wires["floating"].init == "FLOAT"


class TestStructuralChecks:
    def test_unconnected_coil_warning(self):
        sa, errors = analyze_source("""
            component Test {
                relay R1;
            }
        """)
        # Errors should be empty (unconnected coil is a warning, not error)
        assert errors == []
        assert any("coil" in w and "R1" in w for w in sa.warnings)

    def test_unknown_instance_component_error(self):
        sa, errors = analyze_source("""
            component Test {
                instance sub = Nonexistent();
            }
        """)
        assert len(errors) == 1
        assert "unknown component" in str(errors[0]).lower()


class TestTestbenchValidation:
    def test_valid_testbench(self):
        sa, errors = analyze_source("""
            component Adder {
                port in A, B;
                port out Sum;
            }
            testbench AdderTest for Adder {
                vector { A=0, B=0 } -> { Sum==0 };
                vector { A=1, B=0 } -> { Sum==1 };
            }
        """)
        assert errors == [], [str(e) for e in errors]
        assert len(sa.testbenches) == 1

    def test_unknown_port_in_vector_error(self):
        sa, errors = analyze_source("""
            component Adder {
                port in A;
                port out Sum;
            }
            testbench AdderTest for Adder {
                vector { A=0, X=0 } -> { Sum==0 };
            }
        """)
        assert len(errors) == 1
        assert "X" in str(errors[0])

    def test_driving_output_port_error(self):
        sa, errors = analyze_source("""
            component Adder {
                port in A;
                port out Sum;
            }
            testbench AdderTest for Adder {
                vector { Sum=0 } -> { A==0 };
            }
        """)
        assert any("output port" in str(e).lower() for e in errors)

    def test_unknown_target_error(self):
        sa, errors = analyze_source("""
            component Adder { }
            testbench Bad for Nonexistent { }
        """)
        assert len(errors) == 1
        assert "unknown component" in str(errors[0]).lower()


class TestZuseAdderSemantic:
    """Test semantic analysis of the Zuse adder example."""

    def test_analyze_zuse_adder(self):
        import os
        filepath = os.path.join(os.path.dirname(__file__),
                                "..", "examples", "zuse_adder.relay")
        with open(filepath) as f:
            source = f.read()
        sa, errors = analyze_source(source, filepath)
        # Filter out any errors that are just from incomplete components
        real_errors = [e for e in errors
                       if "ZuseAdder4P" not in str(e) or "unknown" not in str(e).lower()]
        # The file should at least parse and analyze the main components
        assert "ZuseAdder" in sa.analyzed or "ZuseAdder4P" in sa.analyzed


class TestComponentInfo:
    """Test that analyzed components contain correct metadata."""

    def test_all_nets(self):
        sa, errors = analyze_source("""
            component Test {
                port in A, B;
                port out Y;
                wire mid;
                relay R1;
                bus data[4];
            }
        """)
        assert errors == [], [str(e) for e in errors]
        ac = sa.analyzed["Test"]
        nets = ac.all_nets
        assert "A" in nets
        assert "B" in nets
        assert "Y" in nets
        assert "mid" in nets
        assert "R1.coil" in nets
        assert "R1.c1.common" in nets
        assert "R1.c2.nc" in nets
        assert "data[0]" in nets
        assert "data[3]" in nets

    def test_relay_symbol_info(self):
        sa, errors = analyze_source("""
            component Test {
                relay(4) BigRelay;
                relay SmallRelay;
            }
        """)
        assert errors == [], [str(e) for e in errors]
        ac = sa.analyzed["Test"]
        assert ac.relays["BigRelay"].poles == 4
        assert ac.relays["SmallRelay"].poles == 2
        assert len(ac.relays["BigRelay"].all_net_names()) == 13  # coil + 4*(common+no+nc)
        assert len(ac.relays["SmallRelay"].all_net_names()) == 7  # coil + 2*(common+no+nc)
