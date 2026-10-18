"""Write the small room-photo fixtures used by the browser tests.

Run from the repository root: `.venv/bin/python frontend/tests/fixtures/photos/make_photos.py`.
"""

import random
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent


def main() -> None:
    Image.new("RGB", (32, 24), "#4a6fa5").save(ROOT / "overview.png")
    Image.new("RGB", (24, 16), "#3c8d5a").save(ROOT / "desk.jpg", quality=90)
    Image.new("RGB", (30, 20), "#d8b13a").save(ROOT / "camera.jpg", quality=90)

    # Stored 40 x 20, red left and blue right. EXIF orientation 6 means "turn 90 degrees
    # clockwise to display", so upright it is 20 x 40 with red on top.
    sideways = Image.new("RGB", (40, 20), "#0000ff")
    sideways.paste(Image.new("RGB", (20, 20), "#ff0000"), (0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    sideways.save(ROOT / "sideways.jpg", quality=95, exif=exif)

    # Phones often add extra pictures (HDR gain maps, previews) to a JPEG. Pillow reports such a
    # file as "MPO", though it is an ordinary JPEG to the user.
    first = Image.new("RGB", (36, 24), "#9b59b6")
    first.save(ROOT / "multi-picture.jpg", format="MPO", save_all=True,
               append_images=[Image.new("RGB", (18, 12), "#ffffff")])

    # The sideways photo again, in CMYK colour: PNG cannot store CMYK, so the upright copy needs
    # converting. Red is C=0 M=255 Y=255 K=0; blue is C=255 M=255 Y=0 K=0.
    cmyk = Image.new("CMYK", (40, 20), (255, 255, 0, 0))
    cmyk.paste(Image.new("CMYK", (20, 20), (0, 255, 255, 0)), (0, 0))
    cmyk.save(ROOT / "cmyk-sideways.jpg", quality=95, exif=exif)

    # 600 x 500 = 300,000 pixels: over the test server's 250,000-pixel limit, but tiny on disk.
    Image.new("RGB", (600, 500), "#777777").save(ROOT / "too-many-pixels.png")

    # Random noise does not compress: over the test server's 64 KiB limit, few pixels.
    noise = random.Random(24)
    data = bytes(noise.randrange(256) for _ in range(160 * 160 * 3))
    Image.frombytes("RGB", (160, 160), data).save(ROOT / "too-many-bytes.png")

    (ROOT / "not-a-photo.jpg").write_bytes(b"This is a text file named like a photo.\n")


if __name__ == "__main__":
    main()
