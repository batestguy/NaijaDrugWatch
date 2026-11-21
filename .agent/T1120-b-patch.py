# -*- coding: utf-8 -*-
"""T1120-b: put the approved navigation into the two generators.

Every replacement is anchored on text copied out of the generators themselves, and each anchor must
appear exactly once or the patch stops. Run it once; the generators are then the source of truth.

    .venv\\Scripts\\python.exe -X utf8 .agent\\T1120-b-patch.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SITE_PY = ROOT / "scripts" / "build_site.py"
DASH_PY = ROOT / "scripts" / "build_dashboard.py"

# ------------------------------------------------------------------------------------------
# the stylesheet the two inner pages share
# ------------------------------------------------------------------------------------------
BAR_CSS = r"""
/* ---- the site bar: one row of links, on every page but the front one --------------------
   The front page carries its three links inside its own masthead, so this bar is for the two
   inner pages. It is a fixed 49px, and `--sb-h` is that height and nothing else: the dashboard's
   jump bar is told to stick directly under it with no script, because a number that is written
   down cannot drift from the number that was measured. */
.sitebar{--nav-max:62rem;--nav-pad:.75rem;background:var(--bg);border-bottom:1px solid var(--line);
 position:sticky;top:0;z-index:8;height:var(--sb-h)}
.sb-inner{max-width:var(--nav-max);margin:0 auto;padding:0 var(--nav-pad);height:100%;
 display:flex;align-items:center;justify-content:space-between;gap:16px}
.sb-mark{font-family:"Archivo Black",Impact,sans-serif;font-size:11.5px;letter-spacing:.13em;
 text-transform:uppercase;color:var(--ink);text-decoration:none;white-space:nowrap;line-height:1}
.sb-mark:hover{color:var(--red)}
.sb-links{list-style:none;display:flex;align-items:center;margin:0;padding:0;overflow-x:auto;
 overscroll-behavior-x:contain;scrollbar-width:none}
.sb-links::-webkit-scrollbar{display:none}
.sb-links li{margin:0;padding:0;flex:0 0 auto}
.sb-links a{position:relative;display:block;padding:12px 11px;min-height:44px;line-height:20px;
 font-size:13.5px;font-weight:600;color:var(--ink);text-decoration:none;white-space:nowrap}
.sb-links a::after{content:"";position:absolute;left:11px;right:11px;bottom:9px;height:3px;
 background:transparent}
.sb-links a:hover{color:var(--red)}
.sb-links a[aria-current="page"]{font-weight:700}
.sb-links a[aria-current="page"]::after{background:var(--red)}
.sitebar a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
@media (max-width:560px){
 /* The bar stacks on a phone: the wordmark on one row, the links on the next, the links
    scrolling inside themselves rather than wrapping, so the bar's height stays the height the
    jump bar is told to sit under. */
 :root{--sb-h:76px}
 .sb-inner{flex-direction:column;align-items:stretch;justify-content:flex-start;gap:0}
 .sb-mark{height:31px;display:flex;align-items:center}
 .sb-links{height:44px}
}
"""

# ------------------------------------------------------------------------------------------
# the front page's own: three links in the masthead row, and the quick index under it
# ------------------------------------------------------------------------------------------
FRONT_CSS = r"""
/* ---- the navigation on the front page: three links in the masthead row, and a quick index
   under it. No second wordmark: the masthead already carries the name, so the links join the
   row that is already there, to the left of the map. */
.mast-right{display:flex;align-items:center;gap:28px}
.mastnav ul{list-style:none;display:flex;align-items:center;margin:0;padding:0;overflow-x:auto;
 overscroll-behavior-x:contain;scrollbar-width:none}
.mastnav ul::-webkit-scrollbar{display:none}
.mastnav li{margin:0;padding:0;flex:0 0 auto}
.mastnav a{position:relative;display:block;padding:12px 11px;min-height:44px;line-height:20px;
 font-size:13.5px;font-weight:600;color:var(--ink);text-decoration:none;white-space:nowrap}
