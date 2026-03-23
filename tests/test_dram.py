"""Test discrete DRAM: diode-gated capacitor cells."""
import pytest
from relaydsl.lang.parser import parse
from relaydsl.lang.elaborate import elaborate, load_flat_into_engine
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState


def load_memory_program():
    import os
    filepath = os.path.join(os.path.dirname(__file__), "..", "stdlib", "memory.relay")
    with open(filepath) as f:
        source = f.read()
    return parse(source, filepath)


class TestDRAMBitCell:
    """Test a single DRAM bit cell."""

    def _make_engine(self):
        program = load_memory_program()
        flat = elaborate(program, "DRAMBitCell")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def _write_bit(self, engine, value):
        engine.drive("WriteData", WireState.HIGH if value else WireState.LOW)
        engine.drive("RowSelect", WireState.HIGH)
        engine.drive("WriteEnable", WireState.HIGH)
        engine.drive("ReadEnable", WireState.LOW)
        # Latch
        engine.drive("WriteEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.LOW)

    def _read_bit(self, engine):
        engine.drive("WriteEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.HIGH)
        engine.drive("ReadEnable", WireState.HIGH)
        result = engine.read("SenseLine")
        engine.drive("ReadEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.LOW)
        return result

    def test_write_one_read_one(self):
        engine = self._make_engine()
        self._write_bit(engine, 1)
        result = self._read_bit(engine)
        assert result == WireState.HIGH, f"Expected HIGH, got {result}"

    def test_write_zero_read_zero(self):
        engine = self._make_engine()
        self._write_bit(engine, 0)
        result = self._read_bit(engine)
        assert result == WireState.LOW, f"Expected LOW, got {result}"

    def test_unwritten_reads_float(self):
        """An unwritten cell has no charge - sense line floats (reads as 0)."""
        engine = self._make_engine()
        result = self._read_bit(engine)
        # No charge = no driver = FLOAT (which the sense relay interprets as 0)
        assert result in (WireState.LOW, WireState.FLOAT), (
            f"Expected LOW or FLOAT for unwritten, got {result}")

    def test_overwrite(self):
        engine = self._make_engine()
        self._write_bit(engine, 1)
        self._write_bit(engine, 0)
        result = self._read_bit(engine)
        assert result == WireState.LOW, f"Expected LOW after overwrite, got {result}"

    def test_capacitor_decay(self):
        engine = self._make_engine()
        self._write_bit(engine, 1)

        # Find the cap
        cap = next(iter(engine.capacitors.values()), None)
        assert cap is not None

        # Right after write
        assert cap.read(engine.time) == WireState.HIGH

        # After decay (50000ms for ceramic caps)
        assert cap.read(engine.time + 60000.0) == WireState.FLOAT


class TestDecoder:
    """Test the 2-to-4 address decoder."""

    def _make_engine(self):
        program = load_memory_program()
        flat = elaborate(program, "Decoder2to4")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def test_all_addresses(self):
        for addr in range(4):
            engine = self._make_engine()
            engine.drive("A0", WireState.HIGH if addr & 1 else WireState.LOW)
            engine.drive("A1", WireState.HIGH if addr & 2 else WireState.LOW)

            for sel in range(4):
                expected = WireState.HIGH if sel == addr else WireState.LOW
                actual = engine.read(f"S{sel}")
                assert actual == expected, (
                    f"Addr={addr}: S{sel} expected {expected} got {actual}")


class TestDRAMNibble:
    """Test 4-bit DRAM word with sense amplifiers."""

    def _make_engine(self):
        program = load_memory_program()
        flat = elaborate(program, "DRAMNibble")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)
        return engine

    def _write_nibble(self, engine, value):
        for i in range(4):
            bit = WireState.HIGH if (value >> i) & 1 else WireState.LOW
            engine.drive(f"D[{i}]", bit)
        engine.drive("RowSelect", WireState.HIGH)
        engine.drive("WriteEnable", WireState.HIGH)
        engine.drive("ReadEnable", WireState.LOW)
        engine.drive("WriteEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.LOW)
        # Clear data bus
        for i in range(4):
            engine.drive(f"D[{i}]", WireState.LOW)

    def _read_nibble(self, engine):
        engine.drive("WriteEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.HIGH)
        engine.drive("ReadEnable", WireState.HIGH)
        result = 0
        for i in range(4):
            if engine.read(f"Q[{i}]") == WireState.HIGH:
                result |= (1 << i)
        engine.drive("ReadEnable", WireState.LOW)
        engine.drive("RowSelect", WireState.LOW)
        return result

    def test_write_read_all_values(self):
        failures = []
        for val in range(16):
            engine = self._make_engine()
            self._write_nibble(engine, val)
            result = self._read_nibble(engine)
            if result != val:
                failures.append(f"Wrote {val}, read {result}")

        assert not failures, f"Failures: {failures}"
        print(f"\nAll 16 nibble values OK!")


class TestDRAMStats:
    """Report component counts."""

    def test_cell_stats(self):
        program = load_memory_program()
        flat = elaborate(program, "DRAMBitCell")
        print(f"\n=== DRAM Bit Cell ===")
        print(f"  Relays: {len(flat.relays)}")
        print(f"  Capacitors: {len(flat.capacitors)}")
        print(f"  Diodes: {len(flat.diodes)}")

    def test_nibble_stats(self):
        program = load_memory_program()
        flat = elaborate(program, "DRAMNibble")
        print(f"\n=== DRAM Nibble ===")
        print(f"  Relays: {len(flat.relays)}")
        print(f"  Capacitors: {len(flat.capacitors)}")
        print(f"  Sense amps: 4 (1 relay each)")

    def test_decoder_stats(self):
        program = load_memory_program()
        flat = elaborate(program, "Decoder2to4")
        print(f"\n=== 2-to-4 Decoder ===")
        print(f"  Relays: {len(flat.relays)}")

    def test_scaling_estimate(self):
        """Estimate component counts for a real memory."""
        program = load_memory_program()
        cell = elaborate(program, "DRAMBitCell")
        nibble = elaborate(program, "DRAMNibble")

        relays_per_cell = len(cell.relays)
        caps_per_cell = len(cell.capacitors)
        relays_per_nibble = len(nibble.relays)
        caps_per_nibble = len(nibble.capacitors)

        print(f"\n=== Memory Scaling Estimates ===")
        print(f"Per bit cell: {relays_per_cell} relays, {caps_per_cell} cap")
        print(f"Per nibble:   {relays_per_nibble} relays, {caps_per_nibble} caps")
        print()

        for words in [64, 256, 1024]:
            bits = words * 4
            # Cells: 4 relays per cell currently (simulation model)
            # In physical diode-gated: 0 relays per cell, 2 diodes
            # Decoder: log2(words) relays roughly
            import math
            addr_bits = int(math.log2(words))
            decoder_relays = addr_bits * 2  # rough estimate
            sense_relays = 4  # one per bit column
            mux_relays = 4  # output mux

            # Simulation model (relay-gated)
            sim_relays = relays_per_cell * bits + decoder_relays + sense_relays
            sim_caps = bits

            # Physical model (diode-gated, per relaiscomputer.nl)
            phys_relays = decoder_relays + sense_relays + mux_relays
            phys_diodes = 2 * bits
            phys_caps = bits

            print(f"{words} words x 4 bits ({bits} cells):")
            print(f"  Simulation: {sim_relays} relays, {sim_caps} caps")
            print(f"  Physical:   {phys_relays} relays, {phys_diodes} diodes, {phys_caps} caps")
            print()
