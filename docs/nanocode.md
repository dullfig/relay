# Nanocode Architecture

## Overview

The microcode is split into two levels:

1. **Microcode boards** (one per instruction, 30 boards) — tiny fuse matrices
   that output a sequence of 8-bit nano-op codes, one per clock step.
2. **Nano-circuits** (shared hardware on CPU boards) — decode the nano-op
   codes and assert the actual control lines. Not separate boards — just
   wired sections on existing CPU boards selected by 4-to-16 relay decoders.

Each microcode step outputs two simultaneous 4-bit fields:

```
  [SOURCE:4 bits] [ACTION:4 bits]
   who drives      what happens
   the data bus    with it
```

Both fire on the same clock edge. Zero timing overhead vs direct microcode.

## Source Codes (4 bits — who drives the data bus)

| Code | Name       | Description                        |
|------|------------|------------------------------------|
| 0000 | SRC_NONE   | Bus idle (no driver)               |
| 0001 | SRC_ACC    | Accumulator -> data bus            |
| 0010 | SRC_X      | X register -> data bus             |
| 0011 | SRC_MEM    | Memory read -> data bus            |
| 0100 | SRC_IMM    | Immediate/operand -> data bus      |
| 0101 | SRC_ALU    | ALU result -> data bus             |
| 0110 | SRC_SHIFT  | Shifter result -> data bus         |
| 0111 | SRC_PCH    | PC high nibble -> data bus         |
| 1000 | SRC_PCM    | PC mid nibble -> data bus          |
| 1001 | SRC_PCL    | PC low nibble -> data bus          |
| 1010 | SRC_FLAGS  | Flags register -> data bus         |
| 1011 | SRC_TEMP   | Temp register -> data bus          |
| 1100 | SRC_SP     | Stack pointer -> data bus          |
| 1101 | (spare)    |                                    |
| 1110 | (spare)    |                                    |
| 1111 | (spare)    |                                    |

## Action Codes (4 bits — what happens this step)

| Code | Name       | Description                        |
|------|------------|------------------------------------|
| 0000 | ACT_NONE   | No action (bus setup only)         |
| 0001 | ACT_TO_ACC | Data bus -> accumulator            |
| 0010 | ACT_TO_X   | Data bus -> X register             |
| 0011 | ACT_TO_MEM | Data bus -> memory write           |
| 0100 | ACT_TO_TEMP| Data bus -> temp register          |
| 0101 | ACT_TO_PCH | Data bus -> PC high nibble         |
| 0110 | ACT_TO_PCM | Data bus -> PC mid nibble          |
| 0111 | ACT_TO_PCL | Data bus -> PC low nibble          |
| 1000 | ACT_ADD    | ALU add, set flags                 |
| 1001 | ACT_SUB    | ALU sub (complement+carry), flags  |
| 1010 | ACT_AND    | ALU AND, set flags                 |
| 1011 | ACT_OR     | ALU OR, set flags                  |
| 1100 | ACT_SHL    | Shift left, set flags              |
| 1101 | ACT_SHR    | Shift right, set flags             |
| 1110 | ACT_SETADDR| Set address bus from operand       |
| 1111 | ACT_DONE   | End execute, return to fetch       |

## Instruction Microcode

Each instruction is a sequence of hex bytes (source nibble + action nibble):

```
NOP:       0F
HLT:       0F  (+ halt signal from instruction decoder)
TAX:       12 0F
TXA:       21 0F
LDA zp:    0E 31 0F
STA zp:    0E 13 0F
LDX zp:    0E 32 0F
STX zp:    0E 23 0F
ADD zp:    0E 34 B8 51 0F
SUB zp:    0E 34 B9 51 0F
AND zp:    0E 34 BA 51 0F
ORA zp:    0E 34 BB 51 0F
CMP zp:    0E 34 B9 0F        (sub without storing result)
INC acc:   18 51 0F
DEC acc:   19 51 0F            (sub with implicit 1)
INX:       28 52 0F
DEX:       29 52 0F
ASL acc:   1C 61 0F
LSR acc:   1D 61 0F
JMP abs:   45 46 47 0F
```

### Shared patterns

| Pattern | Meaning | Used by |
|---------|---------|---------|
| `0E`    | Set address bus from operand | All memory-accessing instructions |
| `34`    | Memory read to temp register | ADD, SUB, AND, ORA, CMP |
| `51`    | ALU result to accumulator | ADD, SUB, AND, ORA, INC, DEC, shifts |
| `0F`    | Done | Every instruction (last step) |

Fix one nano-circuit, every instruction that uses it benefits.

## Physical Implementation

### Microcode boards

- 8 bits per step x 8 steps = **64 fuse points per board**
- Physical size: ~15mm x 30mm (postage stamp)
- 30 boards x 64 = **1,920 total fuses** (was 5,760 with direct microcode, 67% reduction)
- Can be pre-fabricated: PCB manufacturer prints the pattern directly,
  no fuse burning needed. JLCPCB ~$2/design for 5 copies.
- Keep blank boards for experimentation and custom instructions.

### Nano-decode hardware

- Source decoder: 4-bit to 16-line relay tree (~8 relays) on register board
- Action decoder: 4-bit to 16-line relay tree (~8 relays) on control board
- Total added: **16 relays** (negligible)
- Each nano-circuit output has an **isolation diode** to prevent
  backfeed on the shared control bus (same principle as DRAM gating)

### Vs direct microcode

| | Direct | Nanocode |
|---|--------|----------|
| Fuses per board | 192 | 64 |
| Total fuses | 5,760 | 1,920 |
| Board size | 30mm x 71mm | 15mm x 30mm |
| Extra relays | 0 | 16 |
| Bug fix scope | 1 board | All instructions sharing that nano-op |
| Extensibility | Rewire control lines | Add a nano-code, existing boards unchanged |
