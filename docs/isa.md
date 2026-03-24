# Instruction Set Architecture

Relay computer ISA, loosely inspired by the 6502 but simplified for relay decode logic.

## Machine Constants

| Parameter | Value |
|-----------|-------|
| ALU width | 4 bits (nibble), BCD/binary selectable |
| Address space | 12 bits (4096 nibbles) |
| Memory fetch width | 3 nibbles (12 bits) per read |
| Opcode width | 2 nibbles (8 bits), fixed |
| Max instruction length | 5 nibbles (2 opcode + 3 operand) |

## Opcode Encoding

Every instruction is exactly 8 bits, split into a fixed `IIIII_AAA` format:

```
  7  6  5  4  3     2  1  0
 [  instruction  ] [ mode ]
  I  I  I  I  I     A  A  A
```

- **IIIII** (bits 7-3): instruction select, 32 possible opcodes
- **AAA** (bits 2-0): addressing mode, 8 possible modes

This rigid split means decode is just wiring — route the top 5 bits to the
instruction decode tree and the bottom 3 bits to the addressing mode logic.
No bit-shuffling, no overlapping fields.

## Addressing Modes

| AAA | Mode | Operand nibbles | Operand source |
|-----|------|:-:|----------------|
| 000 | Implicit | 0 | Operation is on the accumulator or implied by the instruction (NOP, RTS, etc.) |
| 001 | Immediate | 1 | M+2 is a 4-bit literal value |
| 010 | Zero page | 2 | M+2, M+3 form an 8-bit address into page zero (first 256 nibbles) |
| 011 | Absolute | 3 | M+2, M+3, M+4 form a full 12-bit address |
| 100 | Zero page, X | 2 | M+2, M+3 form an 8-bit ZP address, added to X at execute time |
| 101 | Absolute, X | 3 | M+2, M+3, M+4 form a 12-bit address, added to X at execute time |
| 110 | Indirect | 2 | M+2, M+3 form an 8-bit ZP address; memory at that address holds the effective 12-bit target |
| 111 | Indirect with offset | 3 | M+2, M+3 form an 8-bit ZP address pointing to a 12-bit base; M+4 is a 4-bit signed offset (-8..+7) added to the target |

Indirect addressing always goes through zero page. This keeps the pointer
address to 2 nibbles, leaving room for the offset nibble in mode 111.

## Fetch Cycle

The sliding-window memory returns 3 nibbles per read. The fetch phase is
**always** two reads, unconditionally, with a hardwired PC += 2 in between:

```
Fetch 1:  read mem[PC]     -> get M, M+1, M+2     (opcode + first operand nibble)
          PC += 2           (hardwired, unconditional)
Fetch 2:  read mem[PC]     -> get M+2, M+3, M+4   (remaining operand nibbles)
```

After both fetches, the microcode has all 5 nibbles in registers. M+2
appears in both fetches — that's fine, it's latched from whichever path
needs it.

There is **no variability** in the fetch phase. Every instruction, every
addressing mode, always two reads, always PC += 2. The decode and execute
logic never has to ask "do I need to fetch more?"

## PC Control

The program counter has exactly two modes of operation:

