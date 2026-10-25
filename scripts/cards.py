#!/usr/bin/env python3
"""İstatistik, streak ve dil kartlarını SVG olarak üretir (sadece standart kütüphane).

Ortak servisler (github-readme-stats, streak-stats) sık sık çöküyor ya da kota
doluyor; bu kartlar repodaki dosyalar olduğu için GitHub açık olduğu sürece görünür.
GitHub Actions her gün çalıştırır (.github/workflows/cards.yml).

    GITHUB_TOKEN=... python scripts/cards.py --user MrcDprm --out assets
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://api.github.com"
FONT = "'Segoe UI',ui-sans-serif,-apple-system,Helvetica,Arial,sans-serif"

# Gece Şehri paleti (portfolio/app/globals.css)
THEMES = {
    "dark": {"bg": "#131a25", "line": "#293444", "ink": "#eceff4", "muted": "#9ca7b8",
             "subtle": "#6b788b", "accent": "#f5c77e", "track": "#1f2938"},
    "light": {"bg": "#ecf0f5", "line": "#c4cdd9", "ink": "#161e2e", "muted": "#485468",
              "subtle": "#68758a", "accent": "#a64d0a", "track": "#dde3eb"},
}

# GitHub'ın (linguist) dil renkleri
LANG_COLOR = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "Java": "#b07219", "C#": "#178600",
    "C++": "#f34b7d", "TypeScript": "#3178c6", "Go": "#00ADD8", "HTML": "#e34c26",
    "CSS": "#663399", "C": "#555555", "Shell": "#89e051", "PowerShell": "#012456",
    "Dart": "#00B4AB", "PHP": "#4F5D95", "Kotlin": "#A97BFF", "Swift": "#F05138",
    "Rust": "#dea584", "CMake": "#DA3434", "Dockerfile": "#384d54", "Jupyter Notebook": "#DA5B0B",
}

# Dil kartına sayılmayan repolar (bu profil reposu SVG ve script'ten ibaret)
SKIP_REPOS = {"mrcdprm"}


# ---------------------------------------------------------------- API


def request(url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "mrcdprm-profile-cards",
        **({"Content-Type": "application/json"} if body else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def graphql(query: str, variables: dict, token: str) -> dict:
    res = request(f"{API}/graphql", token, {"query": query, "variables": variables})
    if res.get("errors"):
        raise SystemExit(f"GraphQL hatası: {res['errors']}")
    return res["data"]


YEAR_QUERY = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      contributionCalendar{ weeks{ contributionDays{ date contributionCount } } }
    }
  }
}
"""


def fetch_days(user: str, token: str, tz: str) -> tuple[list[tuple[dt.date, int]], dict[str, int]]:
    """Hesap açıldığından bugüne her günün katkı sayısı ve toplam commit/issue/PR sayıları."""
    created = graphql("query($l:String!){user(login:$l){createdAt}}", {"l": user}, token)["user"]["createdAt"]
    # "Bugün" kullanıcının saat dilimine göre: UTC'ye göre alınırsa gece yarısından sonraki
    # katkılar (İstanbul'da 00:00-03:00) bir sonraki çalışmaya kadar sayılmaz
    today = dt.datetime.now(ZoneInfo(tz)).date()
    days: dict[dt.date, int] = {}
    totals = {"commits": 0, "issues": 0, "prs": 0}
    # GraphQL tek sorguda en fazla 1 yıl veriyor; yıl yıl istenir
    for year in range(int(created[:4]), today.year + 1):
        coll = graphql(YEAR_QUERY, {"login": user, "from": f"{year}-01-01T00:00:00Z",
                                    "to": f"{year}-12-31T23:59:59Z"}, token)["user"]["contributionsCollection"]
        totals["commits"] += coll["totalCommitContributions"]
        totals["issues"] += coll["totalIssueContributions"]
        totals["prs"] += coll["totalPullRequestContributions"]
        for week in coll["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                day = dt.date.fromisoformat(d["date"])
                if day <= today:
                    days[day] = d["contributionCount"]
    return sorted(days.items()), totals


def fetch_repos(user: str, token: str) -> list[dict]:
    repos, page = [], 1
    while True:
        batch = request(f"{API}/users/{user}/repos?per_page=100&type=owner&page={page}", token)
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


# ---------------------------------------------------------------- hesaplar


def streaks(days: list[tuple[dt.date, int]]):
    """(mevcut seri, başlangıç, bitiş) ve (en uzun seri, başlangıç, bitiş)."""
    longest = (0, None, None)
    run, start = 0, None
    for day, count in days:
        if count:
            start = day if run == 0 else start
            run += 1
            if run > longest[0]:
                longest = (run, start, day)
        else:
            run = 0

    # Bugün henüz bitmedi: bugün katkı yoksa seri dünden geriye sayılır
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:
        i -= 1
    end = days[i][0] if i >= 0 else None
    current = 0
    while i >= 0 and days[i][1]:
        current += 1
        i -= 1
    cur_start = days[i + 1][0] if current else None
    return (current, cur_start, end if current else None), longest


def fmt_date(d: dt.date | None) -> str:
    return f"{d:%b} {d.day}, {d.year}" if d else "—"


def fmt_range(a: dt.date | None, b: dt.date | None) -> str:
    if not a or not b:
        return "—"
    if a == b:
        return fmt_date(a)
    left = f"{a:%b} {a.day}" if a.year == b.year else fmt_date(a)
    return f"{left} – {fmt_date(b)}"


def fmt_bytes(n: int) -> str:
    return f"{n / 1_000_000:.2f} MB" if n >= 1_000_000 else f"{n / 1000:.0f} kB"


def fmt_num(n: int) -> str:
    return f"{n:,}"


def esc(s: str) -> str:
    return html.escape(s)


# ---------------------------------------------------------------- kartlar


def frame(w: int, h: int, t: dict, label: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(label)}" font-family="{FONT}">'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="12" fill="{t["bg"]}" stroke="{t["line"]}"/>'
            f"{body}</svg>")


