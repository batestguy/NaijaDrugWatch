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
    n = text.count('How this was built')
    assert n == 3, ('name occurrences', n)
    text = text.replace('How this was built', 'How this was made')
    lines = text.split('\n')
    applied.append('name x3')
i = find(lambda s: '.map{width:58px' in s)
assert i >= 0, 'base .map rule not found'
if not any('@media (max-width:560px){.map{display:none}}' in l for l in lines):
    block = [
    '/* The map is decoration. On a phone it sat on a line of its own under the tagline, about 85 px',
    '   of nothing between the reader and the headline, so it goes below this width, the same way the',
    '   methods page hides its tool-name strips below 960 px. The desktop keeps it. This rule has to',
    '   come after the base .map rule above, or the base rule wins and the map stays. */',
    '@media (max-width:560px){.map{display:none}}',
    ]
    for k in range(len(block) - 1, -1, -1):
        lines.insert(i + 1, block[k])
    applied.append('map hidden below 560px')
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('applied:', applied)
