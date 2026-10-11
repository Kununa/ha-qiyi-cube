"""Glue between Home Assistant Bluetooth and the QiYiCube connection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
import subprocess
import time

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from . import solver
from .const import (
    CONF_MAC,
    DOMAIN,
    ORIENTATION_UPDATE_INTERVAL,
    SOLVE_DELAY,
    SOLVE_MAX_LENGTH,
    SOLVE_SECONDS,
)
from .cube import QiYiCube
from .protocol import (
    MANUFACTURER_ID,
    is_solved,
    mac_from_address,
    mac_from_manufacturer_data,
)

_LOGGER = logging.getLogger(__name__)

type QiYiCubeConfigEntry = ConfigEntry[QiYiCubeCoordinator]


class QiYiCubeCoordinator:
    """Connects whenever the cube wakes up and fans out updates to entities.

    The cube sleeps when idle and only advertises after being moved, so we
    connect on every advertisement seen while we are not connected.
    """

    def __init__(self, hass: HomeAssistant, entry: QiYiCubeConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        mac = entry.data.get(CONF_MAC)
        self.cube = QiYiCube(
            entry.title,
            bytes.fromhex(mac) if mac else mac_from_address(self.address),
            self._on_update,
            self._on_move,
            self._on_gyro,
        )
        self._update_listeners: list[CALLBACK_TYPE] = []
        self._move_listeners: list[Callable[[str, bool], None]] = []
        self._orientation_listeners: list[CALLBACK_TYPE] = []
        self._gyro_listeners: list[CALLBACK_TYPE] = []
        self._last_orientation_push = 0.0
        self._connect_task: asyncio.Task | None = None
        self._solver: solver.SolverProcess | None = None
        self._solver_ready = False
        self._solving = False
        self._solve_timer: CALLBACK_TYPE | None = None
        self._seen_facelets: str | None = None
        self._solution_for: str | None = None

    @property
    def data(self):
        return self.cube.data

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Watch advertisements; returns the unsubscribe callback."""
        cancel = bluetooth.async_register_callback(
            self.hass,
            self._on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        if service_info := bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        ):
            self._on_advertisement(service_info, bluetooth.BluetoothChange.ADVERTISEMENT)
        self.entry.async_create_background_task(
            self.hass, self._async_prepare_solver(), "qiyi_cube prepare solver"
        )
        return cancel

    async def async_stop(self) -> None:
        if self._connect_task:
            self._connect_task.cancel()
        if self._solve_timer:
            self._solve_timer()
        if self._solver:
            await self._solver.stop()
        await self.cube.disconnect()

    @callback
    def _on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        if CONF_MAC not in self.entry.data and (
            data := service_info.manufacturer_data.get(MANUFACTURER_ID)
        ):
            # Older entries or name-only discovery: learn the MAC for the handshake.
            mac = mac_from_manufacturer_data(data)
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_MAC: mac.hex()}
            )
            self.cube._mac = mac  # noqa: SLF001
        if self.cube.connected or (self._connect_task and not self._connect_task.done()):
            return
        self._connect_task = self.entry.async_create_background_task(
            self.hass, self._async_connect(), f"qiyi_cube connect {self.address}"
        )

    async def _async_connect(self) -> None:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return
        try:
            await self.cube.connect(device)
        except (BleakError, TimeoutError) as err:
            # The cube may have gone back to sleep; the next advertisement retries.
            _LOGGER.debug("%s: connect failed: %s", self.address, err)

    # --- listeners -----------------------------------------------------------

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        return self._add(self._update_listeners, update)

    @callback
    def async_add_move_listener(
        self, on_move: Callable[[str, bool], None]
    ) -> CALLBACK_TYPE:
        return self._add(self._move_listeners, on_move)

    @callback
    def async_add_orientation_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        return self._add(self._orientation_listeners, update)

    @callback
    def async_add_gyro_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Every gyro sample (~13/s), unthrottled; for the card's live 3D view."""
        return self._add(self._gyro_listeners, update)

    @staticmethod
    def _add(listeners: list, item) -> CALLBACK_TYPE:
        listeners.append(item)
        return lambda: listeners.remove(item)

    def _on_update(self) -> None:
        if (facelets := self.data.facelets) != self._seen_facelets:
            self._seen_facelets = facelets
            self._facelets_changed(facelets)
        self._notify()

    def _notify(self) -> None:
        for update in list(self._update_listeners):
            update()

    def _on_move(self, move: str, solved: bool) -> None:
        for on_move in list(self._move_listeners):
            on_move(move, solved)

    def _on_gyro(self) -> None:
        for update in list(self._gyro_listeners):
            update()
        now = time.monotonic()
        if now - self._last_orientation_push < ORIENTATION_UPDATE_INTERVAL:
            return
        self._last_orientation_push = now
        for update in list(self._orientation_listeners):
            update()

    # --- solution search -------------------------------------------------------

    async def _async_prepare_solver(self) -> None:
        folder = self.hass.config.cache_path(DOMAIN, "twophase")
        try:
            if not await self.hass.async_add_executor_job(solver.tables_ready, folder):
                _LOGGER.warning(
                    "Building the cube solver tables in %s; this runs once and "
                    "takes 30-60 minutes. Until then there is no solution sensor",
                    folder,
                )
                await self.hass.async_add_executor_job(solver.build_tables, folder)
            # Searching runs in its own process so it never blocks the event loop.
            self._solver = solver.SolverProcess(folder)
            await self._solver.start()
        except (OSError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as err:
            _LOGGER.error("Cube solver unavailable: %s", err)
            return
        self._solver_ready = True
        self._start_solve(None)

    def _facelets_changed(self, facelets: str | None) -> None:
        if self._solve_timer:
            self._solve_timer()
            self._solve_timer = None
        if facelets is None:
            return
        if is_solved(facelets):
            self.data.solution = []
            self.data.solution_for = self._solution_for = facelets
        else:
            self._solve_timer = async_call_later(
                self.hass, SOLVE_DELAY, self._start_solve
            )

    @callback
    def _start_solve(self, _now: datetime | None) -> None:
        self._solve_timer = None
        if self._solver_ready and not self._solving:
            self.entry.async_create_background_task(
                self.hass, self._async_solve(), "qiyi_cube solve"
            )

    async def _async_solve(self) -> None:
        self._solving = True
        try:
            # Re-run if the cube was turned while searching.
            while (facelets := self.data.facelets) not in (None, self._solution_for):
                try:
                    moves = await self._solver.solve(facelets, SOLVE_SECONDS, SOLVE_MAX_LENGTH)
                except ValueError as err:
                    _LOGGER.debug("%s: cannot solve %s: %s", self.address, facelets, err)
                    moves = None
                except RuntimeError as err:
                    _LOGGER.warning("%s: solver failed: %s", self.address, err)
                    moves = None
                if facelets == self.data.facelets:  # else outdated, loop again
                    self.data.solution_for = self._solution_for = facelets
                    self.data.solution = moves
                    self._notify()
        finally:
            self._solving = False
