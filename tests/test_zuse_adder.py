"""Test the Zuse full adder: 2 DPDT relays with complementary carry."""
import pytest
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState
from relaydsl.sim.components import RelayModel, Contact
from relaydsl.lang.parser import parse


class TestZuseAdderDirect:
    """Test the Zuse adder by building it directly in Python (no parser).

    Uses 4-pole relays (as in the original Zuse design, labeled "Relay4").
    R1 (coil=A) has 4 contacts generating intermediates from {0, 1, Cin, CinNeg}.
    R2 (coil=B) has 4 contacts selecting CarryOut, CarryOutNeg, Sum, SumNeg.

    CarryOut = majority(A, B, CarryIn):
      R1.c1: NC=GND, NO=CarryIn    -> A ? CarryIn : 0
      R1.c2: NC=CarryIn, NO=VCC    -> A ? 1 : CarryIn
      R2.c1: NC=R1.c1, NO=R1.c2    -> B ? (A?1:Cin) : (A?Cin:0) = majority

    CarryOutNeg = NOT(majority(A, B, CarryIn)):
      R1.c3: NC=VCC, NO=CarryInNeg    -> A ? CarryInNeg : 1
      R1.c4: NC=CarryInNeg, NO=GND    -> A ? 0 : CarryInNeg
      R2.c2: NC=R1.c3, NO=R1.c4       -> B ? (A?0:CinNeg) : (A?CinNeg:1) = NOT(majority)
    """

    def build_zuse_adder(self) -> SimEngine:
        engine = SimEngine(timing_mode="zero_delay")

        # Create input/output nets
        for name in ["A", "B", "CarryIn", "CarryInNeg",
                      "CarryOut", "CarryOutNeg"]:
            engine.get_or_create_net(name)

        # Constants
        vcc = engine.get_or_create_net("VCC")
        vcc.drive("const:VCC", WireState.HIGH)
        gnd = engine.get_or_create_net("GND")
        gnd.drive("const:GND", WireState.LOW)

        # R1: 4-pole relay, coil driven by A
        engine._create_relay("R1", num_contacts=4)
        engine.connections.append(("A", "R1.coil"))

        # R1.c1: NC=GND, NO=CarryIn -> when A=0: 0, when A=1: CarryIn
        engine.connections.append(("GND", "R1.c1.nc"))
        engine.connections.append(("CarryIn", "R1.c1.no"))

        # R1.c2: NC=CarryIn, NO=VCC -> when A=0: CarryIn, when A=1: 1
        engine.connections.append(("CarryIn", "R1.c2.nc"))
        engine.connections.append(("VCC", "R1.c2.no"))

        # R1.c3: NC=VCC, NO=CarryInNeg -> when A=0: 1, when A=1: CarryInNeg
        engine.connections.append(("VCC", "R1.c3.nc"))
        engine.connections.append(("CarryInNeg", "R1.c3.no"))

        # R1.c4: NC=CarryInNeg, NO=GND -> when A=0: CarryInNeg, when A=1: 0
        engine.connections.append(("CarryInNeg", "R1.c4.nc"))
        engine.connections.append(("GND", "R1.c4.no"))

        # R2: 4-pole relay, coil driven by B
        engine._create_relay("R2", num_contacts=4)
        engine.connections.append(("B", "R2.coil"))

        # R2.c1: NC=R1.c1.common, NO=R1.c2.common -> CarryOut
        engine.connections.append(("R1.c1.common", "R2.c1.nc"))
        engine.connections.append(("R1.c2.common", "R2.c1.no"))
        engine.connections.append(("R2.c1.common", "CarryOut"))

        # R2.c2: NC=R1.c3.common, NO=R1.c4.common -> CarryOutNeg
        engine.connections.append(("R1.c3.common", "R2.c2.nc"))
        engine.connections.append(("R1.c4.common", "R2.c2.no"))
        engine.connections.append(("R2.c2.common", "CarryOutNeg"))

        return engine

    def drive_inputs(self, engine: SimEngine, a: int, b: int, cin: int):
        engine.drive("A", WireState.HIGH if a else WireState.LOW)
        engine.drive("B", WireState.HIGH if b else WireState.LOW)
        engine.drive("CarryIn", WireState.HIGH if cin else WireState.LOW)
        engine.drive("CarryInNeg", WireState.LOW if cin else WireState.HIGH)

    @pytest.mark.parametrize("a,b,cin,expected_cout", [
        (0, 0, 0, 0),
        (1, 0, 0, 0),
        (0, 1, 0, 0),
        (1, 1, 0, 1),
        (0, 0, 1, 0),
        (1, 0, 1, 1),
        (0, 1, 1, 1),
        (1, 1, 1, 1),
    ])
    def test_carry_out(self, a, b, cin, expected_cout):
        engine = self.build_zuse_adder()
        self.drive_inputs(engine, a, b, cin)

        cout = engine.read("CarryOut")
        cout_neg = engine.read("CarryOutNeg")

        expected_state = WireState.HIGH if expected_cout else WireState.LOW
        expected_neg = WireState.LOW if expected_cout else WireState.HIGH

        assert cout == expected_state, (
            f"A={a} B={b} Cin={cin}: CarryOut expected {expected_state} got {cout}"
        )
        assert cout_neg == expected_neg, (
            f"A={a} B={b} Cin={cin}: CarryOutNeg expected {expected_neg} got {cout_neg}"
        )

    @pytest.mark.parametrize("a,b,cin,expected_cout", [
        (0, 0, 0, 0),
        (1, 1, 0, 1),
        (1, 0, 1, 1),
        (0, 1, 1, 1),
    ])
    def test_complementary_carry(self, a, b, cin, expected_cout):
        """Verify CarryOut and CarryOutNeg are always complementary."""
        engine = self.build_zuse_adder()
        self.drive_inputs(engine, a, b, cin)

        cout = engine.read("CarryOut")
        cout_neg = engine.read("CarryOutNeg")

        assert cout != cout_neg, (
            f"A={a} B={b} Cin={cin}: CarryOut={cout} and CarryOutNeg={cout_neg} "
            f"should be complementary"
        )


