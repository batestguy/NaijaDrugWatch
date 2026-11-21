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
if 'How this was built' in text:
    assert text.count('How this was built') == 3, text.count('How this was built')
    text = text.replace('How this was built', 'How this was made')
    lines = text.split('\n')
    applied.append('name x3')
i = find(lambda s: s.strip() == '.qi-inner{padding:0 16px}')
if i >= 0:
    lines[i] = lines[i].replace('.qi-inner{padding:0 16px}', '.qi-inner{--qi-pad:16px;padding:0 var(--qi-pad);position:relative}')
    applied.append('qi-pad')
maplines = [
'  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px',
'     of nothing between the reader and the headline, so it goes below this width. The three nav',
'     links have already moved into the quick index, so the right-hand block the map sat in is empty',
'     without it, and the empty row and its gap go with it. This rule has to sit after the base',
'     .mast-right rule, or the base rule wins and the map stays. */',
'  .mast-right{display:none}',
]
fadelines = [
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
block = []
if not any('.mast-right{display:none}' in l for l in lines): block += maplines
if not any('.qi-inner::after{' in l for l in lines): block += fadelines
if block:
    j = find(lambda s: s.strip() == '.qi-d{display:none}')
    base = find(lambda s: s.strip() == '.mast-right{display:flex;align-items:center;gap:28px}')
    assert j >= 0 and base >= 0 and base < j, (base, j)
    for k in range(len(block) - 1, -1, -1):
        lines.insert(j + 1, block[k])
    applied.append('fade' if len(block) != 6 else 'map+fade')
if not any(l.strip() == '<script>' for l in lines):
    k = find(lambda s: 'class="dashrow"' in s)
    assert k >= 0
    m = -1
    for j2 in range(k, len(lines)):
        if lines[j2].strip() == '</main>': m = j2; break
    assert m >= 0
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
    applied.append('script')
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('applied:', applied)
