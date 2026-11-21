import ast, pathlib
P = pathlib.Path('scripts/build_site.py')
raw = P.read_bytes().decode('utf-8')
crlf = '\r\n' in raw
text = raw.replace('\r\n', '\n')
good = pathlib.Path('.agent/T1120-c-about-good.html').read_bytes().decode('utf-8')
style = good.split('<style>')[1].split('</style>')[0]
tree = ast.parse(text)
cream_node = None; cursor_val = None
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == 'CSS_CREAM': cream_node = node
        if node.targets[0].id == 'CURSOR_CSS': cursor_val = ast.literal_eval(node.value)
assert cream_node is not None and cursor_val is not None
assert style.endswith(cursor_val), 'style does not end with CURSOR_CSS'
cream = style[:len(style) - len(cursor_val)]
assert '"""' not in cream and not cream.endswith('\\')
lines = text.split('\n')
lines = lines[:cream_node.lineno - 1] + ['CSS_CREAM = r"""' + cream + '"""'] + lines[cream_node.end_lineno:]
text = '\n'.join(lines)
assert text.count('How this was built') == 3, text.count('How this was built')
text = text.replace('How this was built', 'How this was made')
lines = text.split('\n')
def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]): return i
    return -1
i = find(lambda s: s.strip() == '.qi-inner{padding:0 16px}')
assert i >= 0, 'qi-inner anchor missing'
lines[i] = lines[i].replace('.qi-inner{padding:0 16px}', '.qi-inner{--qi-pad:16px;padding:0 var(--qi-pad);position:relative}')
base = find(lambda s: s.strip() == '.mast-right{display:flex;align-items:center;gap:28px}')
j = find(lambda s: s.strip() == '.qi-d{display:none}')
assert base >= 0 and j >= 0 and j > base, (base, j)
block = [
'  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px',
'     of nothing between the reader and the headline, so it goes below this width. The three nav',
'     links have already moved into the quick index, so the right-hand block the map sat in is empty',
'     without it, and the empty row and its gap go with it. This rule has to sit after the base',
'     .mast-right rule, or the base rule wins and the map stays. */',
'  .mast-right{display:none}',
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
for k in range(len(block) - 1, -1, -1):
    lines.insert(j + 1, block[k])
k = find(lambda s: 'class="dashrow"' in s)
assert k >= 0, 'dashrow anchor missing'
m = -1
for j2 in range(k, len(lines)):
    if lines[j2].strip() == '</main>': m = j2; break
assert m >= 0, 'main anchor missing'
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
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('PATCH OK: cream chars', len(cream), 'lines', len(lines))
