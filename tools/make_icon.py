"""Render the integration's brand icon (an isometric 3x3 cube like the card's).

Usage: python tools/make_icon.py  ->  custom_components/qiyi_cube/brand/icon*.png
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "qiyi_cube" / "brand"
BODY = (22, 22, 22, 255)
BODY_DARK = (64, 64, 64, 255)  # dark theme: lighter body so the cube stands out
TOP, LEFT, RIGHT = (244, 244, 244), (31, 166, 74), (215, 38, 61)  # white, green, red
SHADE = {"top": 1.0, "left": 0.86, "right": 0.74}  # simple lighting per face
SS = 8  # supersampling factor for anti-aliasing


def render(size: int, body: tuple[int, int, int, int] = BODY) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = math.cos(math.pi / 6)
    # Cube spans 3 units per axis; its silhouette is 6c wide and 6 high.
    s = big * 0.92 / 6
    ox, oy = big / 2, big / 2

    def p(x: float, y: float, z: float) -> tuple[float, float]:
        # Centre the cube (coordinates 0..3) on the image.
        x, y, z = x - 1.5, y - 1.5, z - 1.5
        return (ox + (x - y) * c * s, oy + (x + y) * 0.5 * s - z * s)

    def rounded_poly(points, radius):
        """Polygon with rounded corners (corners cut by short arcs)."""
        out = []
        n = len(points)
        for i in range(n):
            a, b, nxt = points[i - 1], points[i], points[(i + 1) % n]
            for t in range(9):  # quadratic Bézier around corner b
                f = t / 8
                da = [(a[k] - b[k]) for k in range(2)]
                dn = [(nxt[k] - b[k]) for k in range(2)]
                la, ln = math.hypot(*da), math.hypot(*dn)
                p0 = [b[k] + da[k] / la * radius for k in range(2)]
                p2 = [b[k] + dn[k] / ln * radius for k in range(2)]
                out.append(
                    tuple((1 - f) ** 2 * p0[k] + 2 * (1 - f) * f * b[k] + f**2 * p2[k] for k in range(2))
                )
        return out

    # Body: the cube's hexagonal silhouette, slightly enlarged, rounded.
    hexagon = [p(0, 0, 3), p(3, 0, 3), p(3, 0, 0), p(3, 3, 0), p(0, 3, 0), p(0, 3, 3)]
    cx = sum(q[0] for q in hexagon) / 6
    cy = sum(q[1] for q in hexagon) / 6
    grow = 1.035
    hexagon = [(cx + (q[0] - cx) * grow, cy + (q[1] - cy) * grow) for q in hexagon]
    draw.polygon(rounded_poly(hexagon, 0.35 * s), fill=body)

    gap, radius = 0.09, 0.16 * s

    def sticker(corners, color, face):
        shade = SHADE[face]
        fill = tuple(int(v * shade) for v in color) + (255,)
        draw.polygon(rounded_poly(corners, radius), fill=fill)

    for i in range(3):
        for j in range(3):
            a0, a1, b0, b1 = i + gap, i + 1 - gap, j + gap, j + 1 - gap
            sticker([p(a0, b0, 3), p(a1, b0, 3), p(a1, b1, 3), p(a0, b1, 3)], TOP, "top")
            # y = 3 face (front left): x = i, z = j
            sticker([p(a0, 3, 3 - b0), p(a1, 3, 3 - b0), p(a1, 3, 3 - b1), p(a0, 3, 3 - b1)], LEFT, "left")
            # x = 3 face (front right): y = i, z = j
            sticker([p(3, a0, 3 - b0), p(3, a1, 3 - b0), p(3, a1, 3 - b1), p(3, a0, 3 - b1)], RIGHT, "right")

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for prefix, body in (("", BODY), ("dark_", BODY_DARK)):
        for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
            render(size, body).save(OUT / f"{prefix}{name}", optimize=True)
            print("wrote", OUT / f"{prefix}{name}")


if __name__ == "__main__":
    main()
