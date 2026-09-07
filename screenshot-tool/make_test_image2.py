"""Generate a grid screenshot that mimics the REAL ad-intel layout.

Differences from make_test_image.py that matter for card pairing:
  * multiple rows, not one
  * a country badge ("TH", "KR") sitting on the icon, which OCR also reads
  * a store badge glyph at the end of the title line
  * a star glyph at the start of the publisher line

The country badge is the suspicious one: it is a separate text line close
above the title, so it can be mistaken for part of the card's text stack.
"""
import sys

from PIL import Image, ImageDraw, ImageFont

CARDS = [
    ("Roads of Da Vinci 1", "8FLOOR COMPANY", "TH", (206, 122, 90)),
    ("Hamdoku: Sudoku L...", "MOBIRIX", "KR", (243, 232, 168)),
    ("Coinveyor!", "FTY LLC.", "JP", (216, 150, 214)),
    ("Voxel Blast: Cube Puzzle ...", "WODH", "PK", (74, 143, 231)),
    ("Dog Maze Puzzle", "ColorBean", "SG", (150, 205, 120)),
    ("Little Red - Hide & Escape", "ColorBean", "SG", (242, 168, 176)),
    ("Cutie Link: Tile Connect", "ONE MORE GAME LAB", "VN", (250, 214, 90)),
    ("Xmasudoku - Find Santa", "Casual Candy Match", "HK", (170, 80, 200)),
    ("Car Flow: Color Loop", "EASY PLAY GAME TECHN...", "HK", (126, 205, 236)),
    ("Yarn Art : Knit & Match P...", "WEMIX Global", "VN", (196, 170, 232)),
    ("Hooks Jam", "jennywhiteshrimp", "CN", (196, 150, 236)),
    ("Arrow Flow Path Solver", "Hong Kong Yuchi Technol...", "HK", (40, 42, 60)),
    ("Sizzle Master: BBQ Jam S...", "LeoGame Co., Ltd", "VN", (240, 150, 70)),
]

PER_ROW = 5
SCALE = 2
CARD_W, CARD_H = 130 * SCALE, 176 * SCALE
GAP, PAD = 8 * SCALE, 10 * SCALE
ICON = 116 * SCALE


def font(size, bold=False):
    names = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for n in names + ["DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main(out="test_cards2.png"):
    f_title = font(11 * SCALE)
    f_pub = font(10 * SCALE)
    f_badge = font(8 * SCALE, bold=True)

    rows = (len(CARDS) + PER_ROW - 1) // PER_ROW
    w = PAD * 2 + PER_ROW * CARD_W + (PER_ROW - 1) * GAP
    h = PAD * 2 + rows * CARD_H + (rows - 1) * GAP
    img = Image.new("RGB", (w, h), (247, 248, 250))
    d = ImageDraw.Draw(img)

    for i, (title, pub, cc, colour) in enumerate(CARDS):
        r, c = divmod(i, PER_ROW)
        x = PAD + c * (CARD_W + GAP)
        y = PAD + r * (CARD_H + GAP)
        d.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], 10 * SCALE,
                            fill="white", outline=(228, 230, 234))

        ix, iy = x + 6 * SCALE, y + 6 * SCALE
        d.rounded_rectangle([ix, iy, ix + ICON, iy + ICON], 16 * SCALE, fill=colour)

        # country badge on the icon's bottom-left - an extra text line
        bw, bh = 20 * SCALE, 13 * SCALE
        bx, by = ix + 4 * SCALE, iy + ICON - bh - 4 * SCALE
        d.rounded_rectangle([bx, by, bx + bw, by + bh], 4 * SCALE,
                            fill="white", outline=(200, 202, 206))
        d.text((bx + 4 * SCALE, by + 1 * SCALE), cc, font=f_badge, fill=(60, 62, 70))

        ty = iy + ICON + 7 * SCALE
        d.text((x + 6 * SCALE, ty), title, font=f_title, fill=(28, 30, 34))
        # store badge glyph at the end of the title line
        d.polygon([(x + CARD_W - 14 * SCALE, ty + 1 * SCALE),
                   (x + CARD_W - 14 * SCALE, ty + 11 * SCALE),
                   (x + CARD_W - 6 * SCALE, ty + 6 * SCALE)], fill=(40, 180, 100))

        py = ty + 15 * SCALE
        d.text((x + 6 * SCALE, py), "★", font=f_pub, fill=(245, 190, 60))
        d.text((x + 15 * SCALE, py), pub, font=f_pub, fill=(235, 145, 40))

    img.save(out)
    print("wrote %s (%dx%d), %d cards in %d rows" % (out, img.width, img.height,
                                                     len(CARDS), rows))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_cards2.png")
