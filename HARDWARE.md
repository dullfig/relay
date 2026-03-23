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

- **Capacitor**: 22uF 16V ceramic (1210 package, 3.2mm x 2.5mm)
- **Diodes**: 2x per cell (0603 package, 1.6mm x 0.8mm)
- **Relays per cell**: 0 (diode-gated, per relaiscomputer.nl design)
- **Hold time**: ~14 hours above pickup with ceramic dielectric
- **Refresh**: software (optional, ceramic caps hold for hours)
- **Cell footprint**: ~8mm x 3mm

## Clock

- Source: 60Hz mains or neon relaxation oscillator
- Division: neon lamp cascade (divide-by-2 per stage)
- System clock: ~30 Hz (one divider stage from 60Hz)
- Clock cycle: ~26ms (4 relay stages worst case at 6ms/stage + margin)

## Display

- **Tubes**: 8x nixie (IN-12 or similar), BCD-driven
- **Decoder**: diode AND matrix, BCD-to-decimal, zero relays
- **Drive**: static (clock halts on answer, all digits driven continuously)

## Board Dimensions

Target: 100mm x 100mm per board (JLCPCB cheapest tier)

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