.mastnav a::after{content:"";position:absolute;left:11px;right:11px;bottom:9px;height:3px;
 background:transparent}
.mastnav a:hover{color:var(--dress-red)}
.mastnav a[aria-current="page"]{font-weight:700}
.mastnav a[aria-current="page"]::after{background:var(--dress-red)}
.mastnav a:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
/* ---- the quick index: four places to go from the front page, one row under the masthead --- */
.quickidx{background:var(--bg);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.qi-inner{max-width:1240px;margin:0 auto;padding:0 24px}
.qi-list{list-style:none;display:flex;flex-wrap:wrap;margin:0;padding:0}
.qi-list li{margin:0;padding:0;border-left:1px solid var(--rule)}
.qi-list li:first-child{border-left:0}
.qi-list a{display:block;padding:10px 14px;min-height:44px;text-decoration:none;line-height:1.5}
.qi-t{font-size:11px;letter-spacing:.11em;text-transform:uppercase;font-weight:700;color:var(--ink)}
.qi-d{font-size:12.5px;color:var(--muted)}
.qi-d::before{content:"\00a0\2014\00a0"}
.quickidx a:hover .qi-t{color:var(--dress-red)}
.quickidx a:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
@media (max-width:560px){
 /* On a phone the masthead stacks, so the three links move into the quick index, which becomes
    one row of four labels that scrolls inside itself - the pattern the dashboard's jump bar
    already uses - and the glosses go, because four of them cannot sit above the heading on a
    phone without costing more room than the heading is worth. */
 .mastnav{display:none}
 .qi-inner{padding:0 16px}
 .qi-list{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none}
 .qi-list::-webkit-scrollbar{display:none}
 .qi-list li{border-left:0;border-right:1px solid var(--rule)}
 .qi-list a{height:44px;min-height:44px;padding:0 12px;display:flex;align-items:center;
  white-space:nowrap}
 .qi-d{display:none}
}
"""

# ------------------------------------------------------------------------------------------
# the patches
# ------------------------------------------------------------------------------------------
SITE_PATCHES: list[tuple[str, str]] = [
    # 1. the new colour pairs go into the build-time contrast audit, so they are measured on
    #    every build rather than assumed once
    (
        '    ("front: step figure three on the page", DRESS_GOLD, PAPER),\n]\n',
        '    ("front: step figure three on the page", DRESS_GOLD, PAPER),\n'
        '    # the navigation: the three links, the rule under the current one, and the quick index\n'
        '    ("front: a navigation link on the page", INK, PAPER),\n'
        '    ("front: the current page\'s rule on the page", DRESS_RED, PAPER),\n'
        '    ("front: a quick index label on the page", INK, PAPER),\n'
        '    ("front: a quick index gloss on the page", MUTED, PAPER),\n'
        ']\n',
    ),
    # 2. the methods page's stylesheet grows the site bar
    (
        "@media (max-width:420px){\n .step{padding:.8rem .8rem .9rem}\n .step h2{font-size:1rem}\n}\n"
        '""" + (\n',
        "@media (max-width:420px){\n .step{padding:.8rem .8rem .9rem}\n .step h2{font-size:1rem}\n}\n"
        ":root{--sb-h:49px}\n"
        + BAR_CSS +
        '""" + (\n',
    ),
    # 3. the front page's stylesheet grows the masthead links and the quick index
    (
        "  .wrap{padding-left:16px;padding-right:16px}\n"
        "  .hero-grid{padding-left:16px;padding-right:16px}\n}\n\"\"\"\n",
        "  .wrap{padding-left:16px;padding-right:16px}\n"
        "  .hero-grid{padding-left:16px;padding-right:16px}\n}\n"
        + FRONT_CSS +
        "\"\"\"\n",
    ),
    # 4. the front page's masthead row gains the three links, to the left of the map
    (
        '    <div>\n'
        '      <div class="brand">Naija<b>Drug</b>Watch</div>\n'
        '      <p class="tagline">{masthead_line}</p>\n'
        '    </div>\n'
        '    <svg class="map" viewBox="0 0 100 82" role="img" aria-label="Outline of Nigeria">\n',
        '    <div>\n'
        '      <div class="brand">Naija<b>Drug</b>Watch</div>\n'
        '      <p class="tagline">{masthead_line}</p>\n'
        '    </div>\n'
        '    <div class="mast-right">\n'
        '      <nav class="mastnav" aria-label="Site">\n'
        '        <ul class="sb-links">\n'
        '          <li><a href="index.html" aria-current="page">The finding</a></li>\n'
        '          <li><a href="dashboard.html">Every price</a></li>\n'
        '          <li><a href="about.html">How this was made</a></li>\n'
        '        </ul>\n'
        '      </nav>\n'
        '      <svg class="map" viewBox="0 0 100 82" role="img" aria-label="Outline of Nigeria">\n',
    ),
    # 5. ... and the map's group is closed, and the quick index follows the masthead
    (
        '      <path d="{NIGERIA_MAP_PATH}"/>\n'
        "    </svg>\n"
        "  </div>\n"
        "</header>\n",
        '      <path d="{NIGERIA_MAP_PATH}"/>\n'
        "    </svg>\n"
        "    </div>\n"
        "  </div>\n"
        "</header>\n"
        "\n"
        '<nav class="quickidx" aria-label="Quick index">\n'
        '  <div class="qi-inner">\n'
        '    <ul class="qi-list">\n'
        '      <li><a href="#finding"><span class="qi-t">The finding</span>'
        '<span class="qi-d">the {reg[\'matched_flagged\']:,} on this page</span></a></li>\n'
        '      <li><a href="dashboard.html"><span class="qi-t">Every price</span>'
        '<span class="qi-d">{overview[\'latest_listings\']:,} prices, explorable</span></a></li>\n'
        '      <li><a href="#get-the-data"><span class="qi-t">Get the data</span>'
        '<span class="qi-d">the frozen vintage</span></a></li>\n'
        '      <li><a href="about.html"><span class="qi-t">How this was made</span>'
        '<span class="qi-d">the method and the limits</span></a></li>\n'
        "    </ul>\n"
        "  </div>\n"
        "</nav>\n",
    ),
    # 6. the finding block gets an anchor, so the quick index can point at the 154
    (
        '        finding = f"""<div class="finding">\n',
        '        finding = f"""<div class="finding" id="finding">\n',
    ),
    # 7. the methods page: the one-line back link goes, and the site bar takes its place
    (
        '<body>\n'
        '<a class="skip" href="#main">Skip to the content</a>\n'
        '<div class="wrap">\n'
        '<header>\n'
        '<p class="subhead"><a href="index.html">&larr; Medicine prices and registration status '
        'in Nigeria</a></p>\n'
        '<h1>How this was built</h1>\n',
        '<body>\n'
        '<a class="skip" href="#main">Skip to the content</a>\n'
        '<nav class="sitebar" aria-label="Site">\n'
        '  <div class="sb-inner">\n'
        '    <a class="sb-mark" href="index.html" aria-label="NaijaDrugWatch, home page">'
        'NaijaDrugWatch</a>\n'
        '    <ul class="sb-links">\n'
        '      <li><a href="index.html">The finding</a></li>\n'
        '      <li><a href="dashboard.html">Every price</a></li>\n'
        '      <li><a href="about.html" aria-current="page">How this was made</a></li>\n'
        '    </ul>\n'
        '  </div>\n'
        '</nav>\n'
        '<div class="wrap">\n'
        '<header>\n'
        '<h1>How this was built</h1>\n',
    ),
]

