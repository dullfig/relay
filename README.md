# RelayDSL

A scripting language and simulator for designing computers out of electromechanical relays.

Born from a years-long dream: build a programmable BCD calculator entirely from tiny 4PDT relays, diodes, and capacitors. RelayDSL lets you design, simulate, and verify relay circuits before committing to PCB fabrication.

## What it does

```relay
component ZuseAdder {
    port in A, B;
    port in CarryIn, CarryInNeg;
    port out CarryOut, CarryOutNeg;

    wire vcc = HIGH;
    wire gnd = LOW;

    relay(4) R1, R2;

    connect A -> R1.coil;
    connect gnd -> R1.c1.nc;
    connect CarryIn -> R1.c1.no;
    connect CarryIn -> R1.c2.nc;
    connect vcc -> R1.c2.no;
    # ... (full Zuse full adder in 2 relays)
}

testbench ZuseAdderTest for ZuseAdder {
    vector { A=1, B=1, CarryIn=0, CarryInNeg=1 }
        -> { CarryOut==1, CarryOutNeg==0 };
}
```

```
$ python -m relaydsl test examples/zuse_adder.relay
=== Testbench: ZuseAdderTest for ZuseAdder ===
  8 passed, 0 failed
```

## Features

**Language**
- Declare relays (`relay(4) R1;` for 4PDT), diodes, capacitors, fuses
- Tri-state wire model: HIGH, LOW, and FLOAT (floating = not connected, reads as zero)
- Connect statements with optional inline diodes (`connect A ->| B;`)
- Bus declarations and bus port binding (`port in A[4];`, `instance add = Adder(A=data[0..3]);`)
- Component hierarchy with instance elaboration
- Import system with transitive resolution and circular dependency detection
- Testbenches with test vectors

**Simulator**
- Event-driven with union-find net resolution (handles bidirectional relay contacts correctly)
- Zero-delay mode for functional verification
- Timed mode with configurable energize/de-energize delays and contact bounce
- VCD waveform output for external viewers
- Component models: DPDT/4PDT relays, diodes, capacitors (with decay), programmable fuses

**Shannon Expansion Synthesizer**
- Feed it a truth table, get back an optimal relay circuit
- Discovers Konrad Zuse's 1941 full adder from the majority function specification
- Tries all variable orderings, minimizes relay count
- Generates `.relay` source code from synthesis results

**Diode Optimizer**
- Analyzes Boolean functions for monotonicity (unateness)
- Identifies where passive diode AND/OR networks can replace relay stages
- Reports potential relay savings

**CLI**
```
relay-sim parse     <file.relay>    Parse, resolve imports, report errors
relay-sim test      <file.relay>    Run testbenches
relay-sim simulate  <file.relay>    Load and inspect circuit state
relay-sim count     <file.relay>    Report component counts
```

## Examples

| Example | What it tests | Result |
|---------|--------------|--------|
| `zuse_adder.relay` | Konrad Zuse's 2-relay full adder with complementary carry | 8/8 vectors |
| `four_bit_adder.relay` | 4 chained Zuse adders via imports | 4/4 vectors (exhaustive 256-case test in pytest) |
| `dual_mode_adder.relay` | BCD/binary dual-mode nibble adder with mode flag | 256/256 binary + 100/100 BCD |

## The Machine

The target is a programmable BCD calculator with:

- **4PDT relays** (~0.500 x 0.250 inches) for all logic
- **Diode AND/OR networks** replacing relays where functions are monotone
- **Discrete DRAM** using SMD ceramic capacitors + diode pairs (pick-and-place)
- **Fuse-board microcode** (programmable connections, blown = zero)
- **Dual-mode ALU** — BCD for arithmetic, binary for address math (like the 6502's D flag)
- **Clock halts on answer** — relay coils draw continuous current; idle = off
- **Neon lamp clock** — cascade of relaxation oscillators dividing 60Hz; displays time when idle

## Architecture

```
relaydsl/
├── lang/           # Language frontend
│   ├── lexer.py        # Tokenizer
│   ├── parser.py       # Recursive descent parser
│   ├── ast_nodes.py    # AST dataclasses
│   ├── semantic.py     # Symbol tables, net resolution, validation
│   ├── imports.py      # Multi-file import resolver
│   └── elaborate.py    # Instance flattening, bus binding
├── sim/            # Simulator
│   ├── engine.py       # Event-driven simulation loop
│   ├── nets.py         # Tri-state nets, union-find resolver
│   ├── components.py   # Relay, diode, capacitor, fuse models
│   ├── timing.py       # Delay and bounce models
│   ├── events.py       # Priority queue
│   └── trace.py        # VCD and text trace output
├── synth/          # Synthesis
│   └── synthesize.py   # Shannon expansion, truth table to relay circuit
└── opt/            # Optimization
    └── diode_opt.py    # Unateness analysis, diode replacement
```

## Requirements

Python 3.11+. Zero external dependencies for the core. `pytest` for tests.

```
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Why relays?

Because every switching decision is visible. Every contact closure is audible. You can trace a carry propagating through the adder with your finger on the PCB. Transistors hide everything behind abstraction — relays show you computation happening in the physical world.

Konrad Zuse built the world's first programmable computer from relays in 1941, working in isolation in wartime Berlin. He independently reinvented Boolean algebra without knowing Shannon's 1938 thesis existed. This project asks: what could he have built with 80 years of hindsight?

## License

MIT
