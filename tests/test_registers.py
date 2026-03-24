"""Test CPU registers."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.elaborate import elaborate, load_flat_into_engine
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState


def load_reg_program():
    import os
    filepath = os.path.join(os.path.dirname(__file__), "..", "stdlib", "registers.relay")
    with open(filepath) as f:
        source = f.read()
    return parse(source, filepath)


class TestReg4:
    """Test 4-bit latching register."""

    def _make_engine(self):
        program = load_reg_program()
        flat = elaborate(program, "Reg4")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def _write_reg(self, engine, value):
        for i in range(4):
            bit = WireState.HIGH if (value >> i) & 1 else WireState.LOW
            engine.drive(f"D[{i}]", bit)
        engine.drive("Load", WireState.HIGH)
        engine.drive("OutputEn", WireState.LOW)
        engine.drive("Load", WireState.LOW)

    def _read_reg(self, engine):
        engine.drive("OutputEn", WireState.HIGH)
        result = 0
        for i in range(4):
            if engine.read(f"Q[{i}]") == WireState.HIGH:
                result |= (1 << i)
        engine.drive("OutputEn", WireState.LOW)
        return result

    def test_write_read(self):
        engine = self._make_engine()
        self._write_reg(engine, 0xA)
        result = self._read_reg(engine)
        assert result == 0xA, f"Expected 0xA, got 0x{result:X}"

    def test_write_read_all_values(self):
        failures = []
        for val in range(16):
            engine = self._make_engine()
            self._write_reg(engine, val)
            result = self._read_reg(engine)
            if result != val:
                failures.append(f"Wrote 0x{val:X}, read 0x{result:X}")
        assert not failures, f"Failures: {failures}"
        print(f"\nAll 16 register values OK!")

    def test_overwrite(self):
        engine = self._make_engine()
        self._write_reg(engine, 0xF)
        self._write_reg(engine, 0x3)
        result = self._read_reg(engine)
        assert result == 0x3, f"Expected 0x3 after overwrite, got 0x{result:X}"

    def test_output_disabled(self):
        """When OutputEn is low, Q should be LOW (not floating)."""
        engine = self._make_engine()
        self._write_reg(engine, 0xF)
        engine.drive("OutputEn", WireState.LOW)
        for i in range(4):
            state = engine.read(f"Q[{i}]")
            assert state == WireState.LOW, (
                f"Q[{i}] should be LOW when output disabled, got {state}")

    def test_holds_value(self):
        """Register holds value after Load goes low."""
        engine = self._make_engine()
        self._write_reg(engine, 0x7)
        # Clear data bus
        for i in range(4):
            engine.drive(f"D[{i}]", WireState.LOW)
        # Value should still be latched
        result = self._read_reg(engine)
        assert result == 0x7, f"Expected 0x7 held, got 0x{result:X}"


class TestFlagsReg:
    """Test the flags register."""

    def _make_engine(self):
        program = load_reg_program()
        flat = elaborate(program, "FlagsReg")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_set_zero_flag(self):
        engine = self._make_engine()
        engine.drive("ZeroIn", WireState.HIGH)
        engine.drive("CarryIn", WireState.LOW)
        engine.drive("DecimalIn", WireState.LOW)
        engine.drive("LoadZC", WireState.HIGH)
        engine.drive("LoadD", WireState.LOW)
        engine.drive("LoadZC", WireState.LOW)
        assert engine.read("ZeroOut") == WireState.HIGH
        assert engine.read("CarryOut") == WireState.LOW

    def test_set_carry_flag(self):
        engine = self._make_engine()
        engine.drive("ZeroIn", WireState.LOW)
        engine.drive("CarryIn", WireState.HIGH)
        engine.drive("LoadZC", WireState.HIGH)
        engine.drive("LoadD", WireState.LOW)
        engine.drive("LoadZC", WireState.LOW)
        assert engine.read("CarryOut") == WireState.HIGH
        assert engine.read("ZeroOut") == WireState.LOW

    def test_decimal_flag_independent(self):
        """D flag loads independently from Z and C."""
        engine = self._make_engine()
        # Set decimal flag
        engine.drive("DecimalIn", WireState.HIGH)
        engine.drive("LoadD", WireState.HIGH)
        engine.drive("LoadZC", WireState.LOW)
        engine.drive("LoadD", WireState.LOW)
        assert engine.read("DecimalOut") == WireState.HIGH

        # Set Z and C, D should not change
        engine.drive("ZeroIn", WireState.HIGH)
        engine.drive("CarryIn", WireState.HIGH)
        engine.drive("LoadZC", WireState.HIGH)
        engine.drive("LoadZC", WireState.LOW)
        assert engine.read("DecimalOut") == WireState.HIGH
        assert engine.read("ZeroOut") == WireState.HIGH
        assert engine.read("CarryOut") == WireState.HIGH


class TestRegStats:
    def test_reg4_stats(self):
        program = load_reg_program()
        flat = elaborate(program, "Reg4")
        print(f"\n=== Reg4 (4-bit register) ===")
        print(f"  Relays: {len(flat.relays)}")
        print(f"  Capacitors: {len(flat.capacitors)}")

    def test_flags_stats(self):
        program = load_reg_program()
        flat = elaborate(program, "FlagsReg")
        print(f"\n=== FlagsReg (Z, C, D) ===")
        print(f"  Relays: {len(flat.relays)}")
        print(f"  Capacitors: {len(flat.capacitors)}")
