"""Render the header mark from logo.svg, safely.

Textual 8 has no SVG renderer, and pulling a full SVG library in for one 24-unit mark would be worse
than the problem: more dependency, more surface. This module understands a deliberately small subset
and *refuses* anything else instead of ignoring it, so a logo file can never carry code:

    tags        svg, g, polygon, polyline, rect, circle, ellipse, path
    attributes  id, fill, points, x, y, width, height, cx, cy, r, d, viewBox, xmlns
    path        absolute M/L/H/V/Z only - no curves, no relative steps
    colours     #rgb, #rrggbb, or "none" (which erases, so rings and holes are possible)

Rendering is a painter's pass over a small pixel grid, then half-block characters put two pixels in
each terminal cell. The one animation the app needs - a pulsing marker - is a brightness applied to
the shape whose id is "pulse" at render time, which keeps the file itself static.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from rich.color import Color
from rich.style import Style
from rich.text import Text

SAFE_TAGS = {"svg", "g", "polygon", "polyline", "rect", "circle", "ellipse", "path"}
SAFE_ATTRS = {"id", "fill", "points", "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "d", "viewBox", "xmlns"}
HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
PATH_TOKEN = re.compile(r"[MLHVZmlhvz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
FORBIDDEN_TEXT = ("<!doctype", "<!entity", "&")
MAX_BYTES = 64 * 100024
MAX_SHAPES = 256


class UnsafeSVG(ValueError):
    """The file asked for something outside the allowlist. Never rendered."""


@dataclass(frozen=True)
class Shape:
    kind: str
    fill: tuple[int, int, int] | None
    name: str
    points: tuple[tuple[float, float], ...] = ()
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def contains(self, x: float, y: float) -> bool:
        if self.kind in {"polygon", "polyline"}:
            return _point_in_polygon(x, y, self.points)
        left, top, width, height = self.box
        if self.kind == "rect":
            return left <= x <= left + width and top <= y <= top + height
        if self.kind == "circle":
            radius = width
            return (x - left) ** 2 + (y - top) ** 2 <= radius ** 2
        if self.kind == "ellipse":
            if not width or not height:
                return False
            return ((x - left) / width) ** 2 + ((y - top) / height) ** 2 <= 1.0
        return False


def _point_in_polygon(x: float, y: float, points: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    total = len(points)
    for index in range(total):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % total]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def _colour(value: str | None) -> tuple[int, int, int] | None:
    if value is None or value.strip().lower() == "none":
        return None
    value = value.strip()
    if not HEX_COLOUR.match(value):
        raise UnsafeSVG(f"colour {value!r} is not a hex value or none")
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _numbers(text: str) -> list[float]:
    return [float(token) for token in PATH_TOKEN.findall(text) if token[0] not in "MLHVZmlhvz"]


def _path_points(command: str) -> tuple[tuple[float, float], ...]:
    """Absolute M/L/H/V/Z only. Curves and relative steps are refused, not approximated."""
    tokens = PATH_TOKEN.findall(command)
    if not tokens:
        raise UnsafeSVG("empty path")
    points: list[tuple[float, float]] = []
    cursor = (0.0, 0.0)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token[0].isalpha():
            raise UnsafeSVG("path data must start with a command")
        upper = token.upper()
        if token != upper:
            raise UnsafeSVG(f"relative path command {token!r} is not supported")
        if upper == "Z":
            index += 1
            continue
        index += 1
        if upper in {"M", "L"}:
            while index + 1 < len(tokens) and not tokens[index][0].isalpha():
                cursor = (float(tokens[index]), float(tokens[index + 1]))
                points.append(cursor)
                index += 2
        elif upper == "H":
            while index < len(tokens) and not tokens[index][0].isalpha():
                cursor = (float(tokens[index]), cursor[1])
                points.append(cursor)
                index += 1
        elif upper == "V":
            while index < len(tokens) and not tokens[index][0].isalpha():
                cursor = (cursor[0], float(tokens[index]))
                points.append(cursor)
                index += 1
        else:
            raise UnsafeSVG(f"path command {token!r} is not supported")
    if len(points) < 3:
        raise UnsafeSVG("a path needs at least three points to fill")
    return tuple(points)


class Logo:
    """A parsed logo: shapes in paint order plus the viewBox they were authored in."""

    def __init__(self, shapes: list[Shape], viewbox: tuple[float, float, float, float]) -> None:
        self.shapes = shapes
        self.viewbox = viewbox

    @classmethod
    def load(cls, path: str | Path) -> "Logo":
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise UnsafeSVG(f"cannot read {path}: {error}") from error
        if len(raw.encode("utf-8")) > MAX_BYTES:
            raise UnsafeSVG(f"{path} is larger than {MAX_BYTES} bytes")
        lowered = raw.lower()
        for needle in FORBIDDEN_TEXT:
            if needle in lowered:
                raise UnsafeSVG(f"{path} contains {needle!r}; entities and doctypes are refused")
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as error:
            raise UnsafeSVG(f"{path} is not XML: {error}") from error
        if _tag(root) != "svg":
            raise UnsafeSVG(f"{path} does not start with <svg>")
        viewbox = cls._viewbox(root)
        shapes: list[Shape] = []
        cls._walk(root, shapes)
        if not shapes:
            raise UnsafeSVG(f"{path} has no drawable shapes")
        return cls(shapes, viewbox)

    @staticmethod
    def _viewbox(root: ElementTree.Element) -> tuple[float, float, float, float]:
        raw = (root.get("viewBox") or "").replace(",", " ").split()
        if len(raw) != 4:
            raise UnsafeSVG("the root <svg> needs a viewBox of four numbers")
        left, top, width, height = (float(value) for value in raw)
        if width <= 0 or height <= 0:
            raise UnsafeSVG("the viewBox must have a positive width and height")
        return left, top, width, height

    @classmethod
    def _walk(cls, element: ElementTree.Element, shapes: list[Shape]) -> None:
        for child in element:
            tag = _tag(child)
            if tag not in SAFE_TAGS:
                raise UnsafeSVG(f"<{tag}> is not an allowed element")
            for attribute in child.attrib:
                if attribute not in SAFE_ATTRS:
                    raise UnsafeSVG(f"attribute {attribute!r} on <{tag}> is not allowed")
            if tag in {"svg", "g"}:
                cls._walk(child, shapes)
                continue
            if len(shapes) >= MAX_SHAPES:
                raise UnsafeSVG(f"more than {MAX_SHAPES} shapes")
            shapes.append(cls._shape(tag, child))

    @classmethod
    def _shape(cls, tag: str, element: ElementTree.Element) -> Shape:
        name = element.get("id") or ""
        fill = _colour(element.get("fill") or "#ffffff")
        number = lambda key, default=0.0: float(element.get(key, default) or default)  # noqa: E731
        if tag in {"polygon", "polyline"}:
            values = _numbers(element.get("points") or "")
            if len(values) < 6:
                raise UnsafeSVG(f"<{tag}> needs at least three points")
            points = tuple((values[i], values[i + 1]) for i in range(0, len(values) - 1, 2))
            return Shape(tag, fill, name, points=points)
        if tag == "path":
            return Shape("polygon", fill, name, points=_path_points(element.get("d") or ""))
        if tag == "rect":
            return Shape("rect", fill, name, box=(number("x"), number("y"), number("width"), number("height")))
        if tag == "circle":
            return Shape("circle", fill, name, box=(number("cx"), number("cy"), number("r"), 0.0))
        return Shape("ellipse", fill, name, box=(number("cx"), number("cy"), number("rx"), number("ry")))

    def render(self, cols: int, rows: int, *, brighten: dict[str, float] | None = None) -> Text:
        """Paint the logo into a cols x rows pixel grid, then two pixels per cell."""
        if cols <= 0 or rows <= 0:
            raise ValueError("cols and rows must be positive")
        left, top, width, height = self.viewbox
        pixels: list[list[tuple[int, int, int] | None]] = [[None] * cols for _ in range(rows)]
        for shape in self.shapes:
            fill = shape.fill
            if fill is not None and brighten and shape.name in brighten:
                fill = _brighten(fill, brighten[shape.name])
            for row in range(rows):
                y = top + (row + 0.5) * height / rows
                for column in range(cols):
                    x = left + (column + 0.5) * width / cols
                    if shape.contains(x, y):
                        pixels[row][column] = fill
        return _to_text(pixels)


def _tag(element: ElementTree.Element) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        raise UnsafeSVG("comments and processing instructions are not shapes")
    return tag.rsplit("}", 1)[-1].lower()  # strip the namespace


def _brighten(colour: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(min(255, int(channel + (255 - channel) * amount)) for channel in colour)  # type: ignore[return-value]


def _rich(colour: tuple[int, int, int]) -> Color:
    return Color.from_rgb(*colour)


def _to_text(pixels: list[list[tuple[int, int, int] | None]]) -> Text:
    text = Text()
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    for row in range(0, height, 2):
        top_row = pixels[row]
        bottom_row = pixels[row + 1] if row + 1 < height else [None] * width
        for column in range(width):
            upper, lower = top_row[column], bottom_row[column]
            if upper is None and lower is None:
                text.append(" ")
            elif upper is None:
                text.append("▄", style=Style(color=_rich(lower)))
            elif lower is None:
                text.append("▀", style=Style(color=_rich(upper)))
            else:
                text.append("▀", style=Style(color=_rich(upper), bgcolor=_rich(lower)))
        if row + 2 < height:
            text.append("\n")
    return text


def load_default(path: str | Path | None = None) -> Logo:
    """The app's own mark, or a one-pixel placeholder if the file cannot be trusted."""
    target = Path(path) if path else Path(__file__).resolve().parent / "logo.svg"
    return Logo.load(target)
