from __future__ import annotations
from .lexer import Token, TokenType, UNITS
from .ast_nodes import (
    Program, Component, Testbench, Import,
    PortDecl, WireDecl, WireDef, RelayDecl, DiodeDecl,
    CapacitorDecl, FuseDecl, BusDecl,
    ConnectStmt, InstanceStmt, InstanceArg, TimingStmt, TimingParam,
    DriveStmt, WaitStmt, AssertStmt, CheckStmt, VectorStmt,
    SignalAssign, SignalExpect, ForLoop, NetRef,
)
from .errors import ParseError, SourceLocation


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def loc(self) -> SourceLocation:
        return self.current().loc

    def current(self) -> Token:
        return self.tokens[self.pos]

    def at_end(self) -> bool:
        return self.current().type == TokenType.EOF

    def check(self, *types: TokenType) -> bool:
        return self.current().type in types

    def match(self, *types: TokenType) -> Token | None:
        if self.current().type in types:
            tok = self.current()
            self.pos += 1
            return tok
        return None

    def expect(self, tt: TokenType) -> Token:
        tok = self.current()
        if tok.type != tt:
            raise ParseError(
                f"Expected {tt.name}, got {tok.type.name} ({tok.value!r})",
                tok.loc,
            )
        self.pos += 1
        return tok

    def expect_ident(self) -> str:
        return self.expect(TokenType.IDENT).value

    def expect_number(self) -> float:
        tok = self.expect(TokenType.NUMBER)
        if "." in tok.value:
            return float(tok.value)
        return int(tok.value)

    def expect_unit(self) -> str:
        tok = self.current()
        if tok.type == TokenType.IDENT and tok.value in UNITS:
            self.pos += 1
            return tok.value
        raise ParseError(f"Expected time unit (ms/us/ns/ticks), got {tok.value!r}", tok.loc)

    # --- Top level ---

    def parse_program(self) -> Program:
        items = []
        while not self.at_end():
            if self.check(TokenType.COMPONENT):
                items.append(self.parse_component())
            elif self.check(TokenType.TESTBENCH):
                items.append(self.parse_testbench())
            elif self.check(TokenType.IMPORT):
                items.append(self.parse_import())
            else:
                raise ParseError(
                    f"Expected 'component', 'testbench', or 'import', got {self.current().value!r}",
                    self.loc(),
                )
        return Program(items=items)

    def parse_import(self) -> Import:
        loc = self.loc()
        self.expect(TokenType.IMPORT)
        path = self.expect(TokenType.STRING).value
        self.expect(TokenType.SEMICOLON)
        return Import(path=path, loc=loc)

    def parse_component(self) -> Component:
        loc = self.loc()
        self.expect(TokenType.COMPONENT)
        name = self.expect_ident()
        self.expect(TokenType.LBRACE)
        members = []
        while not self.check(TokenType.RBRACE):
            result = self.parse_member()
            if isinstance(result, list):
                members.extend(result)
            else:
                members.append(result)
        self.expect(TokenType.RBRACE)
        return Component(name=name, members=members, loc=loc)

    def parse_member(self):
        if self.check(TokenType.PORT):
            return self.parse_port_decl()
        elif self.check(TokenType.WIRE):
            return self.parse_wire_decl()
        elif self.check(TokenType.RELAY):
            return self.parse_relay_decl()
        elif self.check(TokenType.DIODE):
            return self.parse_diode_decl()
        elif self.check(TokenType.CAPACITOR):
            return self.parse_capacitor_decl()
        elif self.check(TokenType.FUSE):
            return self.parse_fuse_decl()
        elif self.check(TokenType.BUS):
            return self.parse_bus_decl()
        elif self.check(TokenType.CONNECT):
            return self.parse_connect_stmt()
        elif self.check(TokenType.INSTANCE):
            return self.parse_instance_stmt()
        elif self.check(TokenType.TIMING):
            return self.parse_timing_stmt()
        elif self.check(TokenType.ASSERT):
            return self.parse_assert_stmt()
        else:
            raise ParseError(
                f"Expected member declaration, got {self.current().value!r}",
                self.loc(),
            )

    # --- Declarations ---

    def parse_port_decl(self) -> PortDecl:
        loc = self.loc()
        self.expect(TokenType.PORT)
        direction = self.expect(TokenType.IN, TokenType.OUT, TokenType.INOUT).value
        port_defs = [self._parse_port_def()]
        while self.match(TokenType.COMMA):
            port_defs.append(self._parse_port_def())
        self.expect(TokenType.SEMICOLON)
        # Build names list for backward compatibility (expand bus ports)
        names = []
        for pd in port_defs:
            if pd.width is not None:
                for i in range(pd.width):
                    names.append(f"{pd.name}[{i}]")
            else:
                names.append(pd.name)
        return PortDecl(direction=direction, names=names,
                        port_defs=port_defs, loc=loc)

    def _parse_port_def(self):
        from .ast_nodes import PortDef
        name = self.expect_ident()
        width = None
        if self.match(TokenType.LBRACKET):
            width = int(self.expect_number())
            self.expect(TokenType.RBRACKET)
        return PortDef(name=name, width=width)

    def expect(self, *types: TokenType) -> Token:
        tok = self.current()
        if tok.type not in types:
            expected = " or ".join(t.name for t in types)
            raise ParseError(
                f"Expected {expected}, got {tok.type.name} ({tok.value!r})",
                tok.loc,
            )
        self.pos += 1
        return tok

    def parse_wire_decl(self) -> WireDecl:
        loc = self.loc()
        self.expect(TokenType.WIRE)
        wires = [self._parse_wire_def()]
        while self.match(TokenType.COMMA):
            wires.append(self._parse_wire_def())
        self.expect(TokenType.SEMICOLON)
        return WireDecl(wires=wires, loc=loc)

    def _parse_wire_def(self) -> WireDef:
        name = self.expect_ident()
        init = None
        if self.match(TokenType.EQUALS):
            init = self.expect(TokenType.HIGH, TokenType.LOW, TokenType.FLOAT).value
        return WireDef(name=name, init=init)

    def parse_relay_decl(self) -> RelayDecl:
        loc = self.loc()
        self.expect(TokenType.RELAY)
        # Optional pole count: relay(4) R1, R2;
        poles = 2
        if self.match(TokenType.LPAREN):
            poles = int(self.expect_number())
            self.expect(TokenType.RPAREN)
        names = [self.expect_ident()]
        while self.match(TokenType.COMMA):
            names.append(self.expect_ident())
        self.expect(TokenType.SEMICOLON)
        return RelayDecl(names=names, poles=poles, loc=loc)

    def parse_diode_decl(self) -> DiodeDecl:
        loc = self.loc()
        self.expect(TokenType.DIODE)
        names = [self.expect_ident()]
        while self.match(TokenType.COMMA):
            names.append(self.expect_ident())
        self.expect(TokenType.SEMICOLON)
        return DiodeDecl(names=names, loc=loc)

    def parse_capacitor_decl(self) -> CapacitorDecl:
        loc = self.loc()
        self.expect(TokenType.CAPACITOR)
        names = [self.expect_ident()]
        decay = None
        if self.match(TokenType.LPAREN):
            self.expect(TokenType.DECAY)
            self.expect(TokenType.EQUALS)
            decay = self.expect_number()
            self.expect_unit()  # consume but we store as ms
            self.expect(TokenType.RPAREN)
        while self.match(TokenType.COMMA):
            names.append(self.expect_ident())
        self.expect(TokenType.SEMICOLON)
        return CapacitorDecl(names=names, decay=decay, loc=loc)

    def parse_fuse_decl(self) -> FuseDecl:
        loc = self.loc()
        self.expect(TokenType.FUSE)
        names = [self.expect_ident()]
        state = "INTACT"
        if self.match(TokenType.EQUALS):
            state = self.expect(TokenType.INTACT, TokenType.BLOWN).value
        while self.match(TokenType.COMMA):
            names.append(self.expect_ident())
        self.expect(TokenType.SEMICOLON)
        return FuseDecl(names=names, state=state, loc=loc)

    def parse_bus_decl(self) -> BusDecl | list[BusDecl]:
        loc = self.loc()
        self.expect(TokenType.BUS)
        buses = [self._parse_single_bus(loc)]
        while self.match(TokenType.COMMA):
            buses.append(self._parse_single_bus(loc))
        self.expect(TokenType.SEMICOLON)
        return buses[0] if len(buses) == 1 else buses

    def _parse_single_bus(self, loc) -> BusDecl:
        name = self.expect_ident()
        self.expect(TokenType.LBRACKET)
        width = int(self.expect_number())
        self.expect(TokenType.RBRACKET)
        return BusDecl(name=name, width=width, loc=loc)

    # --- Statements ---

    def parse_connect_stmt(self) -> ConnectStmt:
        loc = self.loc()
        self.expect(TokenType.CONNECT)
        source = self.parse_net_ref()
        if self.match(TokenType.DIODE_ARROW):
            has_diode = True
        else:
            self.expect(TokenType.ARROW)
            has_diode = False
        target = self.parse_net_ref()
        self.expect(TokenType.SEMICOLON)
        return ConnectStmt(source=source, target=target, has_diode=has_diode, loc=loc)

    def parse_net_ref(self) -> NetRef:
        loc = self.loc()
        parts = [self.expect_ident()]
        while self.match(TokenType.DOT):
            parts.append(self.expect_ident())
        index = None
        end_index = None
        if self.match(TokenType.LBRACKET):
            index = int(self.expect_number())
            if self.match(TokenType.DOTDOT):
                end_index = int(self.expect_number())
            self.expect(TokenType.RBRACKET)
        return NetRef(parts=parts, index=index, end_index=end_index, loc=loc)

    def parse_instance_stmt(self) -> InstanceStmt:
        loc = self.loc()
        self.expect(TokenType.INSTANCE)
        name = self.expect_ident()
        count = None
        if self.match(TokenType.LBRACKET):
            count = int(self.expect_number())
            self.expect(TokenType.RBRACKET)
        self.expect(TokenType.EQUALS)
        component = self.expect_ident()
        args = []
        if self.match(TokenType.LPAREN):
            if not self.check(TokenType.RPAREN):
                args.append(self._parse_instance_arg())
                while self.match(TokenType.COMMA):
                    args.append(self._parse_instance_arg())
            self.expect(TokenType.RPAREN)
        self.expect(TokenType.SEMICOLON)
        return InstanceStmt(name=name, component=component, args=args, count=count, loc=loc)

    def _parse_instance_arg(self) -> InstanceArg:
        name = self.expect_ident()
        self.expect(TokenType.EQUALS)
        value = self.parse_net_ref()
        return InstanceArg(name=name, value=value)

    def parse_timing_stmt(self) -> TimingStmt:
        loc = self.loc()
        self.expect(TokenType.TIMING)
        name = self.expect_ident()
        self.expect(TokenType.LBRACE)
        params = []
        while not self.check(TokenType.RBRACE):
            kind = self.expect_ident()
            if kind not in ("energize", "deenergize", "bounce"):
                raise ParseError(f"Expected timing parameter, got {kind!r}", self.loc())
            self.expect(TokenType.EQUALS)
            value = self.expect_number()
            unit = self.expect_unit()
            self.expect(TokenType.SEMICOLON)
            params.append(TimingParam(kind=kind, value=value, unit=unit))
        self.expect(TokenType.RBRACE)
        return TimingStmt(relay_name=name, params=params, loc=loc)

    # --- Testbench ---

    def parse_testbench(self) -> Testbench:
        loc = self.loc()
        self.expect(TokenType.TESTBENCH)
        name = self.expect_ident()
        self.expect(TokenType.FOR)
        # 'for' is a keyword, target is next ident
        target = self.expect_ident()
        self.expect(TokenType.LBRACE)
        stmts = []
        while not self.check(TokenType.RBRACE):
            stmts.append(self.parse_tb_statement())
        self.expect(TokenType.RBRACE)
        return Testbench(name=name, target=target, statements=stmts, loc=loc)

    def parse_tb_statement(self):
        if self.check(TokenType.INSTANCE):
            return self.parse_instance_stmt()
        elif self.check(TokenType.DRIVE):
            return self.parse_drive_stmt()
        elif self.check(TokenType.WAIT):
            return self.parse_wait_stmt()
        elif self.check(TokenType.ASSERT):
            return self.parse_assert_stmt()
        elif self.check(TokenType.CHECK):
            return self.parse_check_stmt()
        elif self.check(TokenType.VECTOR):
            return self.parse_vector_stmt()
        elif self.check(TokenType.FOR):
            return self.parse_for_loop()
        else:
            raise ParseError(
                f"Expected testbench statement, got {self.current().value!r}",
                self.loc(),
            )

    def parse_drive_stmt(self) -> DriveStmt:
        loc = self.loc()
        self.expect(TokenType.DRIVE)
        net = self.parse_net_ref()
        self.expect(TokenType.EQUALS)
        value = self.expect(TokenType.HIGH, TokenType.LOW, TokenType.FLOAT).value
        self.expect(TokenType.SEMICOLON)
        return DriveStmt(net=net, value=value, loc=loc)

    def parse_wait_stmt(self) -> WaitStmt:
        loc = self.loc()
        self.expect(TokenType.WAIT)
        duration = self.expect_number()
        unit = self.expect_unit()
        self.expect(TokenType.SEMICOLON)
        return WaitStmt(duration=duration, unit=unit, loc=loc)

    def parse_assert_stmt(self) -> AssertStmt:
        loc = self.loc()
        self.expect(TokenType.ASSERT)
        net = self.parse_net_ref()
        self.expect(TokenType.EQEQ)
        expected = self.expect(TokenType.HIGH, TokenType.LOW, TokenType.FLOAT).value
        at_time = None
        at_unit = None
        if self.match(TokenType.AT):
            at_time = self.expect_number()
            at_unit = self.expect_unit()
        self.expect(TokenType.SEMICOLON)
        return AssertStmt(net=net, expected=expected, at_time=at_time, at_unit=at_unit, loc=loc)

    def parse_check_stmt(self) -> CheckStmt:
        loc = self.loc()
        self.expect(TokenType.CHECK)
        net = self.parse_net_ref()
        self.expect(TokenType.SEMICOLON)
        return CheckStmt(net=net, loc=loc)

    def parse_vector_stmt(self) -> VectorStmt:
        loc = self.loc()
        self.expect(TokenType.VECTOR)
        # Parse inputs
        self.expect(TokenType.LBRACE)
        inputs = []
        if not self.check(TokenType.RBRACE):
            inputs.append(self._parse_signal_assign())
            while self.match(TokenType.COMMA):
                inputs.append(self._parse_signal_assign())
        self.expect(TokenType.RBRACE)
        self.expect(TokenType.ARROW)
        # Parse expected outputs
        self.expect(TokenType.LBRACE)
        outputs = []
        if not self.check(TokenType.RBRACE):
            outputs.append(self._parse_signal_expect())
            while self.match(TokenType.COMMA):
                outputs.append(self._parse_signal_expect())
        self.expect(TokenType.RBRACE)
        self.expect(TokenType.SEMICOLON)
        return VectorStmt(inputs=inputs, outputs=outputs, loc=loc)

    def _parse_signal_assign(self) -> SignalAssign:
        name = self.expect_ident()
        self.expect(TokenType.EQUALS)
        value = self.expect(TokenType.NUMBER).value
        return SignalAssign(name=name, value=value)

    def _parse_signal_expect(self) -> SignalExpect:
        name = self.expect_ident()
        self.expect(TokenType.EQEQ)
        tok = self.current()
        if tok.type == TokenType.NUMBER:
            self.pos += 1
            return SignalExpect(name=name, expected=tok.value)
        elif tok.type == TokenType.FLOAT:
            self.pos += 1
            return SignalExpect(name=name, expected="Z")
        else:
            raise ParseError(f"Expected 0, 1, or FLOAT, got {tok.value!r}", tok.loc)

    def parse_for_loop(self) -> ForLoop:
        loc = self.loc()
        self.expect(TokenType.FOR)
        var = self.expect_ident()
        # expect 'in' keyword
        self.expect(TokenType.IN)
        start = int(self.expect_number())
        self.expect(TokenType.DOTDOT)
        end = int(self.expect_number())
        self.expect(TokenType.LBRACE)
        body = []
        while not self.check(TokenType.RBRACE):
            body.append(self.parse_tb_statement())
        self.expect(TokenType.RBRACE)
        return ForLoop(var=var, start=start, end=end, body=body, loc=loc)


def parse(source: str, filename: str = "<input>") -> Program:
    """Convenience function: lex + parse in one call."""
    from .lexer import Lexer
    tokens = Lexer(source, filename).tokenize()
    return Parser(tokens).parse_program()
