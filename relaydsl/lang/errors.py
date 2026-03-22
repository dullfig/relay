from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SourceLocation:
    file: str
    line: int
    col: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}"


class RelayDSLError(Exception):
    def __init__(self, message: str, loc: SourceLocation | None = None):
        self.loc = loc
        if loc:
            super().__init__(f"{loc}: {message}")
        else:
            super().__init__(message)


class LexError(RelayDSLError):
    pass


class ParseError(RelayDSLError):
    pass


class SemanticError(RelayDSLError):
    pass


class SimulationError(RelayDSLError):
    pass
