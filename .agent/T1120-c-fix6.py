import pathlib
P = pathlib.Path('scripts/build_site.py')
raw = P.read_bytes().decode('utf-8')
crlf = '\r\n' in raw
text = raw.replace('\r\n', '\n')
lines = text.split('\n')
def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]): return i
    return -1
applied = []
# the fade block (same text as the verified version)
fade = [
'  /* The strip scrolls inside itself, and the label at the cut used to be sliced through the middle',
'     of a letter: a cut with nothing to say so reads as a bug, not as an invitation to scroll. This',
'     is a 24 px fade over the last 24 px of the strip, in the ground colour the page already uses,',
'     with no new colour and no shadow. It is drawn on the strip and not inside the scrolling list,',
'     so it stays put while the list moves, and it is drawn at this width only: above it the list',
'     wraps and nothing is cut. The script at the foot of the page puts the class on while there is',
'     more to the right, and takes it off at the end of the list, where nothing is cut. */',
'  .qi-inner::after{content:"";position:absolute;top:0;bottom:0;right:var(--qi-pad);width:24px;',
'   background:var(--bg);pointer-events:none;opacity:0;',
'   -webkit-mask-image:linear-gradient(to right,rgba(0,0,0,0),#000);',
'   mask-image:linear-gradient(to right,rgba(0,0,0,0),#000)}',
'  .qi-inner.qi-more::after{opacity:1}',
]
if not any('.qi-inner::after{' in l for l in lines):
    i = find(lambda s: s.strip() == '.qi-inner{padding:0 16px}')
    assert i >= 0, 'phone .qi-inner rule not found'
    lines[i] = lines[i].replace('.qi-inner{padding:0 16px}', '.qi-inner{--qi-pad:16px;padding:0 var(--qi-pad);position:relative}')
    j = find(lambda s: s.strip() == '.qi-d{display:none}')
    assert j >= 0, '.qi-d rule not found'
    for k in range(len(fade) - 1, -1, -1):
        lines.insert(j + 1, fade[k])
    applied.append('fade css')
else:
    applied.append('fade css already present')
if not any(l.strip() == '<script>' for l in lines):
    k = find(lambda s: 'class="dashrow"' in s)
    assert k >= 0, 'dashrow anchor'
    m = -1
    for j2 in range(k, len(lines)):
        if lines[j2].strip() == '</main>': m = j2; break
    assert m >= 0, 'main anchor'
    pos = m + 1
    if pos < len(lines) and lines[pos].strip() == '': pos += 1
    js = [
    '<script>',
    '/* The quick index scrolls inside itself on a phone, and the label at the cut used to be sliced',
    '   through the middle of a letter. The fade over the last 24 px of the strip says there is more.',
    '   This is the only script on this page: it changes no text, no number and no layout. It only puts',
    '   the fade on while the list has more to the right, and takes it off at the end of the list,',
    '   where nothing is cut. */',
    '(function(){{',
    "  var strip=document.querySelector('.qi-inner');",
    "  var list=document.querySelector('.qi-list');",
    '  if(!strip||!list){{return;}}',
    '  function update(){{',
    '    var more=list.scrollWidth-list.clientWidth-list.scrollLeft>1;',
    "    if(strip.classList.contains('qi-more')!==more){{strip.classList.toggle('qi-more',more);}}",
    '  }}',
    "  list.addEventListener('scroll',update,{{passive:true}});",
    "  window.addEventListener('resize',update);",
    "  window.addEventListener('load',update);",
    '  update();',
    '}})();',
    '</script>',
    ]
    for q in range(len(js) - 1, -1, -1):
        lines.insert(pos, js[q])
    applied.append('scroll listener')
else:
    applied.append('script already present')
# the map: if the map sits inside .mast-right, hide that block; otherwise hide the map itself
markup = '\n'.join(lines)
map_in_block = False
if '<div class="mast-right">' in markup and '<svg class="map"' in markup:
    a = markup.index('<div class="mast-right">'); b = markup.index('<svg class="map"')
    map_in_block = '</div>' not in markup[a:b]
base = find(lambda s: s.strip().startswith('.mast-right{') and 'display:flex' in s)
if map_in_block and base >= 0:
    # remove the earlier .map{display:none} rule I added, and hide the block instead
    keep = []
    skip_next = False
    for l in lines:
        if '@media (max-width:560px){.map{display:none}}' in l:
            skip_next = True
            continue
        if skip_next and l.strip().startswith('/* The map is decoration'):
            continue
        keep.append(l)
    lines = keep
    base = find(lambda s: s.strip().startswith('.mast-right{') and 'display:flex' in s)
    block = [
    '  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px',
    '     of nothing between the reader and the headline, so it goes below this width, the same way the',
    '     methods page hides its tool-name strips below 960 px. The desktop keeps it. The three nav',
    '     links have already moved into the quick index, so the right-hand block the map sat in is empty',
    '     without it, and the empty row and its gap go with it. This rule has to come after the base',
    '     .mast-right rule above, or the base rule wins and the map stays. */',
    '  .mast-right{display:none}',
    ]
    for k in range(len(block) - 1, -1, -1):
        lines.insert(base + 1, block[k])
    applied.append('map: hide .mast-right below 560px')
else:
    applied.append('map: .map hidden below 560px (already applied)')
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('applied:', applied)
