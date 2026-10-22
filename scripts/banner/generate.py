#!/usr/bin/env python3
"""Profil banner'ını (assets/banner-dark.svg, assets/banner-light.svg) üretir.

Fotoğraf 1 bitlik noktalara çevrilir (Floyd-Steinberg), noktaların bir kısmı
sırayla </>, { } ve >_ şekillerine akıp portreye geri döner. Sağda terminal
tarzı bilgi paneli, altta Gece Şehri silüeti vardır.

Yerelde bir kez çalıştırılır (her gün değil):
    pip install -r scripts/banner/requirements.txt
    python scripts/banner/generate.py
"""

from __future__ import annotations

import html
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/source/portrait.png"
OUT = ROOT / "assets"

W, H = 1200, 640
MONO = "ui-monospace,SFMono-Regular,Consolas,'Cascadia Mono',monospace"

# Portre ızgarası ve sol paneldeki yeri
GRID_W, GRID_H = 302, 340
GRID_X, GRID_Y = 91, 166

TRAVELLERS = 1400
MAX_DOTS = 32000
SEED = 20261023

# Döngü: portre → </> → { } → >_ → portre (saniye)
INTRO = 1.6
TIMES = [0, 3.4, 4.7, 6.7, 8.0, 10.0, 11.3, 13.3, 14.6, 15.2]
LOOP = TIMES[-1]

# Gece Şehri paleti (portfolio/app/globals.css içindeki --c-* değerleri)
THEMES = {
    "dark": {
        "bg": "#0b0f15", "surface": "#131a25", "elevated": "#1b2432",
        "line": "#293444", "ink": "#eceff4", "muted": "#9ca7b8",
        "subtle": "#6b788b", "accent": "#f5c77e", "dots": "#f5c77e",
        "keyword": "#c792ea", "string": "#c3e88d", "prop": "#82aaff",
        "city": "#1f2938",
    },
    "light": {
        "bg": "#dee4ec", "surface": "#ecf0f5", "elevated": "#e5eaf1",
        "line": "#c4cdd9", "ink": "#161e2e", "muted": "#485468",
        "subtle": "#68758a", "accent": "#a64d0a", "dots": "#1d2638",
        "keyword": "#763ad0", "string": "#1e6e3c", "prop": "#2450be",
        "city": "#cfd7e2",
    },
}

# Sağ panel satırları: (grup, anahtar, değer). Grup rengi sözdizimi renklerinden gelir.
ROWS = [
    ("user", "name", "Miraç Deprem"),
    ("user", "role", "Full-stack Software Developer"),
    ("user", "location", "Istanbul, Türkiye"),
    ("user", "education", "BSc Computer Engineering · 2026"),
    ("user", "status", "Open to full-stack roles"),
    ("work", "internships", "Çetin Group · Atia Software"),
    ("stack", "languages", "C# · Go · TypeScript · Python · C++"),
    ("stack", "web", "React · Next.js · ASP.NET Core · Node.js"),
    ("stack", "apps", "Flutter · Qt · JavaFX"),
    ("stack", "data", "PostgreSQL · MySQL · Redis"),
    ("stack", "ai", "LLM APIs · RAG · ONNX"),
    ("pub", "paper", "Cipher · IJANA 2026"),
    ("link", "site", "miracdeprem.com"),
    ("link", "linkedin", "/in/miracdeprem"),
    ("link", "github", "MrcDprm"),
]
GROUP_COLOR = {"user": "prop", "work": "accent", "stack": "keyword", "pub": "accent", "link": "string"}


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def text_w(text: str, size: float) -> float:
    # Monospace yazıda karakter genişliği ~0.6 em; textLength ile sabitlenir
    return len(text) * size * 0.6


# ---------------------------------------------------------------- noktalar


