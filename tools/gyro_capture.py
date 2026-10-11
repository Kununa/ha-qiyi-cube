"""Record the cube's raw quaternion stream for orientation calibration.

Usage: python tools/gyro_capture.py [seconds]

Prints one line per gyro frame (~13/s): time, the four int16 components /1000
in the order sent, and moves as they happen. Hold the cube still in known
orientations and pause between them; stable stretches are easy to find.
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


async def main(seconds: float) -> None:
    adv_mac = {}

    def match(_d, adv):
        if (data := adv.manufacturer_data.get(protocol.MANUFACTURER_ID)) is None:
            return False
        adv_mac["mac"] = protocol.mac_from_manufacturer_data(data)
        return True

    print("waiting for cube (turn a face)...", flush=True)
    device = await BleakScanner.find_device_by_filter(match, timeout=90)
    if device is None:
        print("cube not found")
        return

    cube: QiYiCube

    def on_gyro():
        q = cube.data.quaternion
        print(f"{time.monotonic() - T0:7.2f} Q " + " ".join(f"{v:+.3f}" for v in q), flush=True)

    def on_move(move, solved):
        print(f"{time.monotonic() - T0:7.2f} MOVE {move}", flush=True)

    cube = QiYiCube(device.name or "cube", adv_mac["mac"], lambda: None, on_move, on_gyro)
    await cube.connect(device)
    print(f"{time.monotonic() - T0:7.2f} CONNECTED", flush=True)
    await asyncio.sleep(seconds)
    await cube.disconnect()


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 120))
