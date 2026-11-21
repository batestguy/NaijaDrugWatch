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
base = find(lambda s: s.strip() == '.mast-right{display:flex;align-items:center;gap:28px}')
print('base rule at', base + 1)
# remove a bare (non-media-query) .mast-right{display:none} that sits right after the base rule
if base + 1 < len(lines) and lines[base+1].strip() == '.mast-right{display:none}':
    del lines[base+1]
    print('removed the bare rule after the base rule')
# make sure the rule that is inside the phone media query carries its comment
rule = find(lambda s: s.strip() == '.mast-right{display:none}')
print('remaining rule at', rule + 1)
has_comment = False
for k in range(max(0, rule-8), rule):
    if 'The map is decoration' in lines[k]:
        has_comment = True
if not has_comment:
    block = [
    '  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px',
    '     of nothing between the reader and the headline, so it goes below this width, the same way the',
    '     methods page hides its tool-name strips below 960 px. The desktop keeps it. The three nav',
    '     links have already moved into the quick index, so the right-hand block the map sat in is empty',
    '     without it, and the empty row and its gap go with it. */',
    ]
    for k in range(len(block)-1, -1, -1):
        lines.insert(rule + k, block[k])
    print('comment added')
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