def dither(gray: np.ndarray) -> np.ndarray:
    """Yılan sırasıyla (serpentine) Floyd-Steinberg; True = yanan nokta."""
    work = gray.astype(np.float32) / 255.0
    out = np.zeros(work.shape, dtype=bool)
    h, w = work.shape
    for y in range(h):
        step = 1 if y % 2 == 0 else -1
        for x in range(w) if step == 1 else range(w - 1, -1, -1):
            old = work[y, x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = new > 0
            err = old - new
            if 0 <= x + step < w:
                work[y, x + step] += err * 7 / 16
            if y + 1 < h:
                if 0 <= x - step < w:
                    work[y + 1, x - step] += err * 3 / 16
                work[y + 1, x] += err * 5 / 16
                if 0 <= x + step < w:
                    work[y + 1, x + step] += err * 1 / 16
    return out


def portrait_points(theme: str, rng: np.random.Generator) -> np.ndarray:
    img = Image.open(SOURCE).convert("RGBA").resize((GRID_W, GRID_H), Image.Resampling.LANCZOS)
    alpha = np.asarray(img.getchannel("A"), dtype=np.float32) / 255.0
    subject = alpha > 0.1

    if theme == "dark":
        # Koyu temada açık bölgeler yanar (ışık noktaları)
        lum = np.asarray(ImageOps.grayscale(img.convert("RGB")), dtype=np.float32)
        gray = Image.fromarray(np.uint8(np.clip(lum * alpha, 0, 255)), "L")
        gray = ImageOps.equalize(gray, mask=Image.fromarray(np.uint8(subject * 255), "L"))
        # Beyaz tişört dolu bir blok gibi durmasın: en parlak tonlar biraz kısılır, benekli görünür
        gray = gray.point(lambda v: round(v * 0.86))
    else:
        # Açık temada koyu bölgeler mürekkep gibi basılır
        white = Image.new("RGBA", img.size, "white")
        white.alpha_composite(img)
        gray = ImageOps.autocontrast(ImageOps.grayscale(white.convert("RGB")), cutoff=1)

    gray = ImageEnhance.Contrast(gray).enhance(1.3)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=170, threshold=1))
    bits = dither(np.asarray(gray))
    active = (bits if theme == "dark" else ~bits) & subject

    ys, xs = np.where(active)
    pts = np.column_stack((GRID_X + xs, GRID_Y + ys)).astype(np.float32)
    if len(pts) > MAX_DOTS:
        pts = pts[rng.choice(len(pts), MAX_DOTS, replace=False)]
    return pts


