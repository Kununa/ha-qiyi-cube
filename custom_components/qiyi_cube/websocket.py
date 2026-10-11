"""Websocket API: live orientation and move stream for the Lovelace card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe_live)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/subscribe_live",
        vol.Required("entity_id"): str,
    }
)
@callback
def ws_subscribe_live(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream live data of the cube that owns ``entity_id``.

    Sends ``{"q": [w, x, y, z]}`` on every gyro sample, ``{"q": null}`` when
    the cube disconnects, and ``{"move": "R'", "facelets": "..."}`` (state after
    the move) on every quarter turn. Bypasses entity states and the recorder.
    """
    entity = er.async_get(hass).async_get(msg["entity_id"])
    entry = entity and hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        connection.send_error(msg["id"], "not_found", "No loaded QiYi cube for entity")
        return
    coordinator = entry.runtime_data

    @callback
    def send() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], {"q": coordinator.data.quaternion})
        )

    sent_none = coordinator.data.quaternion is None

    @callback
    def on_update() -> None:
        # Tell the card once when the stream stops (disconnect).
        nonlocal sent_none
        if coordinator.data.quaternion is None and not sent_none:
            sent_none = True
            send()
        elif coordinator.data.quaternion is not None:
            sent_none = False

    @callback
    def on_move(move: str, _solved: bool) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"move": move, "facelets": coordinator.data.facelets}
            )
        )

    unsubs = [
        coordinator.async_add_gyro_listener(send),
        coordinator.async_add_listener(on_update),
        coordinator.async_add_move_listener(on_move),
    ]
    connection.subscriptions[msg["id"]] = lambda: [unsub() for unsub in unsubs]
    connection.send_result(msg["id"])
    send()
