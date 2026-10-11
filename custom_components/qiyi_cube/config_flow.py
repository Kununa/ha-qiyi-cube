"""Config flow for QiYi Smart Cube."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import CONF_MAC, DOMAIN
from .protocol import MANUFACTURER_ID, mac_from_manufacturer_data


def _is_cube(info: BluetoothServiceInfoBleak) -> bool:
    return MANUFACTURER_ID in info.manufacturer_data or (info.name or "").startswith(
        ("XMD-", "QY-QYSC")
    )


def _mac_hex(info: BluetoothServiceInfoBleak) -> str | None:
    if data := info.manufacturer_data.get(MANUFACTURER_ID):
        try:
            return mac_from_manufacturer_data(data).hex()
        except ValueError:
            return None
    return None


class QiYiCubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for QiYi Smart Cube."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_cube(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self._create(self._discovery)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(self._discovered[address])

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in current and _is_cube(info):
                self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{info.name} ({addr})"
                            for addr, info in self._discovered.items()
                        }
                    )
                }
            ),
        )

    def _create(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        data = {CONF_ADDRESS: info.address}
        if mac := _mac_hex(info):
            data[CONF_MAC] = mac
        return self.async_create_entry(title=info.name or info.address, data=data)
