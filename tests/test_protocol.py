"""Offline tests for the QiYi protocol, using frames captured from a Tornado V4 AI."""

import importlib.util
import math
from pathlib import Path
import struct
import sys

import pytest

_PATH = Path(__file__).parent.parent / "custom_components" / "qiyi_cube" / "protocol.py"
_spec = importlib.util.spec_from_file_location("qiyi_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["qiyi_protocol"] = protocol
_spec.loader.exec_module(protocol)

# Decrypted gyro frames captured from XMD-TornadoV4LE-04E4.
GYRO_PLAIN = [
    "cc100004f56401270011000603b988f2",
    "cc103d78406403bb0121000000029b70",
]


def _plain_state_frame(opcode: int, move: int, facelet_bytes: bytes, battery=100):
    msg = bytearray([0xFE, 0, opcode]) + (536195033).to_bytes(4, "big")
    msg += facelet_bytes + bytes([move, battery])
    msg[1] = len(msg) + 2
    crc = protocol.crc16_modbus(msg)
    msg += bytes([crc & 0xFF, crc >> 8])
    msg += bytes((16 - len(msg) % 16) % 16)
    return protocol.encrypt(bytes(msg))


def _solved_bytes() -> bytes:
    # Inverse of parse_facelets for a solved cube in URFDLB order.
    idx = {c: i for i, c in enumerate("LRDUFB")}
    nibbles = [idx[c] for c in protocol.SOLVED_FACELETS]
    return bytes(nibbles[i] | nibbles[i + 1] << 4 for i in range(0, 54, 2))


def test_crc_roundtrip():
    frame = protocol.decrypt(protocol.build_frame(b"\x03\x01\x02\x03\x04"))
    assert frame[0] == 0xFE and frame[1] == 9
    assert protocol.crc16_modbus(frame[:9]) == 0


@pytest.mark.parametrize("hex_frame", GYRO_PLAIN)
def test_gyro(hex_frame):
    msg = protocol.parse(protocol.encrypt(bytes.fromhex(hex_frame)))
    assert isinstance(msg, protocol.GyroSample)
    assert msg.battery == 100
    norm = sum(v * v for v in msg.quaternion) ** 0.5
    assert norm == pytest.approx(1.0, abs=0.01)


def test_hello_state():
    msg = protocol.parse(_plain_state_frame(0x02, 0, _solved_bytes()))
    assert isinstance(msg, protocol.CubeState)
    assert msg.facelets == protocol.SOLVED_FACELETS
    assert msg.solved and msg.move is None and msg.battery == 100
    ack = protocol.decrypt(msg.ack)
    assert ack[:7] == bytes([0xFE, 9, 0x02]) + (536195033).to_bytes(4, "big")


def test_move_state():
    msg = protocol.parse(_plain_state_frame(0x03, 2, _solved_bytes()))
    assert msg.move == "L"


def test_corrupt_frame_rejected():
    frame = bytearray(protocol.decrypt(_plain_state_frame(0x03, 2, _solved_bytes())))
    frame[10] ^= 0xFF
    assert protocol.parse(protocol.encrypt(bytes(frame))) is None
    assert protocol.parse(b"\x00" * 7) is None


def test_mac_helpers():
    adv = bytes.fromhex("e4040000a9cc01240a0001211e010117")
    assert protocol.mac_from_manufacturer_data(adv) == protocol.mac_from_address(
        "CC:A9:00:00:04:E4"
    )


def test_is_solved():
    assert protocol.is_solved(protocol.SOLVED_FACELETS)
    assert not protocol.is_solved(
        "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD"
    )


def test_solved_faces():
    after_l = "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD"
    assert protocol.solved_faces(protocol.SOLVED_FACELETS) == 6
    assert protocol.solved_faces(after_l) == 2
    assert protocol.split_faces(after_l)["L"] == "LLLLLLLLL"


def gyro_frame(raw_q: tuple[float, float, float, float], battery: int = 100) -> bytes:
    """Encrypted 0xCC frame with quaternion components in wire order."""
    msg = bytearray([0xCC, 16, 0x2F, 0x04, 0xF5, battery])
    msg += struct.pack(">4h", *(round(v * 1000) for v in raw_q))
    crc = protocol.crc16_modbus(msg)
    return protocol.encrypt(bytes(msg + bytes([crc & 0xFF, crc >> 8])))


# Mean quaternions (wire order) while holding each colour up, 2026-10-11.
CALIBRATION = [
    ((-0.615, -0.356, -0.346, -0.608), "U"),  # white up, green front
    ((-0.678, 0.203, 0.208, -0.671), "U"),  # white up, turned on the table
    ((0.676, -0.199, 0.203, -0.675), "D"),  # yellow
    ((-0.003, 0.005, 0.289, -0.955), "F"),  # green
    ((-0.951, 0.302, 0.002, 0.004), "B"),  # blue
    ((-0.68, 0.209, -0.664, -0.217), "R"),  # red
    ((0.197, 0.68, -0.208, 0.671), "L"),  # orange
    ((0.631, 0.33, 0.315, 0.623), "U"),  # white again (sign-flipped q)
]


@pytest.mark.parametrize(("raw_q", "face"), CALIBRATION)
def test_top_face_from_calibration(raw_q, face):
    msg = protocol.parse(gyro_frame(raw_q))
    assert isinstance(msg, protocol.GyroSample)
    assert msg.quaternion[0] == raw_q[2]  # w is the third component on the wire
    assert protocol.top_face(msg.quaternion) == face


def test_top_face_none_when_tilted():
    # 45° about the cube's y axis: U and F equally up.
    c = math.cos(math.pi / 8)
    s = math.sin(math.pi / 8)
    assert protocol.top_face((c, 0.0, s, 0.0)) is None


def test_piece_indices_match_twophase():
    defs = pytest.importorskip("twophase.defs")
    assert [tuple(c) for c in defs.cornerFacelet] == list(protocol.CORNERS)
    assert [tuple(e) for e in defs.edgeFacelet] == list(protocol.EDGES)


def test_solved_pieces():
    after_l = "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD"
    assert protocol.solved_pieces(protocol.SOLVED_FACELETS) == 20
    assert protocol.solved_pieces(after_l) == 20 - 4 - 4  # L turn moves 4+4 pieces
