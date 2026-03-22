from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from .errors import SourceLocation, LexError


class TokenType(Enum):
    # Keywords
    COMPONENT = auto()
    PORT = auto()
    IN = auto()
    OUT = auto()
    INOUT = auto()
    WIRE = auto()
    RELAY = auto()
    DIODE = auto()
    CAPACITOR = auto()
    FUSE = auto()
    CONNECT = auto()
    INSTANCE = auto()
    TIMING = auto()
    BUS = auto()
    TESTBENCH = auto()
    FOR = auto()
    IMPORT = auto()
    ASSERT = auto()
    DRIVE = auto()
    WAIT = auto()
    CHECK = auto()
    VECTOR = auto()
    AT = auto()
    HIGH = auto()
    LOW = auto()
    FLOAT = auto()
    INTACT = auto()
    BLOWN = auto()
    DECAY = auto()

    # Symbols
    LBRACE = auto()
    RBRACE = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    SEMICOLON = auto()
    COMMA = auto()
    DOT = auto()
    ARROW = auto()       # ->
    DIODE_ARROW = auto() # ->|
    EQUALS = auto()      # =
    EQEQ = auto()        # ==
    DOTDOT = auto()      # ..

    # Literals
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()

    # Meta
    EOF = auto()


KEYWORDS = {
    "component": TokenType.COMPONENT,
    "port": TokenType.PORT,
    "in": TokenType.IN,
    "out": TokenType.OUT,
    "inout": TokenType.INOUT,
    "wire": TokenType.WIRE,
    "relay": TokenType.RELAY,
    "diode": TokenType.DIODE,
    "capacitor": TokenType.CAPACITOR,
    "fuse": TokenType.FUSE,
    "connect": TokenType.CONNECT,
    "instance": TokenType.INSTANCE,
    "timing": TokenType.TIMING,
    "bus": TokenType.BUS,
    "testbench": TokenType.TESTBENCH,
    "for": TokenType.FOR,
    "import": TokenType.IMPORT,
    "assert": TokenType.ASSERT,
    "drive": TokenType.DRIVE,
    "wait": TokenType.WAIT,
    "check": TokenType.CHECK,
    "vector": TokenType.VECTOR,
    "at": TokenType.AT,
    "HIGH": TokenType.HIGH,
    "LOW": TokenType.LOW,
    "FLOAT": TokenType.FLOAT,
    "INTACT": TokenType.INTACT,
    "BLOWN": TokenType.BLOWN,
    "decay": TokenType.DECAY,
}

# Units are just identifiers that we recognize contextually
UNITS = {"ms", "us", "ns", "ticks"}


@dataclass
class Token:
    type: TokenType
    value: str
    loc: SourceLocation

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.loc})"


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []

    def loc(self) -> SourceLocation:
        return SourceLocation(self.filename, self.line, self.col)

    def peek(self) -> str:
        if self.pos < len(self.source):
            return self.source[self.pos]
        return "\0"

    def peek_ahead(self, n: int = 1) -> str:
        p = self.pos + n
        if p < len(self.source):
            return self.source[p]
        return "\0"

    def advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self.peek()
            if ch in " \t\r\n":
                self.advance()
            elif ch == "#":
                # Line comment
                while self.pos < len(self.source) and self.peek() != "\n":
                    self.advance()
            else:
                break

    def read_string(self) -> str:
        quote = self.advance()  # consume opening quote
        result = []
        while self.pos < len(self.source):
            ch = self.advance()
            if ch == quote:
                return "".join(result)
            if ch == "\\":
                next_ch = self.advance()
                if next_ch == "n":
                    result.append("\n")
                elif next_ch == "t":
                    result.append("\t")
                elif next_ch == "\\":
                    result.append("\\")
                elif next_ch == quote:
                    result.append(quote)
                else:
                    result.append(next_ch)
            else:
                result.append(ch)
        raise LexError("Unterminated string", self.loc())

    def read_number(self) -> str:
        start = self.pos
        has_dot = False
        while self.pos < len(self.source):
            ch = self.peek()
            if ch.isdigit():
                self.advance()
            elif ch == "." and not has_dot:
                # Only consume dot if next char is a digit (decimal number)
                # Don't consume ".." (range operator)
                if self.peek_ahead() == ".":
                    break  # it's "..", stop here
                if self.peek_ahead().isdigit():
                    has_dot = True
                    self.advance()
                else:
                    break
            else:
                break
        return self.source[start:self.pos]

    def read_identifier(self) -> str:
        start = self.pos
        while self.pos < len(self.source) and (self.peek().isalnum() or self.peek() == "_"):
            self.advance()
        return self.source[start:self.pos]

    def tokenize(self) -> list[Token]:
        self.tokens = []
        while self.pos < len(self.source):
            self.skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break

            loc = self.loc()
            ch = self.peek()

            if ch == '"' or ch == "'":
                value = self.read_string()
                self.tokens.append(Token(TokenType.STRING, value, loc))
            elif ch.isdigit():
                value = self.read_number()
                self.tokens.append(Token(TokenType.NUMBER, value, loc))
            elif ch.isalpha() or ch == "_":
                value = self.read_identifier()
                tt = KEYWORDS.get(value, TokenType.IDENT)
                self.tokens.append(Token(tt, value, loc))
            elif ch == "{":
                self.advance()
                self.tokens.append(Token(TokenType.LBRACE, "{", loc))
            elif ch == "}":
                self.advance()
                self.tokens.append(Token(TokenType.RBRACE, "}", loc))
            elif ch == "(":
                self.advance()
                self.tokens.append(Token(TokenType.LPAREN, "(", loc))
            elif ch == ")":
                self.advance()
                self.tokens.append(Token(TokenType.RPAREN, ")", loc))
            elif ch == "[":
                self.advance()
                self.tokens.append(Token(TokenType.LBRACKET, "[", loc))
            elif ch == "]":
                self.advance()
                self.tokens.append(Token(TokenType.RBRACKET, "]", loc))
            elif ch == ";":
                self.advance()
                self.tokens.append(Token(TokenType.SEMICOLON, ";", loc))
            elif ch == ",":
                self.advance()
                self.tokens.append(Token(TokenType.COMMA, ",", loc))
            elif ch == "=":
                self.advance()
                if self.peek() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.EQEQ, "==", loc))
                else:
                    self.tokens.append(Token(TokenType.EQUALS, "=", loc))
            elif ch == "-":
                self.advance()
                if self.peek() == ">":
                    self.advance()
                    if self.peek() == "|":
                        self.advance()
                        self.tokens.append(Token(TokenType.DIODE_ARROW, "->|", loc))
                    else:
                        self.tokens.append(Token(TokenType.ARROW, "->", loc))
                else:
                    # Could be negative number
                    if self.peek().isdigit():
                        value = "-" + self.read_number()
                        self.tokens.append(Token(TokenType.NUMBER, value, loc))
                    else:
                        raise LexError(f"Unexpected character: '-'", loc)
            elif ch == ".":
                self.advance()
                if self.peek() == ".":
                    self.advance()
                    self.tokens.append(Token(TokenType.DOTDOT, "..", loc))
                else:
                    self.tokens.append(Token(TokenType.DOT, ".", loc))
            else:
                raise LexError(f"Unexpected character: {ch!r}", loc)

        self.tokens.append(Token(TokenType.EOF, "", self.loc()))
        return self.tokens
