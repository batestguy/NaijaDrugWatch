import ast, pathlib, subprocess
head = subprocess.run(['git','show','HEAD:scripts/build_site.py'], capture_output=True).stdout.decode('utf-8')
brk = pathlib.Path('.agent/T1120-c-broken.py').read_bytes().decode('utf-8')
hl = head.replace('\r\n','\n').split('\n')
bl = brk.replace('\r\n','\n').split('\n')
h = -1
for i in range(2, len(hl)):
    if hl[i].strip() == '.fig .n{font-size:24px}' and hl[i-1].strip() == '.fig{flex:1 1 50%}' and hl[i-2].strip() == '@media (max-width:560px){':
        h = i; break
assert h >= 0, 'head split anchor'
lines = hl[0:h+1] + bl[1:]
text = '\n'.join(lines)
good = pathlib.Path('.agent/T1120-c-about-good.html').read_bytes().decode('utf-8')
style = good.split('<style>')[1].split('</style>')[0]
tree = ast.parse(text)
cream_node = None; cursor_val = None
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == 'CSS_CREAM': cream_node = node
        if node.targets[0].id == 'CURSOR_CSS': cursor_val = ast.literal_eval(node.value)
assert cream_node is not None and cursor_val is not None
assert style.endswith(cursor_val), ('style does not end with CURSOR_CSS', len(style), len(cursor_val))
cream = style[:len(style) - len(cursor_val)]
assert '"""' not in cream and not cream.endswith('\\')
lines = text.split('\n')
lines = lines[:cream_node.lineno-1] + ['CSS_CREAM = r"""' + cream + '"""'] + lines[cream_node.end_lineno:]
text = '\n'.join(lines)
lines = text.split('\n')
i = -1
for k, s in enumerate(lines):
    if s.strip() == 'have already moved into the quick index under the masthead, so the right-hand block the map sat':
        i = k; break
assert i >= 0, 'early fragment not found'
assert lines[i+1].strip().endswith('*/'), lines[i+1]
assert lines[i+2].strip() == '.mast-right{display:none}', lines[i+2]
del lines[i:i+3]
text = '\n'.join(lines)
ast.parse(text)
out = text.replace('\n','\r\n')
pathlib.Path('scripts/build_site.py').write_bytes(out.encode('utf-8'))
print('REBUILT: cream chars', len(cream), 'lines', len(text.split('\n')))
