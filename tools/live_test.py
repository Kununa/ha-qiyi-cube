"""Exercise the integration's QiYiCube class against a real cube, outside HA.

Usage: python tools/live_test.py [seconds]
"""

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import types

from bleak import BleakScanner

# Load protocol.py/cube.py without importing the HA package __init__.
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


async def main(seconds: float) -> None:
    adv_mac = {}

    def match(_d, adv):
        if protocol.MANUFACTURER_ID in adv.manufacturer_data:
            adv_mac["mac"] = protocol.mac_from_manufacturer_data(
                adv.manufacturer_data[protocol.MANUFACTURER_ID]
            )
            return True
        return False

    print("waiting for cube (turn a face)...", flush=True)
    device = await BleakScanner.find_device_by_filter(match, timeout=60)
    if device is None:
        print("cube not found")
        return

    gyro = {"n": 0}
    cube: QiYiCube

    def on_update():
        d = cube.data
        print(
            f"UPDATE connected={d.connected} battery={d.battery} solved={d.solved} "
            f"moves_since_solved={d.moves_since_solved} solving={d.solving} "
            f"last_solve={d.last_solve}",
            flush=True,
        )

    def on_move(move, solved):
        print(f"MOVE {move:3} solved={solved}", flush=True)

    def on_gyro():
        gyro["n"] += 1

    cube = QiYiCube(device.name or "cube", adv_mac["mac"], on_update, on_move, on_gyro)
    await cube.connect(device)
    await asyncio.sleep(seconds)
    print(f"gyro samples: {gyro['n']}, last quaternion: {cube.data.quaternion}")
    await cube.disconnect()


logging.basicConfig(level=logging.INFO)
asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 30))
