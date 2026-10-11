"""Solver wrapper: notation conversion and error handling (no real tables)."""

import importlib.util
from pathlib import Path
import sys

import pytest

_PATH = Path(__file__).parent.parent / "custom_components" / "qiyi_cube" / "solver.py"
_spec = importlib.util.spec_from_file_location("qiyi_solver", _PATH)
solver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(solver)


def test_parse_result():
    assert solver.parse_result("L3 U2 R1 (3f)") == ["L'", "U2", "R"]
    assert solver.parse_result("(0f)") == []
    with pytest.raises(ValueError):
        solver.parse_result("Error: Some edges are undefined.")


# A stand-in worker speaking the same line protocol as the real one.
FAKE_WORKER = """
import sys
print("ready", flush=True)
for line in sys.stdin:
    facelets, max_length, seconds = line.split()
    if facelets == "die":
        sys.exit(1)
    print("Error: bad cube" if facelets == "bad" else "R1 U3 (2f)", flush=True)
"""


async def test_solver_process():
    proc = solver.SolverProcess("unused", argv=[sys.executable, "-c", FAKE_WORKER])
    await proc.start()
    assert await proc.solve("x" * 54, 1.0) == ["R", "U'"]
    with pytest.raises(ValueError):
        await proc.solve("bad", 1.0)
    # A dead worker is restarted transparently.
    with pytest.raises(RuntimeError):
        await proc.solve("die", 1.0)
    assert await proc.solve("x" * 54, 1.0) == ["R", "U'"]
    await proc.stop()


def test_tables_ready(tmp_path):
    assert not solver.tables_ready(str(tmp_path))
    (tmp_path / ".complete").touch()
    assert solver.tables_ready(str(tmp_path))