def glyph_mask(text: str) -> Image.Image:
    """Kalın monospace yazı tipiyle şekli çizip 280 px'lik kareye ortalar."""
    font = None
    for name in ("consolab.ttf", "DejaVuSansMono-Bold.ttf", "Menlo.ttc"):
        try:
            font = ImageFont.truetype(name, 320)
            break
        except OSError:
            continue
    if font is None:
        raise SystemExit("Kalın bir monospace yazı tipi bulunamadı (Consolas Bold / DejaVu Sans Mono Bold).")

    canvas = Image.new("L", (900, 600), 0)
    ImageDraw.Draw(canvas).text((40, 40), text, font=font, fill=255)
    canvas = canvas.filter(ImageFilter.MaxFilter(11))  # çizgileri kalınlaştır, noktalar dolu görünsün
    glyph = canvas.crop(canvas.getbbox())
    scale = 280 / max(glyph.size)
    glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))))
    box = Image.new("L", (280, 280), 0)
    box.paste(glyph, ((280 - glyph.width) // 2, (280 - glyph.height) // 2))
    return box


def shape_points(text: str, rng: np.random.Generator, count: int) -> np.ndarray:
    ys, xs = np.where(np.asarray(glyph_mask(text)) > 127)
    pick = rng.choice(len(xs), count, replace=len(xs) < count)
    # 280 px'lik kare, portre ızgarasının ortasına oturur
    ox = GRID_X + (GRID_W - 280) / 2
    oy = GRID_Y + (GRID_H - 280) / 2
    return np.column_stack((ox + xs[pick], oy + ys[pick])).astype(np.float32)


def transport(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Her noktayı toplam yolu en kısa olacak hedefe eşler (Hungarian algoritması)."""
    rows, cols = linear_sum_assignment(cdist(src, dst, "sqeuclidean"))
    ordered = np.empty_like(dst)
    ordered[rows] = dst[cols]
    return ordered


def runs_path(pts: np.ndarray) -> str:
    """Yan yana tek piksellik noktaları yatay çizgi parçalarına birleştirir (daha küçük SVG)."""
    cells = sorted({(int(x), int(y)) for x, y in np.rint(pts)}, key=lambda p: (p[1], p[0]))
    out: list[str] = []
    i = 0
    while i < len(cells):
        x0, y = cells[i]
        x1 = x0
        i += 1
        while i < len(cells) and cells[i][1] == y and cells[i][0] == x1 + 1:
            x1 = cells[i][0]
            i += 1
        out.append(f"M{x0} {y}.5h{x1 - x0 + 1}")
    return "".join(out)


# ---------------------------------------------------------------- silüet


def skyline(t: dict, rng: np.random.Generator) -> str:
    """Pencerenin altına ince bir İstanbul silüeti: binalar, cami, Galata Kulesi, yanan pencereler."""
    base, left, right = 628, 14, 1186
    parts = [f'<g fill="{t["city"]}">']
    windows: list[str] = []
    x = left
    while x < right:
        w = int(rng.integers(14, 34))
        if (x + w > 272 and x < 308) or (x + w > 840 and x < 940):  # anıtlar için boşluk
            x += 8
            continue
        h = int(rng.integers(10, 34))
        parts.append(f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}"/>')
        for wy in range(base - h + 5, base - 4, 7):
            for wx in range(x + 3, x + w - 3, 6):
                if rng.random() < 0.13:
                    blink = ""
                    if rng.random() < 0.3:
                        d = num(5 + rng.random() * 7)
                        blink = (f'<animate attributeName="opacity" values="1;1;.15;1" keyTimes="0;.6;.75;1" '
                                 f'dur="{d}s" begin="{num(rng.random() * 6)}s" repeatCount="indefinite"/>')
                    windows.append(f'<rect x="{wx}" y="{wy}" width="2" height="3" '
                                   f'opacity="{num(0.45 + rng.random() * 0.5)}">{blink}</rect>')
        x += w + int(rng.integers(0, 3))

    # Galata Kulesi
    cx = 290
    parts.append(f'<rect x="{cx - 6}" y="{base - 52}" width="12" height="52"/>'
                 f'<rect x="{cx - 8}" y="{base - 58}" width="16" height="6"/>'
                 f'<polygon points="{cx - 7},{base - 58} {cx + 7},{base - 58} {cx},{base - 78}"/>')
    windows.append(f'<rect x="{cx - 5}" y="{base - 57}" width="2" height="3"/>'
                   f'<rect x="{cx - 1}" y="{base - 57}" width="2" height="3"/>'
                   f'<rect x="{cx + 3}" y="{base - 57}" width="2" height="3"/>')

    # Cami: kubbe, yarım kubbeler, dört minare
    cx, s = 890, 0.3
    parts.append(f'<rect x="{num(cx - 95 * s)}" y="{num(base - 40 * s)}" width="{num(190 * s)}" height="{num(40 * s)}"/>'
                 f'<path d="M{num(cx - 70 * s)} {num(base - 40 * s)}A{num(70 * s)} {num(62 * s)} 0 0 1 '
                 f'{num(cx + 70 * s)} {num(base - 40 * s)}Z"/>'
                 f'<path d="M{num(cx - 110 * s)} {num(base - 20 * s)}A{num(34 * s)} {num(30 * s)} 0 0 1 '
                 f'{num(cx - 42 * s)} {num(base - 20 * s)}Z"/>'
                 f'<path d="M{num(cx + 42 * s)} {num(base - 20 * s)}A{num(34 * s)} {num(30 * s)} 0 0 1 '
                 f'{num(cx + 110 * s)} {num(base - 20 * s)}Z"/>')
    for mx in (cx - 125 * s, cx - 100 * s, cx + 100 * s, cx + 125 * s):
        parts.append(f'<rect x="{num(mx - 1.2)}" y="{num(base - 170 * s)}" width="2.4" height="{num(170 * s)}"/>'
                     f'<polygon points="{num(mx - 1.2)},{num(base - 170 * s)} {num(mx + 1.2)},'
                     f'{num(base - 170 * s)} {num(mx)},{num(base - 196 * s)}"/>')
    parts.append("</g>")
    parts.append(f'<g fill="{t["accent"]}">{"".join(windows)}</g>')
    return "".join(parts)


# ---------------------------------------------------------------- SVG


def render(theme: str, portrait: np.ndarray, shapes: list[np.ndarray], rng: np.random.Generator) -> str:
    t = THEMES[theme]
    key_times =";".join(f"{v / LOOP:.4f}".rstrip("0").rstrip(".") for v in TIMES)

    n = min(TRAVELLERS, len(portrait))
    src = portrait[rng.choice(len(portrait), n, replace=False)]
    code = transport(src, shapes[0][:n])
    brace = transport(code, shapes[1][:n])
    prompt = transport(brace, shapes[2][:n])
    frames = [src, src, code, code, brace, brace, prompt, prompt, src, src]

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-labelledby="t d">',
        '<title id="t">Miraç Deprem · Full-stack Software Developer</title>',
        '<desc id="d">Animated terminal profile: a dithered portrait whose dots flow into code symbols, '
        'a system info panel and an Istanbul skyline.</desc>',
        "<defs>",
        f'<clipPath id="win"><rect x="12" y="12" width="{W - 24}" height="{H - 24}" rx="14"/></clipPath>',
        '<clipPath id="vis"><rect x="44" y="116" width="396" height="426" rx="4"/></clipPath>',
        "</defs>",
        f'<rect width="{W}" height="{H}" rx="18" fill="{t["bg"]}"/>',
        f'<rect x="12" y="12" width="{W - 24}" height="{H - 24}" rx="14" fill="{t["surface"]}" stroke="{t["line"]}"/>',
        f'<path d="M12 60H{W - 12}" stroke="{t["line"]}"/>',
        # Pencere düğmeleri: amber ışık + iki sönük
        f'<circle cx="36" cy="36" r="6" fill="{t["accent"]}"/>'
        f'<circle cx="56" cy="36" r="6" fill="{t["line"]}"/><circle cx="76" cy="36" r="6" fill="{t["line"]}"/>',
        f'<text x="{W / 2}" y="41" text-anchor="middle" fill="{t["muted"]}" font-family="{MONO}" '
        'font-size="13" letter-spacing=".4">mirac@istanbul: ~ $ ./whoami --live</text>',
        # Sol panel
        f'<rect x="32" y="78" width="420" height="476" rx="6" fill="{t["elevated"]}" stroke="{t["line"]}"/>',
        f'<path d="M32 112H452" stroke="{t["line"]}"/>',
        f'<text x="46" y="100" fill="{t["accent"]}" font-family="{MONO}" font-size="13" '
        'font-weight="700" letter-spacing="1.2">VISUAL.MAP</text>',
        f'<text x="438" y="100" text-anchor="end" fill="{t["subtle"]}" font-family="{MONO}" '
        f'font-size="11">{GRID_W}×{GRID_H} / 1-BIT</text>',
        f'<path d="M48 128h12M48 128v12M436 128h-12M436 128v12M48 528h12M48 528v-12M436 528h-12M436 528v-12" '
        f'fill="none" stroke="{t["accent"]}" opacity=".5"/>',
        '<g clip-path="url(#vis)" shape-rendering="crispEdges">',
    ]

    # Portre 60 gruba bölünür: girişte gruplar karışık sırayla belirir (fotoğraf çiziliyormuş gibi),
    # döngüde her grup hafifçe kayarak söner, şekiller bitince geri gelir.
    groups = 60
    ids = rng.integers(0, groups, size=len(portrait))
    starts = np.empty(groups)
    starts[rng.permutation(groups)] = np.linspace(0.05, 1.1, groups)
    center = np.array([GRID_X + GRID_W / 2, GRID_Y + GRID_H / 2])
    fade = "1;1;0;0;0;0;0;0;1;1"
    for g in range(groups):
        pts = portrait[ids == g]
        if not len(pts):
            continue
        dx, dy = (center - pts.mean(axis=0)) * 0.2 + rng.normal(0, 4, 2)
        moved = f"{num(dx)} {num(dy)}"
        intro_end = starts[g] + 0.5
        p.append(
            f'<path d="{runs_path(pts)}" stroke="{t["dots"]}" stroke-width="1">'
            f'<animate attributeName="opacity" dur="{num(intro_end)}s" fill="freeze" '
            f'keyTimes="0;{num(starts[g] / intro_end)};1" values="0;0;1"/>'
            f'<animate attributeName="opacity" begin="{INTRO}s" dur="{LOOP}s" repeatCount="indefinite" '
            f'keyTimes="{key_times}" values="{fade}"/>'
            f'<animateTransform attributeName="transform" type="translate" begin="{INTRO}s" dur="{LOOP}s" '
            f'repeatCount="indefinite" keyTimes="{key_times}" '
            f'values="0 0;0 0;{moved};{moved};0 0;0 0;0 0;0 0;0 0;0 0"/></path>'
        )

    # Gezgin noktalar: portre sönerken görünür olup şekilden şekle akar.
    # Görünürlük hepsinde aynı olduğu için tek grupta animasyonlanır (dosya küçülür).
    p.append(
        f'<g fill="{t["dots"]}" opacity="0"><animate attributeName="opacity" begin="{INTRO}s" dur="{LOOP}s" '
        f'repeatCount="indefinite" keyTimes="{key_times}" values="0;0;1;1;1;1;1;1;0;0"/>'
    )
    for i in range(n):
        values = ";".join(f"{num(f[i, 0])} {num(f[i, 1])}" for f in frames)
        p.append(
            '<path d="M-.9-.9h1.8v1.8h-1.8z">'
            f'<animateTransform attributeName="transform" type="translate" begin="{INTRO}s" dur="{LOOP}s" '
            f'repeatCount="indefinite" keyTimes="{key_times}" values="{values}"/></path>'
        )
    p.append("</g></g>")
    p.append(f'<text x="48" y="546" fill="{t["subtle"]}" font-family="{MONO}" font-size="10">'
             f'PTS {len(portrait):05d} · FLOYD-STEINBERG</text>')

    # Sağ panel
    p += [
        f'<rect x="472" y="78" width="696" height="476" rx="6" fill="{t["elevated"]}" stroke="{t["line"]}"/>',
        f'<path d="M472 112H1168" stroke="{t["line"]}"/>',
        f'<text x="488" y="100" fill="{t["accent"]}" font-family="{MONO}" font-size="13" '
        'font-weight="700" letter-spacing="1.2">SYSTEM.INFO</text>',
        f'<circle cx="958" cy="95" r="4" fill="{t["accent"]}">'
        '<animate attributeName="opacity" values="1;.25;1" dur="1.8s" repeatCount="indefinite"/></circle>',
        f'<text x="969" y="100" fill="{t["accent"]}" font-family="{MONO}" font-size="12" font-weight="700">LIVE</text>',
        f'<rect x="1018" y="84" width="134" height="22" rx="11" fill="{t["accent"]}" fill-opacity=".14" '
        f'stroke="{t["accent"]}" stroke-opacity=".6"/>',
        f'<text x="1085" y="100" text-anchor="middle" fill="{t["accent"]}" font-family="{MONO}" '
        'font-size="13" font-weight="700">@MrcDprm</text>',
    ]

    size, right, y = 14, 1150.0, 142.0
    for group, key, value in ROWS:
        label = f"{group}.{key}"
        lw, vw = text_w(label, size), text_w(value, size)
        x0, x1 = 490 + lw + 12, right - vw - 12
        dots = "".join(f"M{num(x)} {num(y - 4)}h1" for x in np.arange(x0, x1, 5.0))
        p += [
            f'<text x="490" y="{num(y)}" font-family="{MONO}" font-size="{size}" '
            f'textLength="{num(lw)}" lengthAdjust="spacingAndGlyphs">'
            f'<tspan fill="{t[GROUP_COLOR[group]]}">{group}</tspan>'
            f'<tspan fill="{t["muted"]}">.{html.escape(key)}</tspan></text>',
            f'<path d="{dots}" stroke="{t["line"]}" shape-rendering="crispEdges"/>',
            f'<text x="{num(right)}" y="{num(y)}" text-anchor="end" fill="{t["ink"]}" font-family="{MONO}" '
            f'font-size="{size}" textLength="{num(vw)}" lengthAdjust="spacingAndGlyphs">{html.escape(value)}</text>',
        ]
        y += 24

    p += [
        f'<path d="M488 512H1152" stroke="{t["line"]}"/>',
        f'<text x="490" y="534" fill="{t["accent"]}" font-family="{MONO}" font-size="11">'
        "● building · shipping · learning</text>",
        f'<text x="1150" y="534" text-anchor="end" fill="{t["subtle"]}" font-family="{MONO}" font-size="11">'
        "UTC+3 · ISTANBUL NODE</text>",
        f'<g clip-path="url(#win)">{skyline(t, rng)}</g>',
        "</svg>",
    ]
    return "".join(p)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Kaynak fotoğraf yok: {SOURCE}")
    OUT.mkdir(parents=True, exist_ok=True)
    for i, theme in enumerate(THEMES):
        rng = np.random.default_rng(SEED + i)
        portrait = portrait_points(theme, rng)
        shapes = [shape_points(s, rng, TRAVELLERS) for s in ("</>", "{ }", ">_")]
        svg = render(theme, portrait, shapes, rng)
        out = OUT / f"banner-{theme}.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size / 1024:.0f} KiB, {len(portrait)} nokta")


if __name__ == "__main__":
    main()
