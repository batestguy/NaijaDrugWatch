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
base = find(lambda s: s.strip().startswith('.mast-right{') and 'display:flex' in s)
print('base .mast-right at line', base + 1, '|', lines[base].strip()[:60])
removed = 0
if base + 1 < len(lines) and lines[base+1].strip().startswith('/* The map is decoration'):
    for k in range(base + 1, base + 8):
        print('  removing:', lines[k].strip()[:70])
    del lines[base+1:base+7]
    removed = 6
out = '\n'.join(lines)
if crlf: out = out.replace('\n', '\r\n')
P.write_bytes(out.encode('utf-8'))
print('removed', removed, 'lines')
