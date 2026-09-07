"""Render the old and new direction cards over the same frame, side by side.

Cheaper than re-rendering the PoC video when only the card design changed.
    .venv/Scripts/python.exe poc_ar_arrow/compare_direction_cards.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from poc_ar_arrow.render_poc import _font, render_instruction_card  # noqa: E402

OUT = Path(__file__).resolve().parent / 'out' / 'direction_card_compare.png'
PANE_W, PANE_H = 900, 506


def old_card(frame, english):
    """The previous implementation, kept here only for the comparison."""
    h, w = frame.shape[:2]
    im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    card_w = max(285, min(350, int(w * 0.36)))
    card_h = max(82, min(104, int(h * 0.20)))
    radius = int(card_h * 0.42)
    x1 = (w - card_w) // 2
    y1 = max(56, int(h * 0.13))
    x2, y2 = x1 + card_w, y1 + card_h

    shadow = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x1 + 5, y1 + 7, x2 + 5, y2 + 7),
                                             radius=radius, fill=(0, 0, 0, 100))
    im = Image.alpha_composite(im.convert('RGBA'),
                               shadow.filter(ImageFilter.GaussianBlur(11)))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius,
                           fill=(252, 252, 252, 255),
                           outline=(232, 232, 234, 255), width=2)

    cx = x1 + int(card_w * 0.24)
    cy = (y1 + y2) // 2
    ink = (30, 30, 34, 255)
    line_w = max(3, int(card_h * 0.045))
    kind = {'TURN RIGHT': 'right', 'TURN LEFT': 'left'}.get(english, 'straight')

    if english == 'YOU HAVE ARRIVED':
        r = max(15, int(card_h * 0.22))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=line_w)
        draw.line((cx - r // 2, cy, cx - r // 8, cy + r // 2), fill=ink, width=line_w)
        draw.line((cx - r // 8, cy + r // 2, cx + r * 0.58, cy - r // 2), fill=ink, width=line_w)
    elif kind == 'straight':
        top = cy - int(card_h * 0.25)
        draw.line((cx, cy + int(card_h * 0.28), cx, top), fill=ink, width=line_w)
        wing = int(card_h * 0.13)
        draw.line((cx, top, cx - wing, top + wing), fill=ink, width=line_w)
        draw.line((cx, top, cx + wing, top + wing), fill=ink, width=line_w)
    else:
        side = -1 if kind == 'left' else 1
        x_end = cx + side * int(card_w * 0.12)
        y_top = cy - int(card_h * 0.18)
        draw.line((cx, cy + int(card_h * 0.28), cx, y_top), fill=ink, width=line_w)
        draw.line((cx, y_top, x_end, y_top), fill=ink, width=line_w)
        wx, wy = int(card_h * 0.16), int(card_h * 0.13)
        draw.line((x_end, y_top, x_end - side * wx, y_top - wy), fill=ink, width=line_w)
        draw.line((x_end, y_top, x_end - side * wx, y_top + wy), fill=ink, width=line_w)

    label = 'YOU HAVE ARRIVED' if english == 'YOU HAVE ARRIVED' else english.title()
    draw.text((x1 + int(card_w * 0.43), cy + 1), label, anchor='lm',
              font=_font(max(18, int(card_h * 0.27)), False), fill=ink)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def corridor(seed):
    """Stand-in corridor frame: a plain gradient with some structure, so the
    card is judged against mid-tone content rather than flat colour."""
    rng = np.random.default_rng(seed)
    img = np.zeros((PANE_H, PANE_W, 3), np.uint8)
    for y in range(PANE_H):
        t = y / PANE_H
        img[y, :] = (int(96 + 74 * t), int(92 + 70 * t), int(86 + 64 * t))
    cv2.line(img, (0, 300), (PANE_W // 2, 190), (150, 148, 143), 2)
    cv2.line(img, (PANE_W, 300), (PANE_W // 2, 190), (150, 148, 143), 2)
    cv2.line(img, (0, PANE_H), (PANE_W // 2, 250), (128, 126, 122), 2)
    cv2.line(img, (PANE_W, PANE_H), (PANE_W // 2, 250), (128, 126, 122), 2)
    img = cv2.add(img, rng.integers(0, 9, img.shape, dtype=np.uint8))
    return img


STATES = ['GO STRAIGHT', 'TURN RIGHT', 'TURN LEFT', 'YOU HAVE ARRIVED']
rows = []
for i, state in enumerate(STATES):
    rows.append(np.hstack([old_card(corridor(i), state),
                           render_instruction_card(corridor(i), '', state)]))
sheet = np.vstack(rows)

# Header strip so the two columns are unambiguous.
head = np.full((70, sheet.shape[1], 3), 24, np.uint8)
im = Image.fromarray(cv2.cvtColor(head, cv2.COLOR_BGR2RGB))
d = ImageDraw.Draw(im)
f = _font(30, True)
d.text((PANE_W // 2, 35), 'BEFORE', anchor='mm', font=f, fill=(150, 150, 155))
d.text((PANE_W + PANE_W // 2, 35), 'AFTER', anchor='mm', font=f, fill=(255, 255, 255))
head = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

OUT.parent.mkdir(parents=True, exist_ok=True)
# Written at the pane's native resolution. Downscaling the sheet made the card
# look soft here even though the card itself renders sharp at 1:1.
cv2.imwrite(str(OUT), np.vstack([head, sheet]))
print(OUT, f'{sheet.shape[1]}x{sheet.shape[0] + head.shape[0]}')