class TestZuseAdderParsed:
    """Test the Zuse adder by parsing the .relay file."""

    def test_parse_zuse_adder(self):
        import os
        filepath = os.path.join(os.path.dirname(__file__), "..", "examples", "zuse_adder.relay")
        with open(filepath) as f:
            source = f.read()

        program = parse(source, filepath)
        assert len(program.items) >= 1

        # First item should be the ZuseAdder component
        comp = program.items[0]
        assert comp.name == "ZuseAdder"

    def test_simulate_4p_from_parse(self):
        """Test the 4-pole version using relay(4) syntax."""
        import os
        from relaydsl.lang.ast_nodes import Component

        filepath = os.path.join(os.path.dirname(__file__), "..", "examples", "zuse_adder.relay")
        with open(filepath) as f:
            source = f.read()

        program = parse(source, filepath)
        # Get the ZuseAdder component (now uses relay(4) syntax)
        comp = next(item for item in program.items
                    if isinstance(item, Component) and item.name == "ZuseAdder")

        engine = SimEngine()
        engine.load_component(comp)

        # Test: A=1, B=1, Cin=0 -> Cout=1
        engine.drive("A", WireState.HIGH)
        engine.drive("B", WireState.HIGH)
        engine.drive("CarryIn", WireState.LOW)
        engine.drive("CarryInNeg", WireState.HIGH)

        assert engine.read("CarryOut") == WireState.HIGH
        assert engine.read("CarryOutNeg") == WireState.LOW


class TestLexer:
    """Basic lexer tests."""

    def test_tokenize_simple(self):
        from relaydsl.lang.lexer import Lexer, TokenType
        tokens = Lexer("relay R1;").tokenize()
        assert tokens[0].type == TokenType.RELAY
        assert tokens[1].type == TokenType.IDENT
        assert tokens[1].value == "R1"
        assert tokens[2].type == TokenType.SEMICOLON
        assert tokens[3].type == TokenType.EOF

    def test_tokenize_connect(self):
        from relaydsl.lang.lexer import Lexer, TokenType
        tokens = Lexer("connect A -> R1.coil;").tokenize()
        assert tokens[0].type == TokenType.CONNECT
        assert tokens[1].type == TokenType.IDENT
        assert tokens[2].type == TokenType.ARROW
        assert tokens[3].type == TokenType.IDENT
        assert tokens[4].type == TokenType.DOT
        assert tokens[5].type == TokenType.IDENT

    def test_tokenize_diode_arrow(self):
        from relaydsl.lang.lexer import Lexer, TokenType
        tokens = Lexer("connect A ->| B;").tokenize()
        assert tokens[2].type == TokenType.DIODE_ARROW

    def test_comments_skipped(self):
        from relaydsl.lang.lexer import Lexer, TokenType
        tokens = Lexer("# this is a comment\nrelay R1;").tokenize()
        assert tokens[0].type == TokenType.RELAY


class TestNetModel:
    """Test the tri-state net model."""

    def test_float_by_default(self):
        from relaydsl.sim.nets import Net
        n = Net("test")
        assert n.resolve() == WireState.FLOAT

    def test_single_driver_high(self):
        from relaydsl.sim.nets import Net
        n = Net("test")
        n.drive("src1", WireState.HIGH)
        assert n.resolve() == WireState.HIGH

    def test_conflict_raises(self):
        from relaydsl.sim.nets import Net
        n = Net("test")
        n.drive("src1", WireState.HIGH)
        n.drive("src2", WireState.LOW)
        with pytest.raises(Exception):
            n.resolve()

    def test_release_driver(self):
        from relaydsl.sim.nets import Net
        n = Net("test")
        n.drive("src1", WireState.HIGH)
        n.release("src1")
        assert n.resolve() == WireState.FLOAT


class TestUnionFind:
    """Test the union-find for net grouping."""

    def test_basic_union(self):
        from relaydsl.sim.nets import UnionFind
        uf = UnionFind()
        uf.make_set("a")
        uf.make_set("b")
        assert not uf.connected("a", "b")
        uf.union("a", "b")
        assert uf.connected("a", "b")

    def test_transitive(self):
        from relaydsl.sim.nets import UnionFind
        uf = UnionFind()
        for x in "abcd":
            uf.make_set(x)
        uf.union("a", "b")
        uf.union("b", "c")
        assert uf.connected("a", "c")
        assert not uf.connected("a", "d")