1. **Hardwired +2** during fetch (always happens, no control logic)
2. **Parallel load** during execute (when the instruction isn't implicit)

After the fetch phase, PC is sitting at M+2. What happens next depends on
the addressing mode:

| Mode | Operand nibbles | PC action during execute |
|------|:-:|------|
| Implicit | 0 | Nothing. PC is already at the next opcode. |
| Immediate | 1 | Load PC with M+3 |
| Zero page | 2 | Load PC with M+4 |
| Absolute | 3 | Load PC with M+5 |
| Jump/branch | -- | Load PC with target address |

For implicit instructions (NOP, flag ops, accumulator shifts, RTS, etc.),
the PC is already correct after fetch — the machine just reasserts the
address bus and starts the next instruction. Zero extra work.

For everything else, the PC gets loaded with a new value. From the
hardware's perspective, "skip past a 3-nibble operand" and "jump to a
target address" are the same operation: write a value into PC. One relay
decides whether execute writes to PC or not.

## Indirect Addressing Detail

Indirect and indirect-with-offset are the only modes that require a **third
memory access** during execute:

```
Indirect (110):
  1. Take ZP address from M+2, M+3
  2. Read mem[ZP address] -> 3 nibbles = 12-bit effective address
  3. Use effective address (or load into PC for JMP)

Indirect with offset (111):
  1. Take ZP address from M+2, M+3
  2. Read mem[ZP address] -> 3 nibbles = 12-bit base address
  3. Add signed 4-bit offset from M+4 to base (-8..+7)
  4. Use result as effective address
```

The indirect-with-offset mode is useful for struct-like access: store a
pointer in zero page, then reach nearby fields with small immediate offsets.
No index register needed for the offset — it's baked into the instruction.

```
; example: pointer at ZP $10, access fields at offset 0, 1, 2
LDA ($10)+0     ; load field 0
ADD ($10)+1     ; add field 1
STA ($10)+2     ; store to field 2
```

## Microcode Implementation

Each opcode gets one fusible-link microcode board — a two-sided PCB where
traces at grid crossings can be burned open with high voltage to program
zeros (intact trace = 1, burned trace = 0). Essentially a hand-blown PROM,
same concept as the System/360's TROS cards.

Board inputs: clock counter (micro-step number).
Board outputs: control lines + DONE signal.

A hardwired sequencer counts micro-steps. The active microcode board asserts
DONE on its last step, resetting the sequencer back to fetch. Simple
instructions (NOP) finish in one step; indirect addressing takes several.
No fixed step count — the board decides when it's done.

The fetch sequence (two reads + PC += 2) is hardwired on the control board,
not microcoded. The PC increment is just wiring. Microcode boards only
control the execute phase.

## Proposed Opcodes

22 instructions. Each one is a microcode board.

### Core — Load / Store (4 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 00000 | LDA | Load accumulator from memory |
| 00001 | STA | Store accumulator to memory |
| 00010 | LDX | Load X register from memory |
| 00011 | STX | Store X register to memory |

### Arithmetic / Logic (5 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 00100 | ADD | Add to accumulator (with carry) |
| 00101 | SUB | Subtract from accumulator (with borrow) |
| 00110 | AND | Bitwise AND with accumulator |
| 00111 | ORA | Bitwise OR with accumulator |
| 01000 | CMP | Compare (subtract without storing, flags only) |

### Shifts (2 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 01001 | ASL | Arithmetic shift left (accumulator or memory) |
| 01010 | LSR | Logical shift right (accumulator or memory) |

### Branches (4 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 01011 | BEQ | Branch if zero flag set |
| 01100 | BNE | Branch if zero flag clear |
| 01101 | BCS | Branch if carry flag set |
| 01110 | BCC | Branch if carry flag clear |

### Control Flow (3 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 01111 | JMP | Unconditional jump |
| 10000 | JSR | Jump to subroutine (push return address) |
| 10001 | RTS | Return from subroutine (pull return address) |

### Flags (2 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 10010 | CLC | Clear carry flag |
| 10011 | SEC | Set carry flag |

### System (2 boards)

| IIIII | Mnemonic | Description |
|-------|----------|-------------|
| 10100 | NOP | No operation (DONE immediately) |
| 10101 | HLT | Halt the machine |

### Unassigned

IIIII 10110 through 11111 (10 slots) are reserved. Available for future
use or for reclaiming invalid addressing mode combinations as bonus
instructions.

### Valid Addressing Modes per Instruction

Not every instruction supports every mode. This table shows which
combinations are meaningful:

| Instruction | IMP | IMM | ZP | ABS | ZP,X | ABS,X | (ZP) | (ZP)+off |
|-------------|:---:|:---:|:--:|:---:|:----:|:-----:|:----:|:--------:|
| LDA         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| STA         |     |     | x  |  x  |  x   |   x   |  x   |    x     |
| LDX         |     |  x  | x  |  x  |      |       |  x   |    x     |
| STX         |     |     | x  |  x  |      |       |  x   |    x     |
| ADD         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| SUB         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| AND         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| ORA         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| CMP         |     |  x  | x  |  x  |  x   |   x   |  x   |    x     |
| ASL         |  x  |     | x  |  x  |      |       |      |          |
| LSR         |  x  |     | x  |  x  |      |       |      |          |
| BEQ         |     |  x  |    |  x  |      |       |      |          |
| BNE         |     |  x  |    |  x  |      |       |      |          |
| BCS         |     |  x  |    |  x  |      |       |      |          |
| BCC         |     |  x  |    |  x  |      |       |      |          |
| JMP         |     |     |    |  x  |      |       |  x   |          |
| JSR         |     |     |    |  x  |      |       |      |          |
| RTS         |  x  |     |    |     |      |       |      |          |
| CLC         |  x  |     |    |     |      |       |      |          |
| SEC         |  x  |     |    |     |      |       |      |          |
| NOP         |  x  |     |    |     |      |       |      |          |
| HLT         |  x  |     |    |     |      |       |      |          |

Branches use immediate mode for a 4-bit signed relative offset (-8..+7
nibbles from PC) and absolute mode for a full 12-bit target address.

Invalid combinations (blank cells) are treated as NOP.

## Not All Combinations Are Valid

With 22 instructions x 8 addressing modes = 176 possible encodings, plus
80 more from the 10 unassigned opcode slots, many combinations are
meaningless. Invalid combinations are treated as NOP (safe, simple, no
extra logic needed).

## Open Questions

- **Register set**: A/X plus flags — is that enough? A second index
  register (Y) would cost 2 more microcode boards (LDY, STY) and extra
  register hardware.
- **Branch range**: Immediate-mode branches give -8..+7 nibble range.
  Absolute-mode branches cover the full address space but cost 3 operand
  nibbles. Is short-range branching useful enough, or should branches
  always be absolute?
- **Stack**: JSR/RTS imply a stack. Hardware stack (dedicated pointer +
  small RAM region) or software-managed (fixed address in zero page)?
- **BCD control**: SED/CLD to switch the ALU between binary and BCD mode,
  or hardwire a toggle switch?
- **Illegal opcode reuse**: Which invalid mode/instruction combos are worth
  reclaiming as bonus instructions?
- **Physical form factor**: Grandfather clock style enclosure — vertical
  card cage with backplane, nixie display at top, tape reader at working
  height, power supply in the base.
