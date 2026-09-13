"""User-approved local white-background removal for the supplied logo."""
import argparse
from pathlib import Path
from PIL import Image


def prepare(source, destination):
    image = Image.open(source).convert("RGBA")
    pixels = []
    for r, g, b, alpha in image.getdata():
        # Neutral white/grey pixels are black artwork antialiased over white.
        # Recover their coverage; cyan artwork retains its original colour.
        if max(r, g, b) - min(r, g, b) <= 3:
            coverage = 255 - min(r, g, b)
            if coverage <= 4:
                coverage = 0
            pixels.append((0, 0, 0, round(alpha * coverage / 255)))
        else:
            pixels.append((r, g, b, alpha))
    image.putdata(pixels)
    bounds = image.getbbox()
    if bounds:
        image = image.crop(bounds)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    image.save(destination.with_suffix(".ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    assert image.getextrema()[3][0] == 0
    return image.size


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    print(prepare(args.source, args.destination))
