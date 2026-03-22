"""Tests for timing simulation, trace output, and diode optimization."""
import pytest
from relaydsl.sim.engine import SimEngine
from relaydsl.sim.nets import WireState
from relaydsl.sim.timing import RelayTiming, TIMING_STANDARD, convert_time
from relaydsl.sim.trace import TraceRecorder


class TestTiming:
    def test_convert_time(self):
        assert convert_time(10, "ms") == 10.0
        assert convert_time(1000, "us") == 1.0
        assert convert_time(1_000_000, "ns") == 1.0
        assert convert_time(1, "ticks") == 10.0

    def test_bounce_schedule(self):
        timing = RelayTiming(bounce_count=3, bounce_interval=1.0)
        schedule = timing.bounce_schedule(start_time=10.0)
        assert len(schedule) == 3
        # Each interval should decrease
        intervals = [schedule[i] - (schedule[i-1] if i > 0 else 10.0)
                      for i in range(3)]
        assert intervals[0] > intervals[1] > intervals[2]

    def test_settle_time(self):
        timing = RelayTiming(
            energize_delay=10.0, deenergize_delay=8.0,
            bounce_count=0)
        assert timing.settle_time(energizing=True) == 10.0
        assert timing.settle_time(energizing=False) == 8.0

    def test_timed_simulation(self):
        """Test that timed mode delays relay switching."""
        engine = SimEngine(timing_mode="timed")
        engine._create_relay("R1")
        engine.get_or_create_net("input")
        engine.get_or_create_net("output")
        engine.get_or_create_net("vcc")
        engine.nets["vcc"].drive("const", WireState.HIGH)

        engine.connections.append(("input", "R1.coil"))
        engine.connections.append(("vcc", "R1.c1.no"))
        engine.connections.append(("R1.c1.common", "output"))

        # Drive input HIGH - relay should NOT switch immediately
        engine.drive("input", WireState.HIGH)

        # In timed mode, relay hasn't switched yet
        assert engine.relays["R1"].energized is False

        # Advance time past energize delay (default 10ms)
        engine.step(until=15.0)

        # Now relay should be energized
        assert engine.relays["R1"].energized is True
        assert engine.read("output") == WireState.HIGH


class TestTrace:
    def test_record_events(self):
        recorder = TraceRecorder()
        recorder.record(0.0, "A", WireState.FLOAT, WireState.HIGH)
        recorder.record(10.0, "B", WireState.FLOAT, WireState.LOW)
        assert len(recorder.events) == 2

    def test_text_dump(self):
        recorder = TraceRecorder()
        recorder.record(0.0, "A", WireState.FLOAT, WireState.HIGH)
        recorder.record(10.0, "A", WireState.HIGH, WireState.LOW)
        text = recorder.dump_text()
        assert "A" in text
        assert "H" in text
        assert "L" in text

    def test_filtered_recording(self):
        recorder = TraceRecorder(filter_nets={"A"})
        recorder.record(0.0, "A", WireState.FLOAT, WireState.HIGH)
        recorder.record(0.0, "B", WireState.FLOAT, WireState.LOW)
        assert len(recorder.events) == 1
        assert recorder.events[0].net_name == "A"

    def test_vcd_output(self):
        recorder = TraceRecorder()
        recorder.record_initial("A", WireState.LOW)
        recorder.record_initial("B", WireState.LOW)
        recorder.record(5.0, "A", WireState.LOW, WireState.HIGH)
        recorder.record(10.0, "B", WireState.LOW, WireState.HIGH)

        vcd = recorder.to_vcd()
        assert "$timescale" in vcd
        assert "$var wire" in vcd
        assert "#0" in vcd
        assert "#5" in vcd
        assert "#10" in vcd

    def test_engine_trace_integration(self):
        """Test that the engine records trace events."""
        engine = SimEngine()
        engine._create_relay("R1")
        engine.get_or_create_net("A")
        engine.get_or_create_net("Y")
        engine.get_or_create_net("vcc")
        engine.nets["vcc"].drive("const", WireState.HIGH)

        engine.connections.append(("A", "R1.coil"))
        engine.connections.append(("vcc", "R1.c1.no"))
        engine.connections.append(("R1.c1.common", "Y"))

        engine.drive("A", WireState.HIGH)

        # Should have recorded some state changes
        assert len(engine.trace.events) > 0


