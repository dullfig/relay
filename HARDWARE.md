# Hardware Reference

## Relay: Panasonic AGN20012

- **Type**: DPDT (2 Form C), single side stable
- **Coil**: 12V DC, 1028 ohm, 11.7mA, 140mW
- **Contacts**: AgPd, 1A 30V DC, 100 mohm max
- **Timing**: 4ms operate, 4ms release (max, excluding bounce)
- **Pickup**: 75% of nominal (9V)
- **Dropout**: 10% of nominal (1.2V)
- **Footprint**: 5.7mm x 10.6mm, 9.0mm height
- **Weight**: 1g
- **Life**: 50 million mechanical cycles
- **Packing**: Through-hole (AGN20012) or SMD tape & reel (AGN200A12Z)
- **Datasheet**: agn20009.pdf

## System Voltage

12V DC throughout. Single rail.

- Relay coils: 12V direct
- Logic levels: 12V = HIGH, 0V = LOW
- DRAM caps: charged to 12V
- Nixie tubes: boost converter from 12V to 170V
- Neon lamps: from nixie supply through limiting resistors

## DRAM Cell

- **Capacitor**: Murata GRT21BC81C226ME13 (22uF 16V ceramic, 0805 package, 2.0mm x 1.25mm)
- **Diodes**: 2x per cell (0603 package, 1.6mm x 0.8mm)
- **Relays per cell**: 0 (diode-gated, per relaiscomputer.nl design)
- **Hold time**: ~14 hours above pickup with ceramic dielectric
- **Refresh**: software (optional, ceramic caps hold for hours)
- **Cell footprint**: ~7.6mm x 2.0mm (single-sided) or ~2.5mm x 1.8mm (double-sided, cap top, diodes bottom)
- **Cost**: ~$0.09/cap (10K reel), ~$0.02/diode

### Board Address Selection

Each memory board has a DIP switch setting its page address. The board
compares the high address bits against its DIP switch and only activates
when they match. No central memory controller needed.

- 4-bit DIP: 16 pages x 256 nibbles = 4K address space
- 8-bit DIP: 256 pages x 256 nibbles = 64K address space
- Page comparator: XNOR per bit (1 relay each) + diode AND = ~4 relays per board
- Adding memory: set DIP switches, plug in board, done

### Memory Board Options (100mm x 100mm target)

| Layout | Words | Boards for 1K | Board size | Fit? |
|--------|-------|---------------|------------|------|
| 256 x 4-bit (tight) | 256 | 4 | 99mm x 87mm | YES |
| 128 x 4-bit (comfortable) | 128 | 8 | 84mm x 74mm | YES |

### Memory Cost (1K x 4-bit)

| Component | Quantity | Unit cost | Total |
|-----------|----------|-----------|-------|
| 22uF caps | 4,096 | $0.09 | $369 |
| Diodes | 8,192 | $0.02 | $164 |
| PCBs | 4-8 | $8 | $32-64 |
| **Total** | | | **~$565-597** |

## Clock

- Source: 60Hz mains
- Prescaler: mod-60 counter (7 latching relays) for exact 1Hz tick
- Division: neon lamp cascade (divide-by-2 per stage) for system clock
- System clock: ~30 Hz (one divider stage from 60Hz)
- Clock cycle: ~26ms (4 relay stages worst case at 6ms/stage + margin)

## Real-Time Clock

- Display: HH:MM on 4 of the 8 nixie tubes (shared with calculator)
- Seconds: 1Hz neon lamp from divider chain, mounted as colon separator
- Counter: BCD decade/mod-6 counters using AGN21012 latching relays
  - Minutes ones: 4 bits (decade, reset on 10)
  - Minutes tens: 3 bits (reset on 6)
  - Hours ones: 4 bits (decade, reset on 24 with tens)
  - Hours tens: 2 bits (reset on 24 with ones)
  - Total: ~17 latching relays + reset logic
- Output: BCD counter feeds same diode decoder matrix as calculator
- Switching: 1 relay selects nixie input (calculator result vs clock)
- Latching relays (AGN21012): same family/footprint as AGN20012, hold state with zero power

## Display

- **Tubes**: 8x nixie (IN-12 or similar), BCD-driven
- **Decoder**: diode AND matrix, BCD-to-decimal, zero relays
- **Drive**: static (clock halts on answer, all digits driven continuously)

## Board Dimensions

Target: 100mm x 100mm per board (JLCPCB cheapest tier)

## Boot / Program Loading

- LOAD button: hold to load from paper tape into DRAM
- Clock auto-steps tape reader, one nibble per tick (~30Hz)
- 256 nibbles loads in ~8.5 seconds
- Tape switches connect directly to data bus
- Address counter (shared with PC) auto-increments
- End-of-tape: all-holes pattern detected, stops loading
- Hardware cost: 1 button + ~3 relays
- After loading: press RUN to execute from address 0

## Front Panel Controls

| Control | Function |
|---------|----------|
| LOAD | Hold to load program from tape |
| RUN | Start execution from address 0 |
| 0-9 | Digit entry |
| . | Decimal point |
| + - x / | Arithmetic operations (hardwired in microcode) |
| = | Compute result |
| FUNC | Enter function number, run stored program (FUNC 0 = set time) |
| CLEAR | Clear display/entry |

## Estimated Relay Count

| Board | Relays |
|-------|--------|
| ALU (dual-mode, 2 nibbles) | ~64 |
| Registers | ~20 |
| Control/sequencer | ~30 |
| Bus interface | ~15 |
| I/O | ~10 |
| Memory (decoder + sense) | ~32 |
| **Total** | **~171** |
