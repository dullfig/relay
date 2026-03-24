"""Test the relay computer assembler."""
import pytest
from relaydsl.asm.assembler import Assembler, assemble, INSTRUCTIONS, MODE_BITS


class TestOpcodeEncoding:
    def test_nop(self):
        asm, errors = assemble("NOP")
        assert not errors, errors
        assert len(asm.instructions) == 1
        inst = asm.instructions[0]
        # NOP = IIIII=11100, AAA=000 (implicit)
        expected = (0b11100 << 3) | 0b000
        assert inst.opcode_byte == expected
        assert inst.nibbles == [expected >> 4, expected & 0xF]

    def test_hlt(self):
        asm, errors = assemble("HLT")
        assert not errors, errors
        inst = asm.instructions[0]
        expected = (0b11101 << 3) | 0b000
        assert inst.opcode_byte == expected

    def test_inx(self):
        asm, errors = assemble("INX")
        assert not errors, errors
        inst = asm.instructions[0]
        expected = (0b11010 << 3) | 0b000
        assert inst.opcode_byte == expected
        assert inst.size == 2  # implicit, no operand

    def test_dex(self):
        asm, errors = assemble("DEX")
        assert not errors, errors
        inst = asm.instructions[0]
        expected = (0b11011 << 3) | 0b000
        assert inst.opcode_byte == expected

    def test_lda_immediate(self):
        asm, errors = assemble("LDA #$5")
        assert not errors, errors
        inst = asm.instructions[0]
        # LDA = 00000, IMM = 001
        expected_op = (0b00000 << 3) | 0b001
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [5]
        assert inst.size == 3  # 2 opcode + 1 operand

    def test_lda_zero_page(self):
        asm, errors = assemble("LDA $20")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b010  # ZP
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [2, 0]  # $20 = 2,0
        assert inst.size == 4

    def test_lda_absolute(self):
        asm, errors = assemble("LDA $100")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b011  # ABS
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [1, 0, 0]  # $100 = 1,0,0
        assert inst.size == 5

    def test_sta_zero_page(self):
        asm, errors = assemble("STA $FF")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00001 << 3) | 0b010  # STA ZP
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [0xF, 0xF]

    def test_indexed_zero_page(self):
        asm, errors = assemble("LDA $20,X")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b100  # ZP,X
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [2, 0]

    def test_indexed_absolute(self):
        asm, errors = assemble("LDA $100,X")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b101  # ABS,X
        assert inst.opcode_byte == expected_op

    def test_indirect(self):
        asm, errors = assemble("LDA ($30)")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b110  # IND
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [3, 0]

    def test_indirect_with_offset(self):
        asm, errors = assemble("LDA ($30)+5")
        assert not errors, errors
        inst = asm.instructions[0]
        expected_op = (0b00000 << 3) | 0b111  # INDOFF
        assert inst.opcode_byte == expected_op
        assert inst.operand_nibbles == [3, 0, 5]


class TestLabels:
    def test_forward_label(self):
        source = """
            JMP target
            NOP
        target:
            HLT
        """
        asm, errors = assemble(source)
        assert not errors, errors
        assert len(asm.instructions) == 3
        jmp = asm.instructions[0]
        hlt = asm.instructions[2]
        # JMP should target the address of HLT
        addr = hlt.address
        expected_nibbles = [(addr >> 8) & 0xF, (addr >> 4) & 0xF, addr & 0xF]
        assert jmp.operand_nibbles == expected_nibbles

    def test_backward_label(self):
        source = """
        loop:
            DEC $30
            BNE loop
        """
        asm, errors = assemble(source)
        assert not errors, errors
        assert 'loop' in asm.symbols

    def test_duplicate_label_error(self):
        source = """
        foo: NOP
        foo: HLT
        """
        asm, errors = assemble(source)
        assert len(errors) == 1
        assert "Duplicate" in str(errors[0])


class TestDirectives:
    def test_org(self):
        source = """
        .org $100
        NOP
        """
        asm, errors = assemble(source)
        assert not errors, errors
        assert asm.instructions[0].address == 0x100

    def test_byte(self):
        source = """
        .byte $A $B $C
        """
        asm, errors = assemble(source)
        assert not errors, errors
        assert asm.raw_data[0] == 0xA
        assert asm.raw_data[1] == 0xB
        assert asm.raw_data[2] == 0xC

    def test_ascii(self):
        source = """
        .ascii "HI"
        """
        asm, errors = assemble(source)
        assert not errors, errors
        # H = 0x48, I = 0x49
        assert asm.raw_data[0] == 4
        assert asm.raw_data[1] == 8
        assert asm.raw_data[2] == 4
        assert asm.raw_data[3] == 9

    def test_equ(self):
        source = """
        .equ FLEX $FF0
        STA FLEX
        """
        asm, errors = assemble(source)
        assert not errors, errors
        inst = asm.instructions[0]
        # $FF0 > $FF so absolute mode
        assert inst.operand_nibbles == [0xF, 0xF, 0x0]


class TestInvalidModes:
    def test_sta_immediate_invalid(self):
        source = "STA #5"
        asm, errors = assemble(source)
        assert any("does not support" in str(e) for e in errors)

    def test_rts_with_operand(self):
        """RTS only supports implicit."""
        source = "RTS $100"
        asm, errors = assemble(source)
        assert any("does not support" in str(e) for e in errors)


class TestPrograms:
    def test_hello_world(self):
        """Assemble the hello world program."""
        import os
        filepath = os.path.join(os.path.dirname(__file__),
                                "..", "programs", "hello.asm")
        with open(filepath) as f:
            source = f.read()
        asm, errors = assemble(source)
        assert not errors, [str(e) for e in errors]
        print(f"\n=== Hello World Listing ===")
        print(asm.get_listing())
        print(f"\n=== Hex Dump ===")
        print(asm.get_hex_dump())

    def test_simple_loop(self):
        """A simple countdown loop."""
        source = """
        .org $100
                LDA #9          ; start at 9
                STA $00         ; store counter
        loop:   DEC $00         ; decrement
                BNE loop        ; loop until zero
                HLT
        """
        asm, errors = assemble(source)
        assert not errors, [str(e) for e in errors]
        print(f"\n=== Countdown Loop ===")
        print(asm.get_listing())
        # Verify the loop structure
        assert len(asm.instructions) == 5
        assert asm.instructions[0].size == 3   # LDA #9
        assert asm.instructions[1].size == 4   # STA $00
        assert asm.instructions[2].size == 4   # DEC $00
        # BNE should branch back to loop

    def test_instruction_count(self):
        """Verify all 30 mnemonics are recognized."""
        all_mnemonics = [
            'LDA', 'STA', 'LDX', 'STX',
            'ADD', 'SUB', 'AND', 'ORA', 'CMP', 'INC', 'DEC',
            'ASL', 'LSR', 'ROL', 'ROR',
            'BEQ', 'BNE', 'BCS', 'BCC',
            'JMP', 'JSR', 'RTS',
            'CLC', 'SEC', 'CLD', 'SED',
            'INX', 'DEX',
            'NOP', 'HLT',
        ]
        assert len(all_mnemonics) == 30
        assert len(INSTRUCTIONS) == 30
        for m in all_mnemonics:
            assert m in INSTRUCTIONS, f"Missing mnemonic: {m}"