DASH_PATCHES: list[tuple[str, str]] = [
    # 1. the bar's height, in the page's own variables
    (
        "--pad-x:.75rem;--jump-h:56px;--s1:8px;",
        "--pad-x:.75rem;--jump-h:56px;--sb-h:49px;--s1:8px;",
    ),
    # 2. the bar's own styles, and the jump bar's sticky offset, which now sits under it
    (
        '.jump a[aria-current="true"] .jn{color:var(--c)}\n'
        "@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}\n",
        '.jump a[aria-current="true"] .jn{color:var(--c)}\n'
        "@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}\n"
        + BAR_CSS.replace("--nav-max:62rem;--nav-pad:.75rem;",
                          "--nav-max:76rem;--nav-pad:var(--pad-x);") +
        "\n"
        "/* The jump bar sticks directly under the site bar, and a section's scroll margin grows by\n"
        "   the same amount, so a jumped-to heading still lands below the jump bar and not under it. */\n"
        ".jump{top:var(--sb-h)}\n"
        ".sect{margin:0 0 var(--s5);scroll-margin-top:calc(var(--sb-h) + var(--jump-h) + var(--s1))}\n"
        "main{scroll-margin-top:calc(var(--sb-h) + var(--jump-h) + var(--s1))}\n",
    ),
    # 3. the one-line back link goes, and the site bar takes its place
    (
        '<body>\n'
        '<a class="skip" href="#main">Skip to the prices</a>\n'
        '<div class="wrap">\n'
        '<header>\n'
        '<p class="muted"><a href="index.html">&larr; Medicine prices and registration status '
        'in Nigeria</a></p>\n'
        '<h1>Every price, and what the data can say</h1>\n',
        '<body>\n'
        '<a class="skip" href="#main">Skip to the prices</a>\n'
        '<nav class="sitebar" aria-label="Site">\n'
        '  <div class="sb-inner">\n'
        '    <a class="sb-mark" href="index.html" aria-label="NaijaDrugWatch, home page">'
        'NaijaDrugWatch</a>\n'
        '    <ul class="sb-links">\n'
        '      <li><a href="index.html">The finding</a></li>\n'
        '      <li><a href="dashboard.html" aria-current="page">Every price</a></li>\n'
        '      <li><a href="about.html">How this was made</a></li>\n'
        '    </ul>\n'
        '  </div>\n'
        '</nav>\n'
        '<div class="wrap">\n'
        '<header>\n'
        '<h1>Every price, and what the data can say</h1>\n',
    ),
    # 4. the new colour pairs go into the build-time contrast audit
    (
        '    ("chip: the clear-all label on the panel", CREAM_INK, CREAM_PANEL),\n]\n',
        '    ("chip: the clear-all label on the panel", CREAM_INK, CREAM_PANEL),\n'
        '    # the site bar above the jump bar: its links, and the rule under the current page\n'
        '    ("nav: a link on the bar", CREAM_INK, CREAM_PAPER),\n'
        '    ("nav: the current page\'s rule on the bar", DRESS_RED, CREAM_PAPER),\n'
        ']\n',
    ),
]


def apply(path: Path, patches: list[tuple[str, str]]) -> int:
    text = path.read_text(encoding="utf-8")
    for index, (old, new) in enumerate(patches, start=1):
        found = text.count(old)
        if found != 1:
            print(f"STOP: {path.name} patch {index}: anchor found {found} times, expected 1",
                  file=sys.stderr)
            print("---- anchor ----", file=sys.stderr)
            print(old[:400], file=sys.stderr)
            sys.exit(1)
        text = text.replace(old, new, 1)
        print(f"  {path.name} patch {index}: applied ({len(old)} chars out, {len(new)} in)")
    path.write_text(text, encoding="utf-8")
    return len(patches)


if __name__ == "__main__":
    total = apply(SITE_PY, SITE_PATCHES)
    total += apply(DASH_PY, DASH_PATCHES)
    print(f"{total} patches applied")
    for script in (SITE_PY, DASH_PY):
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
        print(f"  {script.name} compiles")
