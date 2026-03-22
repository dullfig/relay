"""Test the import resolver."""
import os
import pytest
import tempfile
import shutil
from relaydsl.lang.imports import ImportResolver, resolve_file, resolve_and_parse


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def write_file(directory: str, name: str, content: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(content)
    return path


class TestBasicImport:
    def test_single_file_no_imports(self, tmpdir):
        write_file(tmpdir, "simple.relay", """
            component Foo {
                port in A;
                port out B;
            }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "simple.relay"))
        assert not resolved.errors
        assert "Foo" in resolved.components

    def test_import_one_file(self, tmpdir):
        write_file(tmpdir, "base.relay", """
            component Base {
                port in X;
                port out Y;
                relay R1;
                connect X -> R1.coil;
            }
        """)
        write_file(tmpdir, "top.relay", """
            import "base.relay";
            component Top {
                port in A;
                port out B;
                instance sub = Base(X=A, Y=B);
            }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "top.relay"))
        assert not resolved.errors, [str(e) for e in resolved.errors]
        assert "Base" in resolved.components
        assert "Top" in resolved.components
        assert len(resolved.source_files) == 2

    def test_transitive_import(self, tmpdir):
        write_file(tmpdir, "a.relay", """
            component A { port in X; }
        """)
        write_file(tmpdir, "b.relay", """
            import "a.relay";
            component B { port in X; instance a = A(X=X); }
        """)
        write_file(tmpdir, "c.relay", """
            import "b.relay";
            component C { port in X; instance b = B(X=X); }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "c.relay"))
        assert not resolved.errors, [str(e) for e in resolved.errors]
        assert "A" in resolved.components
        assert "B" in resolved.components
        assert "C" in resolved.components
        assert len(resolved.source_files) == 3

    def test_diamond_import(self, tmpdir):
        """A imports B and C, both of which import D. D should load once."""
        write_file(tmpdir, "d.relay", "component D { port in X; }")
        write_file(tmpdir, "b.relay", 'import "d.relay"; component B { port in X; }')
        write_file(tmpdir, "c.relay", 'import "d.relay"; component C { port in X; }')
        write_file(tmpdir, "a.relay", """
            import "b.relay";
            import "c.relay";
            component A { port in X; }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "a.relay"))
        assert not resolved.errors, [str(e) for e in resolved.errors]
        assert len(resolved.components) == 4  # A, B, C, D
        # D's file should appear only once
        d_files = [f for f in resolved.source_files if f.endswith("d.relay")]
        assert len(d_files) == 1


class TestImportErrors:
    def test_missing_file(self, tmpdir):
        write_file(tmpdir, "top.relay", """
            import "nonexistent.relay";
            component Top { }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "top.relay"))
        assert len(resolved.errors) == 1
        assert "cannot find" in str(resolved.errors[0]).lower()

    def test_circular_import(self, tmpdir):
        write_file(tmpdir, "a.relay", """
            import "b.relay";
            component A { }
        """)
        write_file(tmpdir, "b.relay", """
            import "a.relay";
            component B { }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "a.relay"))
        assert any("circular" in str(e).lower() for e in resolved.errors)

    def test_duplicate_component_across_files(self, tmpdir):
        write_file(tmpdir, "a.relay", "component Foo { }")
        write_file(tmpdir, "b.relay", "component Foo { }")
        write_file(tmpdir, "top.relay", """
            import "a.relay";
            import "b.relay";
            component Top { }
        """)
        resolved = resolve_file(os.path.join(tmpdir, "top.relay"))
        assert any("Foo" in str(e) for e in resolved.errors)


class TestImportWithSimulation:
    """Test that imported components simulate correctly."""

    def test_imported_zuse_adder(self):
        """Test loading the 4-bit adder which imports zuse_adder."""
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        four_bit = os.path.join(examples_dir, "four_bit_adder.relay")

        if not os.path.exists(four_bit):
            pytest.skip("four_bit_adder.relay not found")

        resolved = resolve_file(four_bit)
        assert not resolved.errors, [str(e) for e in resolved.errors]
        assert "ZuseAdder" in resolved.components
        assert "FourBitAdder" in resolved.components

    def test_simulate_imported(self, tmpdir):
        """Test that imported components elaborate and simulate correctly."""
        write_file(tmpdir, "inverter.relay", """
            component Inverter {
                port in A;
                port out Y;
                wire vcc = HIGH;
                wire gnd = LOW;
                relay R1;
                connect A -> R1.coil;
                connect vcc -> R1.c1.nc;
                connect gnd -> R1.c1.no;
                connect R1.c1.common -> Y;
            }
        """)
        write_file(tmpdir, "buffer.relay", """
            import "inverter.relay";
            component Buffer {
                port in A;
                port out Y;
                wire mid;
                instance inv1 = Inverter(A=A, Y=mid);
                instance inv2 = Inverter(A=mid, Y=Y);
            }
        """)

        resolved = resolve_file(os.path.join(tmpdir, "buffer.relay"))
        assert not resolved.errors, [str(e) for e in resolved.errors]

        program = resolved.to_program()
        from relaydsl.lang.elaborate import elaborate, load_flat_into_engine
        from relaydsl.sim.engine import SimEngine
        from relaydsl.sim.nets import WireState

        flat = elaborate(program, "Buffer")
        engine = SimEngine()
        load_flat_into_engine(flat, engine)

        engine.drive("A", WireState.HIGH)
        assert engine.read("Y") == WireState.HIGH

        engine.drive("A", WireState.LOW)
        assert engine.read("Y") == WireState.LOW


class TestSearchPaths:
    def test_search_path(self, tmpdir):
        """Test that search paths are used for import resolution."""
        lib_dir = os.path.join(tmpdir, "lib")
        os.makedirs(lib_dir)
        write_file(lib_dir, "base.relay", "component Base { port in X; }")
        write_file(tmpdir, "top.relay", """
            import "base.relay";
            component Top { port in X; instance b = Base(X=X); }
        """)

        # Without search path - should fail
        resolved = resolve_file(os.path.join(tmpdir, "top.relay"))
        assert any("not found" in str(e).lower() or "Cannot find" in str(e)
                    for e in resolved.errors)

        # With search path - should succeed
        resolved = resolve_file(
            os.path.join(tmpdir, "top.relay"),
            search_paths=[lib_dir])
        assert not resolved.errors, [str(e) for e in resolved.errors]
        assert "Base" in resolved.components


class TestCLIWithImport:
    def test_cli_test_with_import(self):
        """Test that relay-sim test works with files that have imports."""
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        zuse = os.path.join(examples_dir, "zuse_adder.relay")

        import subprocess
        result = subprocess.run(
            ["python", "-m", "relaydsl", "test", zuse],
            capture_output=True, text=True, cwd=os.path.join(
                os.path.dirname(__file__), ".."))
        assert result.returncode == 0, result.stderr
        assert "8 passed" in result.stdout

    def test_cli_parse_with_import(self):
        """Test relay-sim parse on a file with imports."""
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        four_bit = os.path.join(examples_dir, "four_bit_adder.relay")

        if not os.path.exists(four_bit):
            pytest.skip("four_bit_adder.relay not found")

        import subprocess
        result = subprocess.run(
            ["python", "-m", "relaydsl", "parse", four_bit],
            capture_output=True, text=True, cwd=os.path.join(
                os.path.dirname(__file__), ".."))
        assert "ZuseAdder" in result.stdout or "FourBitAdder" in result.stdout, result.stdout
