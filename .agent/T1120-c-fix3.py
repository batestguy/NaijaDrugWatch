import pathlib
src = pathlib.Path('scripts/build_site.py').read_bytes().decode('utf-8').replace('\r\n','\n').split('\n')
targets = [
 ('CSS_CREAM', 'css cream'),
 ('<title>How this was made - NaijaDrugWatch</title>', 'title'),
 ('<h1>How this was made</h1>', 'h1'),
 ('<a class="dash" href="about.html">How this was made</a>', 'dash'),
 ('.mast-right{display:none}', 'map rule'),
 ('.qi-inner{--qi-pad:16px', 'qi-pad'),
 ('.qi-inner::after{', 'fade'),
 ('.qi-inner.qi-more::after', 'qi-more'),
 ('<script>', 'script'),
]
nums = []
for pat, name in targets:
    hit = None
    for i, line in enumerate(src):
        if pat in line:
            hit = i + 1
            break
    assert hit is not None, (pat, [l[:90] for l in src if 'CSS' in l][:4])
    nums.append(hit)
    print(name, '-> line', hit, '|', src[hit-1].strip()[:80])
rep = pathlib.Path('.agent/T1120-c-report.md').read_text(encoding='utf-8')
rows = [l for l in rep.split('\n') if l.startswith('| `scripts/build_site.py` | ? |')]
print('placeholder rows found:', len(rows))
assert len(rows) == len(nums), (len(rows), len(nums))
for row, n in zip(rows, nums):
    rep = rep.replace(row, row.replace('| ? |', '| %d |' % n))
rep = rep.replace('20 lines of vanilla script', 'thirteen lines of vanilla script')
pathlib.Path('.agent/T1120-c-report.md').write_text(rep, encoding='utf-8')
for l in rep.split('\n'):
    if l.startswith('| `scripts/build_site.py`'):
        print(l[:118])
