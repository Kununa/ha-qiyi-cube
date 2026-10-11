"""Short solutions via Kociemba's two-phase algorithm (no Home Assistant imports).

Wraps the pure-Python RubikTwoPhase package. On first import it builds ~80 MB
of lookup tables (30+ minutes in pure Python) in ``twophase.defs.FOLDER``,
relative to the working directory unless redirected. ``build_tables`` does
that once in a separate low-priority process.

Solving runs in a long-lived worker process (``SolverProcess``) as well: the
search is CPU-bound pure Python in six threads, and inside the caller's
process it would hold the GIL for the whole search and stall its event loop
(in Home Assistant: the live stream to the card stuttered after every turn).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys

_COMPLETE = ".complete"
_BUILD_SCRIPT = (
    "import os, sys; os.nice(19)\n"
    "import twophase.defs as d; d.FOLDER = sys.argv[1]\n"
    "import twophase.solver\n"
)
# Worker protocol: prints "ready" once the tables are loaded, then answers
# each "<facelets> <max_length> <seconds>" line with one line of two-phase
# output (max_length 0 = search for the full time).
_WORKER_SCRIPT = """\
import contextlib, io, os, sys
os.nice(5)
import twophase.defs as d
d.FOLDER = sys.argv[1]
with contextlib.redirect_stdout(io.StringIO()):
    import twophase.solver as sv
print("ready", flush=True)
for line in sys.stdin:
    facelets, max_length, seconds = line.split()
    try:
        out = sv.solve(facelets, int(max_length), float(seconds))
    except Exception as err:
        out = f"Error: {err}"
    print(out, flush=True)
"""
_START_TIMEOUT = 120  # loading the tables takes a few seconds on a Pi
# Two-phase notation: 1/2/3 = quarter turns clockwise.
_SUFFIX = {"1": "", "2": "2", "3": "'"}


def tables_ready(folder: str) -> bool:
    return (Path(folder) / _COMPLETE).is_file()


def build_tables(folder: str) -> None:
    """Create the lookup tables in a child process (blocks; raises CalledProcessError)."""
    os.makedirs(folder, exist_ok=True)
    subprocess.run(
        [sys.executable, "-c", _BUILD_SCRIPT, folder],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    (Path(folder) / _COMPLETE).touch()


def parse_result(result: str) -> list[str]:
    """Two-phase output like "L3 U2 R1 (3f)" -> ["L'", "U2", "R"]."""
    if not result.endswith("f)"):
        raise ValueError(result)  # e.g. "Error: Some edges are undefined."
    return [m[0] + _SUFFIX[m[1]] for m in result.split()[:-1]]


class SolverProcess:
    """A worker process holding the loaded tables; one search at a time."""

    def __init__(self, folder: str, argv: list[str] | None = None) -> None:
        self._argv = argv or [sys.executable, "-c", _WORKER_SCRIPT, folder]
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        line = await asyncio.wait_for(self._proc.stdout.readline(), _START_TIMEOUT)
        if line.strip() != b"ready":
            await self.stop()
            raise RuntimeError(f"solver worker did not start: {line!r}")

    async def solve(self, facelets: str, seconds: float, max_length: int = 0) -> list[str]:
        """Solution for a URFDLB facelet string.

        Returns as soon as one with at most ``max_length`` moves is found (0:
        keep searching), else the shortest found within ``seconds``.

        Restarts the worker once if it died. Raises ValueError for cubes that
        can't be solved (invalid state) and RuntimeError if the worker fails.
        """
        async with self._lock:
            for attempt in (1, 2):
                if self._proc is None or self._proc.returncode is not None:
                    await self.start()
                try:
                    self._proc.stdin.write(f"{facelets} {max_length} {seconds}\n".encode())
                    await self._proc.stdin.drain()
                    line = await asyncio.wait_for(self._proc.stdout.readline(), seconds + 30)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    line = b""
                if line:
                    return parse_result(line.decode().strip())
                await self.stop()
                if attempt == 2:
                    raise RuntimeError("solver worker failed")
        raise AssertionError("unreachable")

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.kill()
        await proc.wait()
