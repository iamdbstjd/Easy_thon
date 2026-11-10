"""README용 픽셀 배너. 작은 캔버스에 칸 단위로 그린 뒤 최근접 보간으로 4배 키운다.

사용법: python3 make_banner.py <Galmuri 글꼴 폴더> assets/banner.png
글꼴: Galmuri (SIL Open Font License 1.1), `npm pack galmuri` 후 package/dist
"""
import sys
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = sys.argv[1]  # Galmuri 글꼴 파일이 있는 폴더 (npm 패키지 galmuri의 dist)
OUT = sys.argv[2]

W, H, SCALE = 360, 96, 4

PAPER = (244, 239, 230)
INK = (27, 27, 31)
LINE = (214, 205, 189)
RED = (180, 35, 24)
AMBER = (138, 90, 0)
GREEN = (46, 107, 63)
GRAY = (92, 98, 110)
COLORS = {
    "k": INK,
    "r": (176, 64, 48),     # 지붕
    "R": (140, 45, 34),     # 지붕 그림자
    "w": (252, 250, 244),   # 벽
    "y": (242, 193, 78),    # 불 켜진 창
    "d": (110, 70, 45),     # 문
    "b": (200, 225, 240),   # 렌즈
    "l": (255, 255, 255),   # 렌즈 반사
    "h": (70, 50, 40),      # 손잡이
}

HOUSE = [
    ".........kk.........",
    "........krrk........",
    ".......krrrRk.......",
    "......krrrrRRk......",
    ".....krrrrrrRRk.....",
    "....krrrrrrrrRRk....",
    "...krrrrrrrrrrRRk...",
    "..krrrrrrrrrrrrRRk..",
    ".krrrrrrrrrrrrrrRRk.",
    "kkkkkkkkkkkkkkkkkkkk",
    ".kwwwwwwwwwwwwwwwwk.",
    ".kwkkkkwwwwwwkkkkwk.",
    ".kwkyykwwwwwwkyykwk.",
    ".kwkyykwwkkwwkyykwk.",
    ".kwkkkkwkddkwkkkkwk.",
    ".kwwwwwwkddkwwwwwwk.",
    ".kwwwwwwkddkwwwwwwk.",
    ".kkkkkkkkkkkkkkkkkk.",
]

LENS = [
    "..kkkk......",
    ".kbbbbk.....",
    "kbllbbbk....",
    "kblbbbbk....",
    "kbbbbbbk....",
    "kbbbbbbk....",
    ".kbbbbk.....",
    "..kkkkhh....",
    "......hhh...",
    ".......hhh..",
    "........hhh.",
    ".........hh.",
]


def sprite(img, rows, x0, y0, px):
    d = ImageDraw.Draw(img)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            d.rectangle(
                [x0 + x * px, y0 + y * px, x0 + (x + 1) * px - 1, y0 + (y + 1) * px - 1],
                fill=COLORS[ch],
            )


def text(img, xy, s, font_file, size, color, mult=1):
    """안티에일리어싱 없이 글자를 찍고, mult배로 키워서 붙인다."""
    font = ImageFont.truetype(f"{FONT_DIR}/{font_file}", size)
    l, t, r, b = font.getbbox(s)
    mask = Image.new("1", (r, b), 0)
    md = ImageDraw.Draw(mask)
    md.fontmode = "1"
    md.text((0, 0), s, font=font, fill=1)
    mask = mask.resize((r * mult, b * mult), Image.NEAREST)
    img.paste(Image.new("RGB", mask.size, color), xy, mask)
    return xy[0] + r * mult


img = Image.new("RGB", (W, H), PAPER)
d = ImageDraw.Draw(img)

# 서류 같은 테두리: 바깥 먹선 + 안쪽 연한 선
d.rectangle([0, 0, W - 1, H - 1], outline=INK)
d.rectangle([3, 3, W - 4, H - 4], outline=LINE)

# 집과 돋보기
sprite(img, HOUSE, 16, 18, 3)
sprite(img, LENS, 50, 44, 3)

# 글자
TX = 98
text(img, (TX, 14), "자취방 보증금 지킴이", "Galmuri11-Bold.ttf", 12, INK, mult=2)
d.line([TX, 47, W - 18, 47], fill=LINE)
text(img, (TX, 54), "등기부·계약서로 보는 보증금 위험 신호", "Galmuri11.ttf", 12, GRAY)
x = text(img, (TX, 72), "위험", "Galmuri11-Bold.ttf", 12, RED)
x = text(img, (x + 4, 72), "·", "Galmuri11.ttf", 12, GRAY)
x = text(img, (x + 4, 72), "주의", "Galmuri11-Bold.ttf", 12, AMBER)
x = text(img, (x + 4, 72), "·", "Galmuri11.ttf", 12, GRAY)
x = text(img, (x + 4, 72), "해당 없음", "Galmuri11-Bold.ttf", 12, GREEN)

img = img.resize((W * SCALE, H * SCALE), Image.NEAREST)
img.save(OUT, optimize=True)
print(OUT, img.size)
