"""Test bus multiplexers."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.elaborate import elaborate, load_flat_into_engine
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState


def load_bus_program():
    import os
    filepath = os.path.join(os.path.dirname(__file__), "..", "stdlib", "bus.relay")
    with open(filepath) as f:
        source = f.read()
    return parse(source, filepath)


class TestMux2:
    def _make_engine(self):
        program = load_bus_program()
        flat = elaborate(program, "Mux2_1")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_select_a(self):
        engine = self._make_engine()
        engine.drive("A", WireState.HIGH)
        engine.drive("B", WireState.LOW)
        engine.drive("Sel", WireState.LOW)  # select A
        assert engine.read("Y") == WireState.HIGH

    def test_select_b(self):
        engine = self._make_engine()
        engine.drive("A", WireState.LOW)
        engine.drive("B", WireState.HIGH)
        engine.drive("Sel", WireState.HIGH)  # select B
        assert engine.read("Y") == WireState.HIGH


class TestMux4:
    def _make_engine(self):
        program = load_bus_program()
        flat = elaborate(program, "Mux4_1")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_all_inputs(self):
        for sel in range(4):
            engine = self._make_engine()
            # Drive selected input HIGH, others LOW
            for i in range(4):
                state = WireState.HIGH if i == sel else WireState.LOW
                engine.drive(f"D{i}", state)
            engine.drive("S0", WireState.HIGH if sel & 1 else WireState.LOW)
            engine.drive("S1", WireState.HIGH if sel & 2 else WireState.LOW)
            assert engine.read("Y") == WireState.HIGH, (
                f"Sel={sel}: expected HIGH")


class TestMux8:
    def _make_engine(self):
        program = load_bus_program()
        flat = elaborate(program, "Mux8_1")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_all_inputs(self):
        """Select each of 8 inputs and verify it reaches output."""
        for sel in range(8):
            engine = self._make_engine()
            for i in range(8):
                state = WireState.HIGH if i == sel else WireState.LOW
                engine.drive(f"D{i}", state)
            engine.drive("S0", WireState.HIGH if sel & 1 else WireState.LOW)
            engine.drive("S1", WireState.HIGH if sel & 2 else WireState.LOW)
            engine.drive("S2", WireState.HIGH if sel & 4 else WireState.LOW)
            assert engine.read("Y") == WireState.HIGH, (
                f"Sel={sel}: expected HIGH")

    def test_non_selected_blocked(self):
        """Non-selected inputs should not reach output."""
        engine = self._make_engine()
        # Select input 0, drive input 7 HIGH
        for i in range(8):
            engine.drive(f"D{i}", WireState.LOW)
        engine.drive("D7", WireState.HIGH)
        engine.drive("S0", WireState.LOW)
        engine.drive("S1", WireState.LOW)
        engine.drive("S2", WireState.LOW)  # select D0
        assert engine.read("Y") == WireState.LOW


class TestBusSrcMux:
    """Test the full 4-bit 8:1 data bus source mux."""

    def _make_engine(self):
        program = load_bus_program()
        flat = elaborate(program, "BusSrcMux")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def _drive_source(self, engine, name, value):
        """Drive a 4-bit source with a nibble value."""
        for i in range(4):
            bit = WireState.HIGH if (value >> i) & 1 else WireState.LOW
            engine.drive(f"{name}[{i}]", bit)

    def _read_bus(self, engine):
        result = 0
        for i in range(4):
            if engine.read(f"Bus[{i}]") == WireState.HIGH:
                result |= (1 << i)
        return result

    def test_select_accumulator(self):
        engine = self._make_engine()
        self._drive_source(engine, "Acc", 0xA)
        self._drive_source(engine, "XReg", 0x0)
        self._drive_source(engine, "MemData", 0x0)
        self._drive_source(engine, "Immediate", 0x0)
        self._drive_source(engine, "PCHigh", 0x0)
        self._drive_source(engine, "PCMid", 0x0)
        self._drive_source(engine, "PCLow", 0x0)
        self._drive_source(engine, "ALUResult", 0x0)
        # Select 000 = Accumulator
        engine.drive("Sel[0]", WireState.LOW)
        engine.drive("Sel[1]", WireState.LOW)
        engine.drive("Sel[2]", WireState.LOW)
        assert self._read_bus(engine) == 0xA

    def test_select_alu_result(self):
        engine = self._make_engine()
        self._drive_source(engine, "Acc", 0x0)
        self._drive_source(engine, "XReg", 0x0)
        self._drive_source(engine, "MemData", 0x0)
        self._drive_source(engine, "Immediate", 0x0)
        self._drive_source(engine, "PCHigh", 0x0)
        self._drive_source(engine, "PCMid", 0x0)
        self._drive_source(engine, "PCLow", 0x0)
        self._drive_source(engine, "ALUResult", 0x7)
        # Select 111 = ALU result
        engine.drive("Sel[0]", WireState.HIGH)
        engine.drive("Sel[1]", WireState.HIGH)
        engine.drive("Sel[2]", WireState.HIGH)
        assert self._read_bus(engine) == 0x7

    def test_all_sources(self):
        """Test each source selection with a unique value."""
        sources = [
            ("Acc", 0x1), ("XReg", 0x2), ("MemData", 0x3),
            ("Immediate", 0x4), ("PCHigh", 0x5), ("PCMid", 0x6),
            ("PCLow", 0x7), ("ALUResult", 0x8),
        ]
        for sel, (name, value) in enumerate(sources):
            engine = self._make_engine()
            # Drive all sources with unique values
            for sname, sval in sources:
                self._drive_source(engine, sname, sval)
            # Select this source
            engine.drive("Sel[0]", WireState.HIGH if sel & 1 else WireState.LOW)
            engine.drive("Sel[1]", WireState.HIGH if sel & 2 else WireState.LOW)
            engine.drive("Sel[2]", WireState.HIGH if sel & 4 else WireState.LOW)
            result = self._read_bus(engine)
            assert result == value, (
                f"Sel={sel} ({name}): expected 0x{value:X}, got 0x{result:X}")
        print(f"\nAll 8 bus sources select correctly!")


class TestBusDstDemux:
    """Test the destination demux (3-to-8 decoder with enable)."""

    def _make_engine(self):
        program = load_bus_program()
        flat = elaborate(program, "BusDstDemux")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_each_output(self):
        """Each select value should activate exactly one Load line."""
        for sel in range(8):
            engine = self._make_engine()
            engine.drive("Enable", WireState.HIGH)
            engine.drive("Sel[0]", WireState.HIGH if sel & 1 else WireState.LOW)
            engine.drive("Sel[1]", WireState.HIGH if sel & 2 else WireState.LOW)
            engine.drive("Sel[2]", WireState.HIGH if sel & 4 else WireState.LOW)
            # Selected output should be HIGH
            actual = engine.read(f"Load{sel}")
            assert actual == WireState.HIGH, (
                f"Sel={sel}: Load{sel} expected HIGH, got {actual}")
            # All other outputs should NOT be HIGH
            # (they may be LOW or FLOAT - either is fine,
            #  the register load relay won't energize)
            for i in range(8):
                if i != sel:
                    actual = engine.read(f"Load{i}")
                    assert actual != WireState.HIGH, (
                        f"Sel={sel}: Load{i} should not be HIGH")
        print(f"\nAll 8 destination selects decode correctly!")

    def test_enable_low(self):
        """When Enable is LOW, no output should be active."""
        engine = self._make_engine()
        engine.drive("Enable", WireState.LOW)
        engine.drive("Sel[0]", WireState.HIGH)
        engine.drive("Sel[1]", WireState.HIGH)
        engine.drive("Sel[2]", WireState.HIGH)
        for i in range(8):
            actual = engine.read(f"Load{i}")
            assert actual != WireState.HIGH, (
                f"Load{i} should not be HIGH when Enable is LOW")


class TestBusStats:
    def test_component_counts(self):
        program = load_bus_program()

        flat = elaborate(program, "Mux8_1")
        print(f"\n=== Mux8_1 (1-bit, 8:1) ===")
        print(f"  Relays: {len(flat.relays)}")

        flat = elaborate(program, "BusSrcMux")
        print(f"\n=== BusSrcMux (4-bit, 8:1) ===")
        print(f"  Relays: {len(flat.relays)}")

        flat = elaborate(program, "BusDstDemux")
        print(f"\n=== BusDstDemux (3-to-8 decoder) ===")
        print(f"  Relays: {len(flat.relays)}")

        flat = elaborate(program, "AddrSrcMux")
        print(f"\n=== AddrSrcMux (4-bit, 4:1) ===")
        print(f"  Relays: {len(flat.relays)}")
