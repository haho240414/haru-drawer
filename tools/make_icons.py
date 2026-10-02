"""앱 아이콘·시작 화면 그림 만들기 (Capacitor 기본 그림 대신). python tools/make_icons.py

모양: 남보라→주황 그라데이션 위에 흰 서랍 두 칸 (app/icon.svg 와 같은 디자인).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android/app/src/main/res"
DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
C1, C2 = (99, 102, 241), (245, 158, 11)


def gradient(size: int) -> Image.Image:
    im = Image.new("RGB", (size, size))
    px = im.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(C1, C2))
    return im


def drawers(d: ImageDraw.ImageDraw, box: tuple[float, float, float, float]):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    bh, gap, r = h * 0.40, h * 0.20, h * 0.13
    for i, (alpha, handle) in enumerate(((242, C1), (200, (217, 119, 6)))):
        top = y0 + i * (bh + gap)
        d.rounded_rectangle([x0, top, x1, top + bh], radius=r, fill=(255, 255, 255, alpha))
        hw, hh = w * 0.28, bh * 0.22
        cx, cy = (x0 + x1) / 2, top + bh * 0.42
        d.rounded_rectangle([cx - hw / 2, cy - hh / 2, cx + hw / 2, cy + hh / 2], radius=hh / 2, fill=handle + (255,))


def icon(size: int, round_: bool) -> Image.Image:
    s = size * 4
    base = gradient(s).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    if round_:
        md.ellipse([0, 0, s - 1, s - 1], fill=255)
    else:
        md.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=255)
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    drawers(ImageDraw.Draw(layer), (s * 0.24, s * 0.26, s * 0.76, s * 0.74))
    base.alpha_composite(layer)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def foreground(size: int) -> Image.Image:
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # 적응형 아이콘 안전 영역(가운데 66/108) 안에
    m = s * (1 - 0.46) / 2
    drawers(ImageDraw.Draw(im), (m, m * 1.04, s - m, s - m * 0.96))
    return im.resize((size, size), Image.LANCZOS)


def main():
    for name, k in DENS.items():
        d = RES / f"mipmap-{name}"
        d.mkdir(exist_ok=True)
        icon(round(48 * k), False).save(d / "ic_launcher.png")
        icon(round(48 * k), True).save(d / "ic_launcher_round.png")
        foreground(round(108 * k)).save(d / "ic_launcher_foreground.png")
        gradient(round(108 * k)).save(d / "ic_launcher_background.png")
    for xml in (RES / "mipmap-anydpi-v26").glob("*.xml"):
        xml.write_text(xml.read_text().replace("@color/ic_launcher_background", "@mipmap/ic_launcher_background"))
    # 시작 화면: 어두운 배경 + 가운데 아이콘 (기존 그림 크기 그대로)
    for p in RES.glob("drawable*/splash.png"):
        w, h = Image.open(p).size
        im = Image.new("RGB", (w, h), (17, 18, 21))
        ic = icon(int(min(w, h) * 0.28), False)
        im.paste(ic, ((w - ic.width) // 2, (h - ic.height) // 2), ic)
        im.save(p)
    print("아이콘·시작 화면 완료")


if __name__ == "__main__":
    main()
