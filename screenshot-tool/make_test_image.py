"""Generate a synthetic card-grid screenshot to exercise the OCR pipeline.

Mimics the real layout: icon tile, truncated title, coloured publisher line,
cards laid out in a row with narrow gutters.
"""
import sys

from PIL import Image, ImageDraw, ImageFont

CARDS = [
    ("Hamdoku: S...", "MOBIRIX", (250, 220, 120)),
    ("Coinveyor!", "FTY LLC.", (240, 150, 190)),
    ("Voxel Blast: Cub...", "WODH", (110, 160, 230)),
    ("Dog Maze Puzzle", "ColorBean", (140, 200, 120)),
    ("Little Red - Hide...", "ColorBean", (240, 140, 140)),
    ("Xmasudoku - Fi...", "Casual Candy...", (170, 110, 210)),
    ("Car Flow: Color ...", "EASY PLAY GA...", (120, 200, 230)),
    ("Yarn Art: Knit &...", "WEMIX Global", (200, 170, 230)),
    ("Hooks Jam", "jennywhiteshri...", (230, 180, 110)),
    ("Sizzle Master: B...", "LeoGame Co., Lt...", (240, 130, 110)),
]

SCALE = 2  # render at 2x; small UI text is what makes OCR hard
CARD_W, GUTTER, PAD = 112 * SCALE, 10 * SCALE, 12 * SCALE
ICON = 88 * SCALE


def font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main(out="test_cards.png"):
    f_title = font(11 * SCALE)
    f_pub = font(10 * SCALE)

    w = PAD * 2 + len(CARDS) * CARD_W + (len(CARDS) - 1) * GUTTER
    h = PAD * 2 + ICON + 46 * SCALE
    img = Image.new("RGB", (w, h), (245, 246, 248))
    d = ImageDraw.Draw(img)

    for i, (title, pub, colour) in enumerate(CARDS):
        x = PAD + i * (CARD_W + GUTTER)
        d.rounded_rectangle([x, PAD, x + CARD_W, h - PAD], 8 * SCALE,
                            fill=(255, 255, 255), outline=(225, 227, 230))
        ix = x + (CARD_W - ICON) // 2
        d.rounded_rectangle([ix, PAD + 6 * SCALE, ix + ICON, PAD + 6 * SCALE + ICON],
                            14 * SCALE, fill=colour)

        ty = PAD + 6 * SCALE + ICON + 6 * SCALE
        d.text((x + 6 * SCALE, ty), title, font=f_title, fill=(30, 32, 36))
        d.text((x + 6 * SCALE, ty + 15 * SCALE), pub, font=f_pub,
               fill=(235, 145, 40))

    img.save(out)
    print("wrote {} ({}x{})".format(out, img.width, img.height))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_cards.png")
