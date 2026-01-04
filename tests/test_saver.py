from datetime import datetime
from pathlib import Path

from svg_to_png_live.export.saver import atomic_write_bytes, generate_png_filename


def test_generate_png_filename_is_stable() -> None:
    name = generate_png_filename("abcdef0123456789", now=datetime(2020, 1, 2, 3, 4, 5))
    assert name == "20200102_030405_abcdef0123.png"


def test_atomic_write_bytes(tmp_path: Path) -> None:
    out = tmp_path / "x.png"
    atomic_write_bytes(out, b"123")
    assert out.read_bytes() == b"123"