class TestDiodeOptimization:
    def test_and_is_unate(self):
        from relaydsl.opt.diode_opt import analyze_function
        # AND(A, B) = monotone positive in both variables
        tt = {(0,0): 0, (0,1): 0, (1,0): 0, (1,1): 1}
        result = analyze_function(tt, ["A", "B"])
        assert result["unate"] is True
        assert result["polarities"]["A"] == "pos"
        assert result["polarities"]["B"] == "pos"
        print(f"\nAND: {result['explanation']}")

    def test_or_is_unate(self):
        from relaydsl.opt.diode_opt import analyze_function
        tt = {(0,0): 0, (0,1): 1, (1,0): 1, (1,1): 1}
        result = analyze_function(tt, ["A", "B"])
        assert result["unate"] is True
        print(f"\nOR: {result['explanation']}")

    def test_xor_is_not_unate(self):
        from relaydsl.opt.diode_opt import analyze_function
        # XOR is binate - needs inversion, can't use diodes alone
        tt = {(0,0): 0, (0,1): 1, (1,0): 1, (1,1): 0}
        result = analyze_function(tt, ["A", "B"])
        assert result["unate"] is False
        print(f"\nXOR: {result['explanation']}")

    def test_majority_is_not_unate(self):
        """Majority IS actually unate (monotone positive in all variables)."""
        from relaydsl.opt.diode_opt import analyze_function
        tt = {
            (0,0,0): 0, (0,0,1): 0, (0,1,0): 0, (0,1,1): 1,
            (1,0,0): 0, (1,0,1): 1, (1,1,0): 1, (1,1,1): 1,
        }
        result = analyze_function(tt, ["A", "B", "C"])
        # Majority IS monotone! Each variable is positive-unate.
        # This means the carry function could theoretically use diodes...
        # BUT it needs a pull-down/pull-up structure that relays provide.
        assert result["unate"] is True
        print(f"\nMajority: {result['explanation']}")

    def test_nand_is_negative_unate(self):
        """NAND is monotone decreasing - implementable as OR(~A, ~B) with diodes."""
        from relaydsl.opt.diode_opt import analyze_function
        tt = {(0,0): 1, (0,1): 1, (1,0): 1, (1,1): 0}
        result = analyze_function(tt, ["A", "B"])
        # NAND IS unate (negative in both vars)
        assert result["unate"] is True
        assert result["polarities"]["A"] == "neg"
        assert result["polarities"]["B"] == "neg"
        print(f"\nNAND: {result['explanation']}")

    def test_suggest_optimizations(self):
        from relaydsl.opt.diode_opt import suggest_optimizations
        suggestions = suggest_optimizations(
            {
                "AND_gate": {(0,0): 0, (0,1): 0, (1,0): 0, (1,1): 1},
                "OR_gate": {(0,0): 0, (0,1): 1, (1,0): 1, (1,1): 1},
                "XOR_gate": {(0,0): 0, (0,1): 1, (1,0): 1, (1,1): 0},
            },
            ["A", "B"],
        )
        print("\n=== Diode Optimization Suggestions ===")
        for s in suggestions:
            print(s)

        # AND and OR should be diode-replaceable, XOR should not
        assert any("AND_gate" in s and "diode" in s.lower() for s in suggestions)
        assert any("OR_gate" in s and "diode" in s.lower() for s in suggestions)
        assert any("XOR_gate" in s and "RELAY" in s for s in suggestions)

    def test_diode_circuit_synthesis(self):
        """Test that the optimizer generates actual diode gate descriptions."""
        from relaydsl.opt.diode_opt import analyze_function
        # 3-input AND
        tt = {
            (0,0,0): 0, (0,0,1): 0, (0,1,0): 0, (0,1,1): 0,
            (1,0,0): 0, (1,0,1): 0, (1,1,0): 0, (1,1,1): 1,
        }
        result = analyze_function(tt, ["A", "B", "C"])
        assert result["unate"] is True
        assert result["diode_circuit"] is not None
        assert len(result["diode_circuit"]) >= 1
        gate = result["diode_circuit"][0]
        assert gate.gate_type == "AND"
        assert set(gate.inputs) == {"A", "B", "C"}
        print(f"\n3-AND: {gate.gate_type}({', '.join(gate.inputs)}) -> {gate.output}")
        print(f"  Diodes needed: {result['diode_count']}")
