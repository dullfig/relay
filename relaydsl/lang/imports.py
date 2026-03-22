"""
Import resolver for RelayDSL.

Resolves import statements, loads referenced files, parses them,
and merges all components into a unified program.

Handles:
- Relative paths (resolved from the importing file's directory)
- Transitive imports (A imports B which imports C)
- Circular import detection
- De-duplication (same file imported from multiple places)
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from .ast_nodes import Program, Component, Testbench, Import
from .errors import SemanticError, SourceLocation
from .parser import parse as parse_source


@dataclass
class ResolvedProgram:
    """A program with all imports resolved and merged."""
    components: dict[str, Component] = field(default_factory=dict)
    testbenches: list[Testbench] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    errors: list[SemanticError] = field(default_factory=list)

    def to_program(self) -> Program:
        """Convert back to a Program for downstream use."""
        items: list = list(self.components.values()) + self.testbenches
        return Program(items=items)


class ImportResolver:
    """
    Resolves imports across multiple .relay files.

    Usage:
        resolver = ImportResolver()
        resolved = resolver.resolve_file("path/to/top.relay")
        program = resolved.to_program()
    """

    def __init__(self, search_paths: list[str] | None = None):
        self.search_paths = search_paths or []
        self.loaded_files: dict[str, Program] = {}  # abs_path -> parsed Program
        self.loading_stack: list[str] = []  # for circular import detection
        self.components: dict[str, Component] = {}
        self.component_source: dict[str, str] = {}  # component_name -> source file
        self.testbenches: list[Testbench] = []
        self.errors: list[SemanticError] = []

    def resolve_file(self, filepath: str) -> ResolvedProgram:
        """Resolve a top-level file and all its imports."""
        abs_path = os.path.abspath(filepath)
        self._load_file(abs_path)

        return ResolvedProgram(
            components=dict(self.components),
            testbenches=list(self.testbenches),
            source_files=list(self.loaded_files.keys()),
            errors=list(self.errors),
        )

    def resolve_source(self, source: str, filename: str = "<input>",
                        base_dir: str | None = None) -> ResolvedProgram:
        """Resolve from source string (for testing)."""
        self._base_dir_override = base_dir or os.getcwd()
        program = parse_source(source, filename)
        self._process_program(program, filename)

        return ResolvedProgram(
            components=dict(self.components),
            testbenches=list(self.testbenches),
            source_files=list(self.loaded_files.keys()),
            errors=list(self.errors),
        )

    def _load_file(self, abs_path: str):
        """Load and process a single file, resolving its imports."""
        # Circular import? (must check before loaded_files)
        if abs_path in self.loading_stack:
            cycle = " -> ".join(self.loading_stack + [abs_path])
            self.errors.append(SemanticError(
                f"Circular import detected: {cycle}"))
            return

        # Already fully loaded? (diamond import - same file from multiple paths)
        if abs_path in self.loaded_files:
            return

        # Read and parse
        if not os.path.exists(abs_path):
            self.errors.append(SemanticError(
                f"Import file not found: {abs_path}"))
            return

        try:
            with open(abs_path, "r") as f:
                source = f.read()
        except OSError as e:
            self.errors.append(SemanticError(f"Cannot read file: {e}"))
            return

        try:
            program = parse_source(source, abs_path)
        except Exception as e:
            self.errors.append(SemanticError(f"Parse error in {abs_path}: {e}"))
            return

        self.loading_stack.append(abs_path)
        self.loaded_files[abs_path] = program
        self._process_program(program, abs_path)
        self.loading_stack.pop()

    def _process_program(self, program: Program, source_path: str):
        """Process a parsed program: resolve imports, collect components."""
        source_dir = os.path.dirname(os.path.abspath(source_path))
        if hasattr(self, '_base_dir_override'):
            source_dir = self._base_dir_override

        for item in program.items:
            if isinstance(item, Import):
                self._resolve_import(item, source_dir)
            elif isinstance(item, Component):
                self._register_component(item, source_path)
            elif isinstance(item, Testbench):
                self.testbenches.append(item)

    def _resolve_import(self, imp: Import, source_dir: str):
        """Resolve a single import statement."""
        # Try relative to importing file first
        rel_path = os.path.join(source_dir, imp.path)
        abs_path = os.path.abspath(rel_path)

        if os.path.exists(abs_path):
            self._load_file(abs_path)
            return

        # Try search paths
        for search_dir in self.search_paths:
            candidate = os.path.join(search_dir, imp.path)
            abs_candidate = os.path.abspath(candidate)
            if os.path.exists(abs_candidate):
                self._load_file(abs_candidate)
                return

        self.errors.append(SemanticError(
            f"Cannot find import '{imp.path}' "
            f"(searched: {source_dir}, {', '.join(self.search_paths) or 'no search paths'})",
            imp.loc,
        ))

    def _register_component(self, comp: Component, source_path: str):
        """Register a component, checking for duplicates."""
        if comp.name in self.components:
            existing_source = self.component_source.get(comp.name, "<unknown>")
            if existing_source != source_path:
                self.errors.append(SemanticError(
                    f"Component '{comp.name}' defined in both "
                    f"'{existing_source}' and '{source_path}'",
                    comp.loc,
                ))
            # Same file imported twice - skip duplicate silently
            return

        self.components[comp.name] = comp
        self.component_source[comp.name] = source_path


# --- Convenience functions ---

def resolve_file(filepath: str,
                  search_paths: list[str] | None = None) -> ResolvedProgram:
    """Resolve a .relay file with all its imports."""
    resolver = ImportResolver(search_paths=search_paths)
    return resolver.resolve_file(filepath)


def resolve_and_parse(filepath: str,
                       search_paths: list[str] | None = None) -> Program:
    """Resolve imports and return a unified Program."""
    resolved = resolve_file(filepath, search_paths)
    if resolved.errors:
        raise SemanticError(
            f"Import errors:\n" +
            "\n".join(f"  {e}" for e in resolved.errors))
    return resolved.to_program()
