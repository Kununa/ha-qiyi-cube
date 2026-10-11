"""QiYi smart cube BLE protocol (X-Man Tornado V4 AI and other QiYi cubes).

Pure Python, no Home Assistant imports, so it can be tested standalone.

Frames on characteristic FFF6 are AES-128-ECB encrypted in 16-byte blocks.
Decrypted, a frame is: header byte, total length, payload..., CRC16-MODBUS (LE),
zero padding. Header 0xFE carries cube messages, 0xCC carries gyro samples.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000fff6-0000-1000-8000-00805f9b34fb"
MANUFACTURER_ID = 0x0504

_KEY = bytes(
    [87, 177, 249, 171, 205, 90, 232, 167, 156, 185, 140, 231, 87, 140, 81, 8]
)

OP_HELLO = 0x02
OP_STATE_CHANGE = 0x03

MOVES = {
    1: "L'", 2: "L", 3: "R'", 4: "R", 5: "D'", 6: "D",
    7: "U'", 8: "U", 9: "F'", 10: "F", 11: "B'", 12: "B",
}

SOLVED_FACELETS = "".join(f * 9 for f in "URFDLB")


def _cipher() -> Cipher:
    return Cipher(algorithms.AES(_KEY), modes.ECB())


def encrypt(data: bytes) -> bytes:
    enc = _cipher().encryptor()
    return enc.update(data) + enc.finalize()


def decrypt(data: bytes) -> bytes:
    dec = _cipher().decryptor()
    return dec.update(data) + dec.finalize()


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(content: bytes) -> bytes:
    """Wrap an app->cube message (opcode + payload) into an encrypted frame."""
    msg = bytearray([0xFE, 4 + len(content)]) + content
    crc = crc16_modbus(msg)
    msg += bytes([crc & 0xFF, crc >> 8])
    msg += bytes((16 - len(msg) % 16) % 16)
    return encrypt(bytes(msg))


def mac_from_manufacturer_data(data: bytes) -> bytes:
    """Return the 6 MAC bytes (reversed order, as the hello wants) from adv data."""
    if len(data) < 6:
        raise ValueError("manufacturer data too short")
    return bytes(data[:6])


def mac_from_address(address: str) -> bytes:
    """Return reversed MAC bytes from an 'AA:BB:CC:DD:EE:FF' address."""
    return bytes(reversed(bytes.fromhex(address.replace(":", ""))))


def build_hello(mac_reversed: bytes) -> bytes:
    return build_frame(
        bytes([0x00, 0x6B, 0x01, 0x00, 0x00, 0x22, 0x06, 0x00, 0x02, 0x08, 0x00])
        + mac_reversed
    )


def parse_facelets(raw: bytes) -> str:
    """Decode 27 bytes (54 nibbles) into a URFDLB facelet string."""
    return "".join(
        "LRDUFB"[(raw[i >> 1] >> ((i % 2) * 4)) & 0xF] for i in range(54)
    )


@dataclass(frozen=True)
class CubeState:
    """Hello (0x02) or state change (0x03) message from the cube."""

    opcode: int
    timestamp_ms: int
    facelets: str
    battery: int
    move: str | None
    ack: bytes  # encrypted frame that must be written back

    @property
    def solved(self) -> bool:
        return is_solved(self.facelets)


@dataclass(frozen=True)
class GyroSample:
    """Orientation sample (0xCC), quaternion (w, x, y, z) scaled to unit length."""

    sequence: int
    battery: int
    quaternion: tuple[float, float, float, float]


@dataclass(frozen=True)
class Unknown:
    opcode: int
    raw: bytes


Message = CubeState | GyroSample | Unknown


FACES = "URFDLB"


def split_faces(facelets: str) -> dict[str, str]:
    """Facelet string -> {"U": 9 facelets, "R": …} in URFDLB order."""
    return {f: facelets[i * 9 : i * 9 + 9] for i, f in enumerate(FACES)}


def solved_faces(facelets: str) -> int:
    return sum(len(set(face)) == 1 for face in split_faces(facelets).values())


def is_solved(facelets: str) -> bool:
    return solved_faces(facelets) == 6


# Facelet indices of each piece, Kociemba order (same as twophase.defs).
CORNERS = (
    (8, 9, 20), (6, 18, 38), (0, 36, 47), (2, 45, 11),
    (29, 26, 15), (27, 44, 24), (33, 53, 42), (35, 17, 51),
)  # fmt: skip
EDGES = (
    (5, 10), (7, 19), (3, 37), (1, 46), (32, 16), (28, 25),
    (30, 43), (34, 52), (23, 12), (21, 41), (50, 39), (48, 14),
)  # fmt: skip


def solved_pieces(facelets: str) -> int:
    """Corners and edges (0..20) sitting in place with the right orientation."""
    return sum(
        all(facelets[i] == FACES[i // 9] for i in piece) for piece in CORNERS + EDGES
    )


# Cube-frame axis (index, sign) pointing up -> face on top. Calibrated by
# holding each centre colour up (white = U, green = F, red = R).
_UP_AXIS_FACE = {
    (0, 1): "U", (0, -1): "D",
    (1, 1): "L", (1, -1): "R",
    (2, 1): "F", (2, -1): "B",
}  # fmt: skip


def up_vector(q: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """Gravity "up" in cube coordinates for a (w, x, y, z) orientation."""
    w, x, y, z = q
    return (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))


def top_face(q: tuple[float, float, float, float], min_up: float = 0.8) -> str | None:
    """Face pointing up, or None while tilted more than ~37° away from any face."""
    v = up_vector(q)
    axis = max(range(3), key=lambda i: abs(v[i]))
    if abs(v[axis]) < min_up:
        return None
    return _UP_AXIS_FACE[(axis, 1 if v[axis] > 0 else -1)]


def parse(data: bytes) -> Message | None:
    """Decrypt and parse one notification. Returns None for corrupt frames."""
    if not data or len(data) % 16:
        return None
    msg = decrypt(bytes(data))
    header, length = msg[0], msg[1]
    if header not in (0xFE, 0xCC) or length < 5 or length > len(msg):
        return None
    msg = msg[:length]
    if crc16_modbus(msg) != 0:
        return None

    if header == 0xCC and length == 16:
        # Wire order is x, y, w, z (calibrated against gravity 2026-10-11).
        x, y, w, z = (v / 1000 for v in struct.unpack(">4h", msg[6:14]))
        return GyroSample(sequence=msg[2], battery=msg[5], quaternion=(w, x, y, z))

    opcode = msg[2]
    if header == 0xFE and opcode in (OP_HELLO, OP_STATE_CHANGE) and length >= 38:
        return CubeState(
            opcode=opcode,
            timestamp_ms=int.from_bytes(msg[3:7], "big"),
            facelets=parse_facelets(msg[7:34]),
            battery=msg[35],
            move=MOVES.get(msg[34]) if opcode == OP_STATE_CHANGE else None,
            ack=build_frame(msg[2:7]),
        )
    return Unknown(opcode=opcode if header == 0xFE else header, raw=msg)
