"""Render a trusted local PNG as Rich terminal half-block pixels."""
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from rich.color import Color
from rich.style import Style
from rich.text import Text

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 1024 * 1024

class Logo:
    def __init__(self, image: Image.Image):
        self.image = image.copy().convert('RGBA')

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('logo.png exceeds 2 MB')
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
               source.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            if source.format != 'PNG':
                raise ValueError('logo must be PNG')
            return cls(source)

    def render(self, cols, rows, *, brighten=None):
        if not (1 <= cols <= 256 and 1 <= rows <= 256):
            raise ValueError('invalid terminal logo size')
        image = self.image.resize((cols, rows), Image.Resampling.NEAREST)
        result = Text()
        for y in range(0, rows, 2):
            for x in range(cols):
                top = image.getpixel((x, y))
                bottom = image.getpixel((x, y + 1)) if y + 1 < rows else (0, 0, 0, 0)
                a = top[:3] if top[3] >= 128 else None
                b = bottom[:3] if bottom[3] >= 128 else None
                if a is None and b is None:
                    result.append(' ')
                elif a is None:
                    result.append('▄', style=Style(color=Color.from_rgb(*b)))
                elif b is None:
                    result.append('▀', style=Style(color=Color.from_rgb(*a)))
                else:
                    result.append('▀', style=Style(color=Color.from_rgb(*a), bgcolor=Color.from_rgb(*b)))
            if y + 2 < rows:
                result.append('\n')
        return result

def load_default(path=None):
    return Logo.load(Path(path) if path else Path(__file__).resolve().parent / 'logo.png')
