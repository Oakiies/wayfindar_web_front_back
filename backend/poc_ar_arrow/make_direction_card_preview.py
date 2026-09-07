from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


OUT = Path(__file__).resolve().parent / 'out' / 'direction_cards_preview_all.png'
W, H = 1500, 560


def font(size, bold=False):
    path = r'C:\Windows\Fonts\segoeuib.ttf' if bold else r'C:\Windows\Fonts\segoeui.ttf'
    return ImageFont.truetype(path, size)


def draw_arrow(draw, kind, cx, cy, color=(30, 30, 34, 255)):
    """Thin, rounded navigation glyphs with a consistent visual weight."""
    width = 5
    if kind == 'straight':
        draw.line((cx, cy + 36, cx, cy - 27), fill=color, width=width)
        draw.line((cx, cy - 27, cx - 16, cy - 10), fill=color, width=width)
        draw.line((cx, cy - 27, cx + 16, cy - 10), fill=color, width=width)
    else:
        side = -1 if kind == 'left' else 1
        x_end = cx + side * 43
        y_top = cy - 25
        draw.line((cx, cy + 36, cx, y_top), fill=color, width=width)
        draw.line((cx, y_top, x_end, y_top), fill=color, width=width)
        # The arrowhead follows the final horizontal segment: right points
        # right, left points left (instead of incorrectly pointing upward).
        draw.line((x_end, y_top, x_end - side * 17, y_top - 14), fill=color, width=width)
        draw.line((x_end, y_top, x_end - side * 17, y_top + 14), fill=color, width=width)


def draw_card(canvas, box, kind, label):
    x1, y1, x2, y2 = box
    radius = 48

    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((x1 + 7, y1 + 12, x2 + 7, y2 + 12),
                                  radius=radius, fill=(0, 0, 0, 95))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=radius, fill=(252, 252, 252, 255),
                           outline=(232, 232, 234, 255), width=2)

    cx = x1 + 112
    cy = (y1 + y2) // 2
    draw_arrow(draw, kind, cx, cy)
    draw.text((x1 + 205, cy + 1), label, anchor='lm', font=font(36, bold=False),
              fill=(25, 25, 30, 255))


canvas = Image.new('RGBA', (W, H), (30, 39, 53, 255))
draw = ImageDraw.Draw(canvas)
for y in range(H):
    shade = int(30 + 17 * y / H)
    draw.line((0, y, W, y), fill=(shade, shade + 8, shade + 20, 255))

# Three variants in one image; no distance or extra status text is included.
card_w, card_h = 410, 180
gap = 35
left = (W - (card_w * 3 + gap * 2)) // 2
y = 190
draw_card(canvas, (left, y, left + card_w, y + card_h), 'straight', 'Go Straight')
draw_card(canvas, (left + card_w + gap, y, left + card_w * 2 + gap,
                   y + card_h), 'right', 'Turn Right')
draw_card(canvas, (left + card_w * 2 + gap * 2, y, W - left, y + card_h),
          'left', 'Turn Left')

title_font = font(24, bold=True)
draw = ImageDraw.Draw(canvas)
draw.text((W // 2, 76), 'Direction card concepts', anchor='mm',
          font=title_font, fill=(244, 246, 250, 230))

OUT.parent.mkdir(parents=True, exist_ok=True)
canvas.convert('RGB').save(OUT, quality=95)
print(OUT)
