"""Connection and state tracking for a QiYi cube (no Home Assistant imports)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Literal

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol

_LOGGER = logging.getLogger(__name__)


# A "real" solve, as opposed to fidgeting: the cube was well mixed, then not
# turned for an inspection pause, then solved. The first such pause after
# leaving solved starts the solve; later (thinking) pauses don't matter.
INSPECTION_MS = 3000
# Well mixed: few pieces in place (fidget patterns like R U R' U' leave many
# untouched) and, if the solver has a solution for the state, far from solved.
MAX_SOLVED_PIECES = 5
MIN_SCRAMBLE_DISTANCE = 12


@dataclass(frozen=True)
class SolveResult:
    moves: int
    seconds: float  # first move after inspection until solved
    scramble_moves: int
    scramble_distance: int | None  # solution length after scrambling, if known
    inspection_seconds: float

    @property
    def tps(self) -> float:
        return round(self.moves / self.seconds, 2) if self.seconds else 0.0


@dataclass
class CubeData:
    """Everything the entities expose."""

    connected: bool = False
    battery: int | None = None
    facelets: str | None = None
    last_move: str | None = None
    moves_since_solved: int = 0
    solving: bool = False
    last_solve: SolveResult | None = None
    quaternion: tuple[float, float, float, float] | None = None
    top_face: str | None = None
    # Filled in by the HA coordinator: a solution and the facelets it is for.
    solution: list[str] | None = None
    solution_for: str | None = None
    # internal
    _last_move_ms: int | None = field(default=None, repr=False)
    _solve_start_ms: int = field(default=0, repr=False)
    _solve_moves: int = field(default=0, repr=False)
    _scramble: tuple[int, int | None, float] = field(default=(0, None, 0.0), repr=False)

    @property
    def solved(self) -> bool | None:
        return None if self.facelets is None else protocol.is_solved(self.facelets)


class QiYiCube:
    """Connects to the cube, performs the handshake and tracks its state.

    `on_update` is called on every state change, `on_move` for every face turn.
    Gyro samples only update `data.quaternion` and call `on_gyro`.
    """

    def __init__(
        self,
        name: str,
        mac_reversed: bytes,
        on_update: Callable[[], None],
        on_move: Callable[[str, bool], None] | None = None,
        on_gyro: Callable[[], None] | None = None,
    ) -> None:
        self.name = name
        self._mac = mac_reversed
        self._on_update = on_update
        self._on_move = on_move
        self._on_gyro = on_gyro
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.data = CubeData()

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self, device: BLEDevice) -> None:
        """Connect if not already connected. Safe to call repeatedly."""
        if self.connected or self._lock.locked():
            return
        async with self._lock:
            _LOGGER.debug("%s: connecting to %s", self.name, device.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self.name,
                disconnected_callback=self._on_disconnect,
                max_attempts=3,
            )
            try:
                await client.start_notify(protocol.CHAR_UUID, self._on_notify)
                self._client = client
                await self._write(protocol.build_hello(self._mac))
            except BleakError:
                await client.disconnect()
                self._client = None
                raise
            self.data.connected = True
            _LOGGER.debug("%s: connected, hello sent", self.name)
            self._on_update()

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()
        self._set_disconnected()

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("%s: disconnected", self.name)
        self._client = None
        self._set_disconnected()

    def _set_disconnected(self) -> None:
        if self.data.connected:
            self.data.connected = False
            self.data.quaternion = None
            # The cube's clock and our view of the session can't be trusted
            # across a reconnect; a solve in progress is abandoned.
            self.data.solving = False
            self.data._last_move_ms = None  # noqa: SLF001
            self._on_update()

    async def _write(self, frame: bytes) -> None:
        if self._client is None:
            return
        await self._client.write_gatt_char(protocol.CHAR_UUID, frame, response=False)

    def _send_ack(self, frame: bytes) -> None:
        task = asyncio.get_running_loop().create_task(self._write(frame))
        self._tasks.add(task)
        task.add_done_callback(self._ack_done)

    def _ack_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()):
            _LOGGER.debug("%s: ack failed: %s", self.name, exc)

    def _on_notify(self, _char, data: bytearray) -> None:
        msg = protocol.parse(bytes(data))
        if msg is None:
            _LOGGER.debug("%s: dropped corrupt frame %s", self.name, data.hex())
            return
        if isinstance(msg, protocol.GyroSample):
            d = self.data
            d.quaternion = msg.quaternion
            changed = False
            # Gyro frames report 101 while the cube sits in its charging box.
            if (battery := min(msg.battery, 100)) != d.battery:
                d.battery = battery
                changed = True
            # Keep the last face while the cube is tilted between two faces.
            if (face := protocol.top_face(msg.quaternion)) and face != d.top_face:
                d.top_face = face
                changed = True
            if changed:
                self._on_update()
            if self._on_gyro:
                self._on_gyro()
            return
        if isinstance(msg, protocol.Unknown):
            _LOGGER.debug("%s: unknown message %s", self.name, msg.raw.hex())
            return

        self._send_ack(msg.ack)
        if msg.move is not None and msg.timestamp_ms == self.data._last_move_ms:  # noqa: SLF001
            # The cube resends a turn when our ACK is late (e.g. via a BLE
            # proxy); same cube timestamp = same turn.
            _LOGGER.debug("%s: duplicate turn %s ignored", self.name, msg.move)
            return
        self._apply_state(msg)

    def _apply_state(self, msg: protocol.CubeState) -> None:
        d = self.data
        before = d.facelets
        d.battery = min(msg.battery, 100)
        d.facelets = msg.facelets

        if msg.move is not None:
            d.last_move = msg.move
            if before is not None and not d.solving and d._last_move_ms is not None:
                pause = msg.timestamp_ms - d._last_move_ms
                if pause >= INSPECTION_MS and (
                    distance := self._mixed_distance(before)
                ) is not False:
                    d.solving = True
                    d._solve_start_ms = msg.timestamp_ms
                    d._solve_moves = 0
                    d._scramble = (d.moves_since_solved, distance, pause / 1000)
            d._last_move_ms = msg.timestamp_ms
            d.moves_since_solved += 1
            if d.solving:
                d._solve_moves += 1
            if msg.solved:
                if d.solving:
                    scramble_moves, distance, inspection = d._scramble
                    d.last_solve = SolveResult(
                        moves=d._solve_moves,
                        seconds=round((msg.timestamp_ms - d._solve_start_ms) / 1000, 2),
                        scramble_moves=scramble_moves,
                        scramble_distance=distance,
                        inspection_seconds=round(inspection, 1),
                    )
                d.solving = False
                d.moves_since_solved = 0
            if self._on_move:
                self._on_move(msg.move, msg.solved)
        elif msg.solved:
            d.moves_since_solved = 0
            d.solving = False
        self._on_update()

    def _mixed_distance(self, facelets: str) -> int | None | Literal[False]:
        """Distance from solved if ``facelets`` count as scrambled, else False."""
        d = self.data
        if protocol.solved_pieces(facelets) > MAX_SOLVED_PIECES:
            return False
        if d.solution is None or d.solution_for != facelets:
            return None  # no solver result for this state; trust the pieces
        distance = len(d.solution)
        return distance if distance >= MIN_SCRAMBLE_DISTANCE else False