def streak_card(t: dict, total: int, first: dt.date, last: dt.date, current, longest) -> str:
    w, h = 1000, 200
    col = w / 3
    fire = ("M0-15c4 6 11 10 11 18a11 11 0 0 1-22 0c0-5 3-8 5-11 0 4 2 6 4 6-1-5 0-9 2-13z")
    parts = [
        f'<path d="M{col:.0f} 34V166M{2 * col:.0f} 34V166" stroke="{t["line"]}"/>',
        # Toplam katkı
        f'<text x="{col / 2:.0f}" y="94" text-anchor="middle" font-size="34" font-weight="700" fill="{t["ink"]}">{fmt_num(total)}</text>',
        f'<text x="{col / 2:.0f}" y="128" text-anchor="middle" font-size="15" fill="{t["muted"]}">Total Contributions</text>',
        f'<text x="{col / 2:.0f}" y="154" text-anchor="middle" font-size="12" fill="{t["subtle"]}">{esc(fmt_range(first, last))}</text>',
        # Mevcut seri: halka + alev
        f'<circle cx="{w / 2:.0f}" cy="76" r="42" fill="none" stroke="{t["track"]}" stroke-width="6"/>',
        f'<circle cx="{w / 2:.0f}" cy="76" r="42" fill="none" stroke="{t["accent"]}" stroke-width="6" '
        f'stroke-dasharray="230 34" transform="rotate(-62 {w / 2:.0f} 76)"/>',
        f'<path d="{fire}" transform="translate({w / 2:.0f} 30) scale(.62)" fill="{t["accent"]}" '
        f'stroke="{t["bg"]}" stroke-width="5" paint-order="stroke"/>',
        f'<text x="{w / 2:.0f}" y="88" text-anchor="middle" font-size="32" font-weight="700" fill="{t["ink"]}">{current[0]}</text>',
        f'<text x="{w / 2:.0f}" y="146" text-anchor="middle" font-size="15" font-weight="700" fill="{t["accent"]}">Current Streak</text>',
        f'<text x="{w / 2:.0f}" y="170" text-anchor="middle" font-size="12" fill="{t["subtle"]}">{esc(fmt_range(current[1], current[2]))}</text>',
        # En uzun seri
        f'<text x="{w - col / 2:.0f}" y="94" text-anchor="middle" font-size="34" font-weight="700" fill="{t["ink"]}">{longest[0]}</text>',
        f'<text x="{w - col / 2:.0f}" y="128" text-anchor="middle" font-size="15" fill="{t["muted"]}">Longest Streak</text>',
        f'<text x="{w - col / 2:.0f}" y="154" text-anchor="middle" font-size="12" fill="{t["subtle"]}">{esc(fmt_range(longest[1], longest[2]))}</text>',
    ]
    return frame(w, h, t, "GitHub contribution streak", "".join(parts))


