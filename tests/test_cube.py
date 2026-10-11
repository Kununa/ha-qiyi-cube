"""Real solve vs fidgeting, driven by state frames (no Home Assistant)."""

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.qiyi_cube import protocol
from custom_components.qiyi_cube.cube import QiYiCube

cubie = pytest.importorskip("twophase.cubie")

MOVE_CODES = {name: code for code, name in protocol.MOVES.items()}


class Driver:
    """Turns a simulated cube and feeds the resulting frames to QiYiCube."""

    def __init__(self) -> None:
        self.cube = QiYiCube("test", bytes(6), lambda: None)
        self.cube._client = MagicMock(is_connected=True, write_gatt_char=AsyncMock())
        self.cube.data.connected = True
        self.state = cubie.CubieCube()
        self.ms = 1000
        self._send(0x02, 0)

    def turn(self, moves: list[str], every_ms: int = 400) -> None:
        for move in moves:
            self.ms += every_ms
            turns = {"": 1, "2": 2, "'": 3}[move[1:]]
            for _ in range(turns):
                self.state.multiply(cubie.basicMoveCube["URFDLB".index(move[0])])
            # The cube reports half turns as two quarter turns.
            quarter = move[0] if turns != 3 else move
            for _ in range(2 if turns == 2 else 1):
                self._send(0x03, MOVE_CODES[quarter])

    def pause(self, ms: int) -> None:
        self.ms += ms

    @property
    def facelets(self) -> str:
        return self.state.to_facelet_cube().to_string()

    def _send(self, opcode: int, move: int) -> None:
        idx = {c: i for i, c in enumerate("LRDUFB")}
        n = [idx[c] for c in self.facelets]
        raw = bytes(n[i] | n[i + 1] << 4 for i in range(0, 54, 2))
        msg = bytearray([0xFE, 0, opcode]) + self.ms.to_bytes(4, "big") + raw
        msg += bytes([move, 90])
        msg[1] = len(msg) + 2
        crc = protocol.crc16_modbus(msg)
        msg += bytes([crc & 0xFF, crc >> 8])
        msg += bytes((16 - len(msg) % 16) % 16)
        self.cube._on_notify(None, bytearray(protocol.encrypt(bytes(msg))))


def inverse(moves: list[str]) -> list[str]:
    flip = {"": "'", "'": "", "2": "2"}
    return [m[0] + flip[m[1:]] for m in reversed(moves)]


def scramble(n: int = 20) -> list[str]:
    rng = random.Random(4)
    out: list[str] = []
    while len(out) < n:
        face = rng.choice("URFDLB")
        if not out or out[-1][0] != face:
            out.append(face + rng.choice(["", "'"]))
    return out


async def test_real_solve() -> None:
    drv = Driver()
    moves = scramble()
    drv.turn(moves, every_ms=300)
    drv.pause(5000)  # inspection
    assert not drv.cube.data.solving
    solution = inverse(moves)
    drv.turn(solution[:1], every_ms=0)
    assert drv.cube.data.solving
    drv.pause(8000)  # thinking pauses during the solve don't matter
    drv.turn(solution[1:], every_ms=500)

    d = drv.cube.data
    assert d.solved and not d.solving
    r = d.last_solve
    assert (r.moves, r.scramble_moves, r.inspection_seconds) == (20, 20, 5.0)
    assert r.seconds == 8 + 19 * 0.5
    assert r.scramble_distance is None  # no solver result was available
    assert r.tps == round(20 / 17.5, 2)


async def test_fidget_pattern_is_not_a_solve() -> None:
    drv = Driver()
    sexy = ["R", "U", "R'", "U'"]
    drv.turn(sexy * 3)
    drv.pause(5000)  # pausing mid-fidget: still 7+ pieces untouched
    drv.turn(sexy * 3)
    assert drv.cube.data.solved
    assert drv.cube.data.last_solve is None


async def test_solver_distance_vetoes_shallow_states() -> None:
    drv = Driver()
    moves = scramble()
    drv.turn(moves, every_ms=300)
    d = drv.cube.data
    # Pretend the solver found a short way back: not really scrambled.
    d.solution, d.solution_for = ["R"] * 8, drv.facelets
    drv.pause(5000)
    drv.turn(inverse(moves))
    assert d.solved and d.last_solve is None

    drv.turn(moves, every_ms=300)
    d.solution, d.solution_for = ["R"] * 18, drv.facelets
    drv.pause(5000)
    drv.turn(inverse(moves))
    assert d.last_solve.scramble_distance == 18


async def test_disconnect_abandons_solve() -> None:
    drv = Driver()
    moves = scramble()
    drv.turn(moves, every_ms=300)
    drv.pause(5000)
    drv.turn(inverse(moves)[:5])
    assert drv.cube.data.solving
    drv.cube._on_disconnect(drv.cube._client)
    assert not drv.cube.data.solving


async def test_resent_turn_is_counted_once() -> None:
    drv = Driver()
    moves: list[str] = []
    drv.cube._on_move = lambda move, solved: moves.append(move)
    drv.turn(["R"])
    drv._send(0x03, MOVE_CODES["R"])  # same frame again, same cube timestamp
    assert moves == ["R"]
    assert drv.cube.data.moves_since_solved == 1
    drv.turn(["R'"])
    assert moves == ["R", "R'"] and drv.cube.data.solved
