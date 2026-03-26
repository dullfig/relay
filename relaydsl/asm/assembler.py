"""
Assembler for the relay computer ISA.

Reads assembly source, produces nibble images for DRAM loading.

Syntax:
    LDA #$5         ; immediate (1 nibble literal)
    LDA $20         ; zero page (2 nibble address, < $100)
    LDA $100        ; absolute (3 nibble address, >= $100)
    LDA $20,X       ; zero page indexed
    LDA $100,X      ; absolute indexed
    LDA ($20)       ; indirect (ZP pointer)
    LDA ($20)+3     ; indirect with signed offset
    ASL             ; implicit (accumulator)
    BEQ label       ; branch to label (assembler picks immediate or absolute)
    BEQ *-4         ; relative branch (PC-relative)

Labels:
    loop:  DEC $30
           BNE loop

Directives:
    .org $100       ; set assembly address
    .byte $A $B $C  ; raw nibble data
    .ascii "HELLO"  ; ASCII string as nibble pairs
    .equ NAME $FF0  ; named constant
"""
from __future__ import annotations
from dataclasses import dataclass, field


# Instruction table: mnemonic -> (IIIII bits, valid modes set)
INSTRUCTIONS = {
    'LDA': (0b00000, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'STA': (0b00001, {'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'LDX': (0b00010, {'imm', 'zp', 'abs', 'ind', 'indoff'}),
    'STX': (0b00011, {'zp', 'abs', 'ind', 'indoff'}),
    'ADD': (0b00100, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'SUB': (0b00101, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'AND': (0b00110, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'ORA': (0b00111, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'CMP': (0b01000, {'imm', 'zp', 'abs', 'zpx', 'absx', 'ind', 'indoff'}),
    'INC': (0b01001, {'imp', 'zp', 'abs'}),
    'DEC': (0b01010, {'imp', 'zp', 'abs'}),
    'ASL': (0b01011, {'imp', 'zp', 'abs'}),
    'LSR': (0b01100, {'imp', 'zp', 'abs'}),
    'ROL': (0b01101, {'imp', 'zp', 'abs'}),
    'ROR': (0b01110, {'imp', 'zp', 'abs'}),
    'BEQ': (0b01111, {'imm', 'abs'}),
    'BNE': (0b10000, {'imm', 'abs'}),
    'BCS': (0b10001, {'imm', 'abs'}),
    'BCC': (0b10010, {'imm', 'abs'}),
    'JMP': (0b10011, {'abs', 'ind'}),
    'JSR': (0b10100, {'abs'}),
    'RTS': (0b10101, {'imp'}),
    'CLC': (0b10110, {'imp'}),
    'SEC': (0b10111, {'imp'}),
    'CLD': (0b11000, {'imp'}),
    'SED': (0b11001, {'imp'}),
    'INX': (0b11010, {'imp'}),
    'DEX': (0b11011, {'imp'}),
    'NOP': (0b11100, {'imp'}),
    'HLT': (0b11101, {'imp'}),
}

# Reclaimed illegal opcodes: full 8-bit encoding -> mnemonic
# These bypass the normal IIIII_AAA split via the mode override relay.
RECLAIMED = {
    'TXA': 0b00000_000,  # LDA implicit -> transfer X to A
    'TAX': 0b00001_000,  # STA implicit -> transfer A to X
    'PHA': 0b00001_001,  # STA immediate -> push A to stack
    'PLA': 0b00010_000,  # LDX implicit -> pull A from stack
    'PHX': 0b00011_000,  # STX implicit -> push X to stack
    'PLX': 0b00011_001,  # STX immediate -> pull X from stack
}

# Addressing mode -> AAA bits
MODE_BITS = {
    'imp':    0b000,
    'imm':    0b001,
    'zp':     0b010,
    'abs':    0b011,
    'zpx':    0b100,
    'absx':   0b101,
    'ind':    0b110,
    'indoff': 0b111,
}

# Operand nibble count per mode
MODE_OPERAND_NIBBLES = {
    'imp':    0,
    'imm':    1,
    'zp':     2,
    'abs':    3,
    'zpx':    2,
    'absx':   3,
    'ind':    2,
    'indoff': 3,
}


@dataclass
class AsmError:
    line: int
    message: str

    def __str__(self):
        return f"Line {self.line}: {self.message}"


@dataclass
class Symbol:
    name: str
    value: int
    line: int


@dataclass
class Instruction:
    address: int
    opcode_byte: int      # 8-bit opcode (IIIII_AAA)
    operand_nibbles: list  # 0-3 nibbles
    source_line: int
    source_text: str
    label: str = ""

    @property
    def nibbles(self) -> list[int]:
        """Return the full instruction as a list of nibbles."""
        high = (self.opcode_byte >> 4) & 0xF
        low = self.opcode_byte & 0xF
        return [high, low] + self.operand_nibbles

    @property
    def size(self) -> int:
        return 2 + len(self.operand_nibbles)


class Assembler:
    def __init__(self):
        self.symbols: dict[str, Symbol] = {}
        self.instructions: list[Instruction] = []
        self.errors: list[AsmError] = []
        self.pc: int = 0
        self.raw_data: dict[int, int] = {}  # address -> nibble (for .byte/.ascii)

    def assemble(self, source: str) -> list[AsmError]:
        """Two-pass assembly. Returns list of errors."""
        lines = source.split('\n')

        # Pass 1: collect labels and calculate addresses
        self.pc = 0
        self._pass1(lines)

        if self.errors:
            return self.errors

        # Pass 2: resolve labels and encode
        self.pc = 0
        self.instructions = []
        self.raw_data = {}
        self._pass2(lines)

        return self.errors

    def _pass1(self, lines: list[str]):
        """First pass: collect labels, calculate instruction sizes."""
        self._pass1_mode = True  # suppress undefined symbol errors
        for line_num, line in enumerate(lines, 1):
            stripped = self._strip_comment(line).strip()
            if not stripped:
                continue

            # Check for label
            if ':' in stripped and not stripped.startswith('.'):
                label_part, rest = stripped.split(':', 1)
                label = label_part.strip()
                if label:
                    if label in self.symbols:
                        self.errors.append(AsmError(line_num,
                            f"Duplicate label '{label}'"))
                    else:
                        self.symbols[label] = Symbol(label, self.pc, line_num)
                stripped = rest.strip()
                if not stripped:
                    continue

            # Handle directives
            if stripped.startswith('.'):
                self._handle_directive_size(stripped, line_num)
                continue

            # Parse instruction to get size
            mnemonic, operand_str = self._split_instruction(stripped)
            mnem_upper = mnemonic.upper()

            # Check reclaimed opcodes first (implicit only, 2 nibbles)
            if mnem_upper in RECLAIMED:
                self.pc += 2
                continue

            if mnem_upper not in INSTRUCTIONS:
                self.errors.append(AsmError(line_num,
                    f"Unknown mnemonic '{mnemonic}'"))
                continue

            mode = self._detect_mode(mnem_upper, operand_str, line_num)
            if mode:
                size = 2 + MODE_OPERAND_NIBBLES[mode]
                self.pc += size
        self._pass1_mode = False

    def _pass2(self, lines: list[str]):
        """Second pass: encode instructions with resolved labels."""
        for line_num, line in enumerate(lines, 1):
            stripped = self._strip_comment(line).strip()
            if not stripped:
                continue

            label = ""
            if ':' in stripped and not stripped.startswith('.'):
                label_part, rest = stripped.split(':', 1)
                label = label_part.strip()
                stripped = rest.strip()
                if not stripped:
                    continue

            # Handle directives
            if stripped.startswith('.'):
                self._handle_directive(stripped, line_num)
                continue

            mnemonic, operand_str = self._split_instruction(stripped)
            mnemonic = mnemonic.upper()

            # Handle reclaimed opcodes
            if mnemonic in RECLAIMED:
                opcode_byte = RECLAIMED[mnemonic]
                inst = Instruction(
                    address=self.pc,
                    opcode_byte=opcode_byte,
                    operand_nibbles=[],
                    source_line=line_num,
                    source_text=line.strip(),
                    label=label,
                )
                self.instructions.append(inst)
                self.pc += 2
                continue

            if mnemonic not in INSTRUCTIONS:
                continue  # already reported in pass 1

            mode = self._detect_mode(mnemonic, operand_str, line_num)
            if not mode:
                continue

            instr_bits, valid_modes = INSTRUCTIONS[mnemonic]
            if mode not in valid_modes:
                self.errors.append(AsmError(line_num,
                    f"'{mnemonic}' does not support {mode} addressing"))
                continue

            # Encode opcode byte
            opcode_byte = (instr_bits << 3) | MODE_BITS[mode]

            # Encode operand
            operand_nibbles = self._encode_operand(
                mode, operand_str, mnemonic, line_num)

            inst = Instruction(
                address=self.pc,
                opcode_byte=opcode_byte,
                operand_nibbles=operand_nibbles,
                source_line=line_num,
                source_text=line.strip(),
                label=label,
            )
            self.instructions.append(inst)
            self.pc += inst.size

    def _strip_comment(self, line: str) -> str:
        """Remove ; comment from a line."""
        pos = line.find(';')
        if pos >= 0:
            return line[:pos]
        return line

    def _split_instruction(self, text: str) -> tuple[str, str]:
        """Split 'LDA #$5' into ('LDA', '#$5')."""
        parts = text.split(None, 1)
        mnemonic = parts[0]
        operand = parts[1].strip() if len(parts) > 1 else ""
        return mnemonic, operand

    def _resolve_value(self, token: str, line_num: int) -> int | None:
        """Resolve a numeric literal or label to an integer."""
        token = token.strip()
        if not token:
            return None

        # Hex: $FF or 0xFF
        if token.startswith('$'):
            try:
                return int(token[1:], 16)
            except ValueError:
                self.errors.append(AsmError(line_num,
                    f"Invalid hex value '{token}'"))
                return None

        if token.startswith('0x') or token.startswith('0X'):
            try:
                return int(token, 16)
            except ValueError:
                self.errors.append(AsmError(line_num,
                    f"Invalid hex value '{token}'"))
                return None

        # Decimal
        if token.isdigit() or (token.startswith('-') and token[1:].isdigit()):
            return int(token)

        # Label
        if token in self.symbols:
            return self.symbols[token].value

        # PC-relative: *-4, *+2
        if token.startswith('*'):
            offset_str = token[1:].strip()
            if offset_str:
                try:
                    offset = int(offset_str)
                    return self.pc + offset
                except ValueError:
                    pass

        # In pass 1, forward references are expected - don't error
        if getattr(self, '_pass1_mode', False):
            return None

        self.errors.append(AsmError(line_num,
            f"Undefined symbol '{token}'"))
        return None

    def _detect_mode(self, mnemonic: str, operand: str, line_num: int) -> str | None:
        """Detect addressing mode from operand syntax."""
        operand = operand.strip()

        # No operand = implicit
        if not operand:
            return 'imp'

        # Immediate: #value
        if operand.startswith('#'):
            return 'imm'

        # Indirect with offset: ($XX)+N
        if operand.startswith('(') and ')+' in operand:
            return 'indoff'
        if operand.startswith('(') and ')-' in operand:
            return 'indoff'

        # Indirect: ($XX)
        if operand.startswith('(') and operand.endswith(')'):
            return 'ind'

        # Indexed: addr,X
        if operand.upper().endswith(',X'):
            addr_str = operand[:-2].strip()
            val = self._resolve_value(addr_str, line_num)
            if val is not None:
                return 'absx' if val > 0xFF else 'zpx'
            return 'absx'  # assume absolute for forward refs (safe, larger)

        # Control flow always uses absolute (JMP/JSR/branches)
        if mnemonic in ('JMP', 'JSR'):
            return 'abs'

        # Branches: check if relative offset fits in immediate
        if mnemonic in ('BEQ', 'BNE', 'BCS', 'BCC'):
            val = self._resolve_value(operand, line_num)
            if val is not None:
                offset = val - (self.pc + 3)  # PC after this instruction
                if -8 <= offset <= 7:
                    return 'imm'
            return 'abs'

        # Plain address: ZP if < $100, absolute otherwise
        val = self._resolve_value(operand, line_num)
        if val is not None:
            return 'abs' if val > 0xFF else 'zp'

        # Unresolved (forward label) - assume absolute (safe)
        return 'abs'

    def _encode_operand(self, mode: str, operand: str,
                         mnemonic: str, line_num: int) -> list[int]:
        """Encode operand into nibbles."""
        operand = operand.strip()

        if mode == 'imp':
            return []

        if mode == 'imm':
            val_str = operand.lstrip('#')
            val = self._resolve_value(val_str, line_num)
            if val is None:
                return [0]
            # For branches, encode as signed 4-bit offset
            if mnemonic in ('BEQ', 'BNE', 'BCS', 'BCC'):
                target = val
                offset = target - (self.pc + 3)
                if offset < 0:
                    offset = offset & 0xF  # two's complement in 4 bits
                return [offset & 0xF]
            return [val & 0xF]

        if mode == 'zp':
            val = self._resolve_value(operand, line_num)
            if val is None:
                return [0, 0]
            return [(val >> 4) & 0xF, val & 0xF]

        if mode == 'abs':
            # For branches, resolve label to absolute address
            if mnemonic in ('BEQ', 'BNE', 'BCS', 'BCC', 'JMP', 'JSR'):
                val = self._resolve_value(operand, line_num)
            else:
                val = self._resolve_value(operand, line_num)
            if val is None:
                return [0, 0, 0]
            return [(val >> 8) & 0xF, (val >> 4) & 0xF, val & 0xF]

        if mode == 'zpx':
            addr_str = operand[:-2].strip()  # strip ,X
            val = self._resolve_value(addr_str, line_num)
            if val is None:
                return [0, 0]
            return [(val >> 4) & 0xF, val & 0xF]

        if mode == 'absx':
            addr_str = operand[:-2].strip()
            val = self._resolve_value(addr_str, line_num)
            if val is None:
                return [0, 0, 0]
            return [(val >> 8) & 0xF, (val >> 4) & 0xF, val & 0xF]

        if mode == 'ind':
            inner = operand.strip('()')
            val = self._resolve_value(inner, line_num)
            if val is None:
                return [0, 0]
            return [(val >> 4) & 0xF, val & 0xF]

        if mode == 'indoff':
            # ($XX)+N or ($XX)-N
            paren_end = operand.index(')')
            inner = operand[1:paren_end]
            offset_str = operand[paren_end+1:]  # +N or -N
            base_val = self._resolve_value(inner, line_num)
            offset_val = int(offset_str) if offset_str else 0
            if base_val is None:
                return [0, 0, 0]
            if offset_val < 0:
                offset_val = offset_val & 0xF
            return [(base_val >> 4) & 0xF, base_val & 0xF, offset_val & 0xF]

        return []

    def _handle_directive_size(self, text: str, line_num: int):
        """Pass 1: calculate size of directives."""
        parts = text.split()
        directive = parts[0].lower()

        if directive == '.org':
            if len(parts) > 1:
                val = self._resolve_value(parts[1], line_num)
                if val is not None:
                    self.pc = val

        elif directive == '.byte':
            self.pc += len(parts) - 1  # each value is one nibble

        elif directive == '.ascii':
            # Find quoted string
            text_after = text[len(parts[0]):].strip()
            if text_after.startswith('"') and text_after.endswith('"'):
                s = text_after[1:-1]
                self.pc += len(s) * 2  # 2 nibbles per ASCII char

        elif directive == '.equ':
            if len(parts) >= 3:
                name = parts[1]
                val = self._resolve_value(parts[2], line_num)
                if val is not None:
                    self.symbols[name] = Symbol(name, val, line_num)

    def _handle_directive(self, text: str, line_num: int):
        """Pass 2: emit data for directives."""
        parts = text.split()
        directive = parts[0].lower()

        if directive == '.org':
            if len(parts) > 1:
                val = self._resolve_value(parts[1], line_num)
                if val is not None:
                    self.pc = val

        elif directive == '.byte':
            for val_str in parts[1:]:
                val = self._resolve_value(val_str, line_num)
                if val is not None:
                    self.raw_data[self.pc] = val & 0xF
                    self.pc += 1

        elif directive == '.ascii':
            text_after = text[len(parts[0]):].strip()
            if text_after.startswith('"') and text_after.endswith('"'):
                s = text_after[1:-1]
                for ch in s:
                    code = ord(ch)
                    self.raw_data[self.pc] = (code >> 4) & 0xF
                    self.raw_data[self.pc + 1] = code & 0xF
                    self.pc += 2

        elif directive == '.equ':
            pass  # handled in pass 1

    def get_image(self, size: int = 256) -> list[int]:
        """Get the assembled nibble image."""
        image = [0] * size
        # Write instructions
        for inst in self.instructions:
            addr = inst.address
            for nibble in inst.nibbles:
                if addr < size:
                    image[addr] = nibble
                addr += 1
        # Write raw data
        for addr, nibble in self.raw_data.items():
            if addr < size:
                image[addr] = nibble
        return image

    def get_listing(self) -> str:
        """Get a human-readable listing."""
        lines = []
        for inst in self.instructions:
            nibs = ' '.join(f'{n:X}' for n in inst.nibbles)
            label_str = f"{inst.label}: " if inst.label else "  "
            addr_str = f"${inst.address:03X}"
            lines.append(f"{addr_str}  {nibs:16s}  {label_str}{inst.source_text}")
        for addr in sorted(self.raw_data.keys()):
            lines.append(f"${addr:03X}  {self.raw_data[addr]:X}")
        return '\n'.join(lines)

    def get_hex_dump(self) -> str:
        """Get a hex dump of the assembled image."""
        image = self.get_image()
        lines = []
        for row in range(0, len(image), 16):
            nibbles = image[row:row+16]
            if all(n == 0 for n in nibbles):
                continue
            hex_str = ' '.join(f'{n:X}' for n in nibbles)
            lines.append(f"${row:03X}: {hex_str}")
        return '\n'.join(lines)


def assemble(source: str) -> tuple[Assembler, list[AsmError]]:
    """Convenience: assemble source text."""
    asm = Assembler()
    errors = asm.assemble(source)
    return asm, errors