def stats_card(t: dict, user: str, tiles: list[tuple[str, str]]) -> str:
    w, h = 495, 210
    parts = [
        f'<text x="24" y="38" font-size="16" font-weight="700" fill="{t["accent"]}">{esc(user)}</text>',
        f'<text x="{w - 24}" y="38" text-anchor="end" font-size="12" fill="{t["subtle"]}">at a glance</text>',
        f'<path d="M24 52H{w - 24}" stroke="{t["line"]}"/>',
    ]
    for i, (value, label) in enumerate(tiles):
        x = 24 + (i % 4) * 114
        y = 98 + (i // 4) * 66
        parts.append(f'<text x="{x}" y="{y}" font-size="25" font-weight="700" fill="{t["ink"]}">{esc(value)}</text>'
                     f'<text x="{x}" y="{y + 19}" font-size="11.5" fill="{t["muted"]}">{esc(label)}</text>')
    return frame(w, h, t, f"{user} GitHub statistics", "".join(parts))


def languages_card(t: dict, langs: list[tuple[str, int]], total: int) -> str:
    w, h = 495, 210
    x0, bar_w, y_bar = 24, w - 48, 66
    parts = [
        f'<text x="24" y="38" font-size="16" font-weight="700" fill="{t["accent"]}">Most used languages</text>',
        f'<clipPath id="bar"><rect x="{x0}" y="{y_bar}" width="{bar_w}" height="10" rx="5"/></clipPath>',
        f'<rect x="{x0}" y="{y_bar}" width="{bar_w}" height="10" rx="5" fill="{t["track"]}"/>',
        '<g clip-path="url(#bar)">',
    ]
    x = float(x0)
    for name, size in langs:
        seg = bar_w * size / total
        parts.append(f'<rect x="{x:.2f}" y="{y_bar}" width="{seg + 0.6:.2f}" height="10" '
                     f'fill="{LANG_COLOR.get(name, t["subtle"])}"/>')
        x += seg
    parts.append("</g>")

    # İki sütunlu açıklama: nokta, ad, boyut, yüzde
    for i, (name, size) in enumerate(langs):
        cx = 24 + (i % 2) * 236
        cy = 108 + (i // 2) * 26
        parts.append(
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{LANG_COLOR.get(name, t["subtle"])}"/>'
            f'<text x="{cx + 18}" y="{cy}" font-size="13" fill="{t["ink"]}">{esc(name)}</text>'
            f'<text x="{cx + 168}" y="{cy}" text-anchor="end" font-size="12" fill="{t["subtle"]}">{fmt_bytes(size)}</text>'
            f'<text x="{cx + 218}" y="{cy}" text-anchor="end" font-size="12" fill="{t["muted"]}">{100 * size / total:.1f}%</text>'
        )
    return frame(w, h, t, "Most used languages", "".join(parts))


# ---------------------------------------------------------------- çalıştır


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", default="assets")
    ap.add_argument("--tz", default="Europe/Istanbul")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN ortam değişkeni gerekli.")

    days, totals = fetch_days(args.user, token, args.tz)
    total = sum(c for _, c in days)
    first = next((d for d, c in days if c), None)
    current, longest = streaks(days)
    this_year = sum(c for d, c in days if d.year == days[-1][0].year)

    profile = request(f"{API}/users/{args.user}", token)
    repos = [r for r in fetch_repos(args.user, token) if not r["fork"]]
    stars = sum(r["stargazers_count"] for r in repos)

    lang_bytes: dict[str, int] = {}
    for r in repos:
        if r["name"].lower() in SKIP_REPOS:
            continue
        for name, size in request(r["languages_url"], token).items():
            lang_bytes[name] = lang_bytes.get(name, 0) + size
    lang_total = sum(lang_bytes.values()) or 1
    top = sorted(lang_bytes.items(), key=lambda kv: -kv[1])[:8]

    tiles = [
        (fmt_num(total), "Total contributions"),
        (fmt_num(this_year), f"{days[-1][0].year} contributions"),
        (fmt_num(totals["commits"]), "Commits"),
        (fmt_num(totals["prs"]), "Pull requests"),
        (fmt_num(totals["issues"]), "Issues"),
        (fmt_num(profile["public_repos"]), "Public repos"),
        (fmt_num(stars), "Stars earned"),
        (fmt_num(profile["followers"]), "Followers"),
    ]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, t in THEMES.items():
        (out / f"card-streak-{name}.svg").write_text(
            streak_card(t, total, first, days[-1][0], current, longest), encoding="utf-8")
        (out / f"card-stats-{name}.svg").write_text(stats_card(t, args.user, tiles), encoding="utf-8")
        (out / f"card-languages-{name}.svg").write_text(languages_card(t, top, lang_total), encoding="utf-8")

    print(f"katkı {total}, seri {current[0]} (en uzun {longest[0]}), commit {totals['commits']}, "
          f"issue {totals['issues']}, PR {totals['prs']}, "
          f"repo {profile['public_repos']}, yıldız {stars}, dil {len(lang_bytes)}")


if __name__ == "__main__":
    main()
