"""CLI entry point for relay-sim."""
from __future__ import annotations
import sys
import os


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    command = args[0]
    if command == "parse":
        cmd_parse(args[1:])
    elif command == "simulate":
        cmd_simulate(args[1:])
    elif command == "test":
        cmd_test(args[1:])
    elif command == "count":
        cmd_count(args[1:])
    elif command == "dump":
        cmd_dump(args[1:])
    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)


def print_help():
    print("""relay-sim: Relay circuit DSL simulator

Commands:
  parse     <file.relay>    Parse and report errors
  simulate  <file.relay>    Load and interactively probe
  test      <file.relay>    Run testbenches
  count     <file.relay>    Report component counts
  dump      <file.relay>    Parse and dump AST
""")


def load_program(filepath: str):
    """Load a .relay file, resolving all imports."""
    from .lang.imports import resolve_file
    resolved = resolve_file(filepath)
    if resolved.errors:
        for err in resolved.errors:
            print(f"  IMPORT ERROR: {err}")
        sys.exit(1)
    if len(resolved.source_files) > 1:
        print(f"Loaded {len(resolved.source_files)} file(s): "
              f"{', '.join(os.path.basename(f) for f in resolved.source_files)}")
    return resolved.to_program()


def cmd_parse(args: list[str]):
    if not args:
        print("Usage: relay-sim parse <file.relay>")
        sys.exit(1)
    filepath = args[0]
    from .lang.semantic import analyze
    try:
        program = load_program(filepath)
        sa, errors = analyze(program)

        components = list(sa.analyzed.values())
        testbenches = sa.testbenches

        if errors:
            print(f"ERRORS ({len(errors)}):")
            for err in errors:
                print(f"  {err}")
            sys.exit(1)

        print(f"OK: {len(components)} component(s), {len(testbenches)} testbench(es)")
        for ac in components:
            relay_count = sum(1 for _ in ac.relays)
            poles_info = ", ".join(
                f"{r.name}({r.poles}PDT)" for r in ac.relays.values())
            print(f"  component {ac.name}: {relay_count} relay(s) [{poles_info}], "
                  f"{len(ac.connections)} connection(s), "
                  f"{len(ac.all_nets)} net(s)")

        if sa.warnings:
            print(f"\nWarnings ({len(sa.warnings)}):")
            for w in sa.warnings:
                print(f"  {w}")

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def cmd_dump(args: list[str]):
    if not args:
        print("Usage: relay-sim dump <file.relay>")
        sys.exit(1)
    program = load_program(args[0])
    for item in program.items:
        print(item)


def cmd_simulate(args: list[str]):
    if not args:
        print("Usage: relay-sim simulate <file.relay>")
        sys.exit(1)
    from .sim.engine import SimEngine
    from .lang.ast_nodes import Component

    program = load_program(args[0])
    engine = SimEngine()
    for item in program.items:
        if isinstance(item, Component):
            engine.load_component(item)
            break
    engine.propagate()
    print("Circuit loaded. Net states:")
    for name, state in sorted(engine.dump_state().items()):
        print(f"  {name}: {state}")
    print("\nRelay states:")
    for name, state in sorted(engine.dump_relays().items()):
        print(f"  {name}: {state}")


def cmd_test(args: list[str]):
    if not args:
        print("Usage: relay-sim test <file.relay>")
        sys.exit(1)
    from .sim.engine import SimEngine
    from .sim.nets import WireState
    from .lang.ast_nodes import Component, Testbench, VectorStmt, InstanceStmt
    from .lang.elaborate import elaborate, load_flat_into_engine

    program = load_program(args[0])

    components = {item.name: item for item in program.items
                  if isinstance(item, Component)}
    testbenches = [item for item in program.items
                   if isinstance(item, Testbench)]

    if not testbenches:
        print("No testbenches found.")
        return

    # Pre-elaborate components that have instances
    flat_cache = {}
    for name, comp in components.items():
        has_instances = any(isinstance(m, InstanceStmt) for m in comp.members)
        if has_instances:
            try:
                flat_cache[name] = elaborate(program, name)
            except Exception as e:
                print(f"  WARNING: Cannot elaborate {name}: {e}")

    total_passed = 0
    total_failed = 0

    for tb in testbenches:
        print(f"\n=== Testbench: {tb.name} for {tb.target} ===")

        passed = 0
        failed = 0
        tb_errors = []

        for i, stmt in enumerate(tb.statements):
            if isinstance(stmt, VectorStmt):
                # Fresh engine for each vector
                engine = SimEngine()
                comp = components.get(tb.target)
                if not comp:
                    print(f"  ERROR: Component {tb.target} not found")
                    break

                # Use elaboration for components with instances
                if tb.target in flat_cache:
                    load_flat_into_engine(flat_cache[tb.target], engine)
                else:
                    engine.load_component(comp)

                # Apply inputs
                for assign in stmt.inputs:
                    state = WireState.HIGH if assign.value == "1" else WireState.LOW
                    engine.drive(assign.name, state)

                # Check outputs
                vec_ok = True
                for expect in stmt.outputs:
                    actual = engine.read(expect.name)
                    if expect.expected == "Z":
                        expected_state = WireState.FLOAT
                    elif expect.expected == "1":
                        expected_state = WireState.HIGH
                    else:
                        expected_state = WireState.LOW

                    if actual != expected_state:
                        vec_ok = False
                        inputs_str = ", ".join(
                            f"{a.name}={a.value}" for a in stmt.inputs)
                        tb_errors.append(
                            f"  Vector {i+1} [{inputs_str}]: "
                            f"{expect.name} expected {expected_state} got {actual}"
                        )

                if vec_ok:
                    passed += 1
                else:
                    failed += 1

        total_passed += passed
        total_failed += failed
        print(f"  {passed} passed, {failed} failed")
        for err in tb_errors:
            print(err)

    print(f"\nTotal: {total_passed} passed, {total_failed} failed")
    sys.exit(1 if total_failed > 0 else 0)


def cmd_count(args: list[str]):
    if not args:
        print("Usage: relay-sim count <file.relay>")
        sys.exit(1)
    from .lang.ast_nodes import (Component, RelayDecl, DiodeDecl,
                                  CapacitorDecl, FuseDecl, ConnectStmt)

    program = load_program(args[0])
    for item in program.items:
        if isinstance(item, Component):
            relays = sum(len(m.names) for m in item.members
                         if isinstance(m, RelayDecl))
            diodes = sum(len(m.names) for m in item.members
                         if isinstance(m, DiodeDecl))
            inline_diodes = sum(1 for m in item.members
                                if isinstance(m, ConnectStmt) and m.has_diode)
            caps = sum(len(m.names) for m in item.members
                       if isinstance(m, CapacitorDecl))
            fuses = sum(len(m.names) for m in item.members
                        if isinstance(m, FuseDecl))
            connects = sum(1 for m in item.members
                           if isinstance(m, ConnectStmt))
            print(f"Component {item.name}:")
            print(f"  Relays:      {relays}")
            print(f"  Diodes:      {diodes + inline_diodes}")
            print(f"  Capacitors:  {caps}")
            print(f"  Fuses:       {fuses}")
            print(f"  Connections: {connects}")


if __name__ == "__main__":
    main()
