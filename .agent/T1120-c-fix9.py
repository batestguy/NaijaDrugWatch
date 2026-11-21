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
markup = '\n'.join(lines)
a = markup.find('<div class="mast-right">'); b = markup.find('<svg class="map"')
map_in_block = (a >= 0 and b > a and '</div>' not in markup[a:b])
print('mast-right div at', a, '| map svg at', b, '| map inside mast-right:', map_in_block)
# remove the existing map rule and its comment wherever they are
keep = []
i = 0
while i < len(lines):
    l = lines[i]
    if l.strip() == '.mast-right{display:none}' or l.strip() == '.map{display:none}':
        # drop a comment block just above that mentions the map
        while keep and 'The map is decoration' in keep[-1]:
            keep.pop()
        i += 1
        continue
    keep.append(l); i += 1
lines = keep
j = find(lambda s: s.strip() == '.qi-d{display:none}')
assert j >= 0, 'phone block anchor .qi-d not found'
sel = '.mast-right{display:none}' if map_in_block else '.map{display:none}'
block = [
'  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px',
'     of nothing between the reader and the headline, so it goes below this width, the same way the',
'     methods page hides its tool-name strips below 960 px. The desktop keeps it. The three nav',
'     links have already moved into the quick index, so the right-hand block the map sat in is empty',
'     without it, and the empty row and its gap go with it. */',
'  ' + sel,
]
for k in range(len(block) - 1, -1, -1):
    lines.insert(j + 1, block[k])
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('inserted', sel, 'after the .qi-d rule at line', j + 1)
