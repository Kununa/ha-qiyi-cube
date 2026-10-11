"""Dump raw decrypted cube frames to find undocumented fields (e.g. charging).

Usage: python tools/capture.py [seconds]

Prints the advertisement, every FE frame in full, and CC (gyro) frames only
when a byte other than sequence/timer/quaternion changes. Plug/unplug the
charger while it runs and watch which bytes react.
"""

import asyncio
import importlib.util
from pathlib import Path
import sys
import time
import types

from bleak import BleakScanner

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "qiyi_cube"
sys.modules["qiyi_cube"] = types.ModuleType("qiyi_cube")
sys.modules["qiyi_cube"].__path__ = [str(PKG)]
for mod in ("protocol", "cube"):
    spec = importlib.util.spec_from_file_location(f"qiyi_cube.{mod}", PKG / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"qiyi_cube.{mod}"] = m
    spec.loader.exec_module(m)

from qiyi_cube import protocol  # noqa: E402
from qiyi_cube.cube import QiYiCube  # noqa: E402

T0 = time.monotonic()


def log(text: str) -> None:
    print(f"{time.monotonic() - T0:7.2f}  {text}", flush=True)


def install_frame_logger() -> None:
    parse = protocol.parse
    last_cc: dict[str, bytes] = {}

    def logging_parse(data: bytes):
        msg = protocol.decrypt(bytes(data))
        length = msg[1]
        if msg[0] == 0xCC:
            # Ignore seq (2), timer (3-4) and quaternion (6-13); keep the rest.
            key = bytes([msg[5]]) + msg[14 : max(length - 2, 14)]
            if key != last_cc.get("key"):
                last_cc["key"] = key
                log(f"CC  len={length} batt={msg[5]} raw={msg[:length].hex(' ')}")
        else:
            log(f"FE  op={msg[2]:#04x} len={length} raw={msg[:length].hex(' ')}")
            if length > 38:
                log(f"    bytes after battery: {msg[36 : length - 2].hex(' ')}")
        return parse(data)

    protocol.parse = logging_parse


async def main(seconds: float) -> None:
    adv_mac = {}

    def match(_d, adv):
        if (data := adv.manufacturer_data.get(protocol.MANUFACTURER_ID)) is None:
            return False
        adv_mac["mac"] = protocol.mac_from_manufacturer_data(data)
        log(f"ADV manufacturer data: {data.hex(' ')}  rssi={adv.rssi}")
        return True

    print("waiting for cube (turn a face)...", flush=True)
    device = await BleakScanner.find_device_by_filter(match, timeout=60)
    if device is None:
        print("cube not found")
        return

    install_frame_logger()
    cube = QiYiCube(
        device.name or "cube", adv_mac["mac"], lambda: None, lambda *_: None, lambda: None
    )
    await cube.connect(device)
    log("connected – plug / unplug the charger now")
    await asyncio.sleep(seconds)
    await cube.disconnect()


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 90))
