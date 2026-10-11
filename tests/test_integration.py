"""Home Assistant level tests: config flow, setup, entities driven by cube frames.

Requires pytest-homeassistant-custom-component. Bluetooth is patched out;
frames are fed straight into the notification handler.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components import bluetooth
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.qiyi_cube import protocol, solver
from custom_components.qiyi_cube.const import CONF_MAC, DOMAIN

ADDRESS = "CC:A9:00:00:04:E4"
NAME = "XMD-TornadoV4LE-04E4"
MFR = bytes.fromhex("e4040000a9cc01240a0001211e010117")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_real_bluetooth(hass: HomeAssistant):
    hass.config.components.add("bluetooth_adapters")
    hass.config.components.add("bluetooth")
    with (
        patch.object(bluetooth, "async_register_callback", return_value=lambda: None),
        patch.object(bluetooth, "async_last_service_info", return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def fake_solver():
    """The real tables take 30+ minutes to build; pretend they exist."""
    process = MagicMock(start=AsyncMock(), stop=AsyncMock(), solve=AsyncMock(return_value=["L'"]))
    with (
        patch.object(solver, "tables_ready", return_value=True),
        patch.object(solver, "SolverProcess", return_value=process),
    ):
        yield process.solve


def _service_info():
    return SimpleNamespace(
        address=ADDRESS, name=NAME, manufacturer_data={protocol.MANUFACTURER_ID: MFR}
    )


def _state_frame(opcode: int, move: int, facelets: str, ts: int) -> bytes:
    idx = {c: i for i, c in enumerate("LRDUFB")}
    n = [idx[c] for c in facelets]
    raw = bytes(n[i] | n[i + 1] << 4 for i in range(0, 54, 2))
    msg = bytearray([0xFE, 0, opcode]) + ts.to_bytes(4, "big") + raw + bytes([move, 87])
    msg[1] = len(msg) + 2
    crc = protocol.crc16_modbus(msg)
    msg += bytes([crc & 0xFF, crc >> 8])
    msg += bytes((16 - len(msg) % 16) % 16)
    return protocol.encrypt(bytes(msg))


async def test_user_flow(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.qiyi_cube.config_flow.async_discovered_service_info",
        return_value=[_service_info()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_MAC: MFR[:6].hex()}


async def test_entities_follow_cube(hass: HomeAssistant, fake_solver) -> None:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_fire_time_changed,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_MAC: MFR[:6].hex()},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    cube = entry.runtime_data.cube
    client = MagicMock(is_connected=True, write_gatt_char=AsyncMock())
    cube._client = client
    cube.data.connected = True

    solved = protocol.SOLVED_FACELETS
    after_l = "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD"
    cube._on_notify(None, bytearray(_state_frame(0x02, 0, solved, 1000)))
    cube._on_notify(None, bytearray(_state_frame(0x03, 2, after_l, 2000)))
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.xmd_tornadov4le_04e4_solved").state == "off"
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_last_move").state == "L"
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_battery").state == "87"
    assert hass.states.get("event.xmd_tornadov4le_04e4_move").attributes[
        "event_type"
    ] == "L"
    assert client.write_gatt_char.await_count == 2  # both messages ACKed
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_moves_since_solved").state == "1"
    faces = hass.states.get("sensor.xmd_tornadov4le_04e4_solved_faces")
    assert faces.state == "2"  # only R and L survive an L turn
    assert faces.attributes["facelets"] == after_l
    assert faces.attributes["face_u"] == "BUUBUUBUU"

    # The solution is searched once the cube has been still for a moment.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    fake_solver.assert_called_once_with(after_l, 1.0, 20)
    to_solve = hass.states.get("sensor.xmd_tornadov4le_04e4_moves_to_solve")
    assert to_solve.state == "1"
    assert to_solve.attributes["solution"] == "L'"

    cube._on_notify(None, bytearray(_state_frame(0x03, 1, solved, 3500)))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.xmd_tornadov4le_04e4_solved").state == "on"
    # L, L' without scramble or inspection is fidgeting, not a solve.
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_last_solve_moves").state == "unknown"
    assert hass.states.get("binary_sensor.xmd_tornadov4le_04e4_solving").state == "off"
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_moves_since_solved").state == "0"
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_solved_faces").state == "6"
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_moves_to_solve").state == "0"
    assert hass.states.get("binary_sensor.xmd_tornadov4le_04e4_connectivity").state == "on"

    # Real gyro frame captured with the cube in its charging box (battery 101).
    in_box = bytes.fromhex("cc1021ba4565fe22fdf1fdf6fe316375")
    cube._on_notify(None, bytearray(protocol.encrypt(in_box)))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_battery").state == "100"
    # It was standing in the box white side up.
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_top_face").state == "white"
    orientation = hass.states.get("sensor.xmd_tornadov4le_04e4_orientation")
    assert orientation.attributes["w"] == -0.522

    cube._on_disconnect(client)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.xmd_tornadov4le_04e4_connectivity").state == "off"
    # Values are kept while the cube sleeps.
    assert hass.states.get("sensor.xmd_tornadov4le_04e4_last_move").state == "L'"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_orientation_stream(hass: HomeAssistant, hass_ws_client) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_MAC: MFR[:6].hex()},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    cube = entry.runtime_data.cube
    client = MagicMock(is_connected=True, write_gatt_char=AsyncMock(), disconnect=AsyncMock())
    cube._client = client
    cube.data.connected = True

    ws = await hass_ws_client(hass)
    await ws.send_json(
        {
            "id": 1,
            "type": "qiyi_cube/subscribe_live",
            "entity_id": "sensor.xmd_tornadov4le_04e4_solved_faces",
        }
    )
    assert (await ws.receive_json())["success"]
    assert (await ws.receive_json())["event"] == {"q": None}

    in_box = bytes.fromhex("cc1021ba4565fe22fdf1fdf6fe316375")
    cube._on_notify(None, bytearray(protocol.encrypt(in_box)))
    assert (await ws.receive_json())["event"] == {"q": [-0.522, -0.478, -0.527, -0.463]}

    after_l = "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD"
    cube._on_notify(None, bytearray(_state_frame(0x02, 0, protocol.SOLVED_FACELETS, 1000)))
    cube._on_notify(None, bytearray(_state_frame(0x03, 2, after_l, 2000)))
    assert (await ws.receive_json())["event"] == {"move": "L", "facelets": after_l}

    cube._on_disconnect(client)
    assert (await ws.receive_json())["event"] == {"q": None}

    await ws.send_json(
        {"id": 2, "type": "qiyi_cube/subscribe_live", "entity_id": "sensor.nope"}
    )
    assert (await ws.receive_json())["error"]["code"] == "not_found"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entity_ids_are_english_in_german(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.config.language = "de"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_MAC: MFR[:6].hex()},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    prefix = "xmd_tornadov4le_04e4"
    assert {
        f"binary_sensor.{prefix}_connectivity",
        f"binary_sensor.{prefix}_solving",
        f"sensor.{prefix}_solved_faces",
        f"sensor.{prefix}_moves_to_solve",
        f"sensor.{prefix}_top_face",
        f"sensor.{prefix}_battery",
        f"event.{prefix}_move",
    } <= ids
    # Names are still translated.
    assert hass.states.get(f"sensor.{prefix}_solved_faces").name.endswith("Gelöste Seiten")
    assert await hass.config_entries.async_unload(entry.entry_id)
