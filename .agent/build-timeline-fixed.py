import pathlib, re

MAIN = pathlib.Path("D:/NaijaDrugWatch/.playwright-mcp/v2")
FIX = pathlib.Path("D:/NaijaDrugWatch/.playwright-mcp/v2fix")

def load(dirpath, prefix):
    out = []
    for f in sorted(dirpath.glob(prefix + "*.png")):
        m = re.search(r"_(\d{4})\.png$", f.name)
        out.append((int(f.name[1:5]), f, int(m.group(1)) / 100.0))
    return out

main = load(MAIN, "f")
fix = load(FIX, "g")
by_index = {i: (f, d) for i, f, d in main}

# the licence block as captured first time: glide f0151..f0192, hold f0193
licence = [i for i, f, d in main if 151 <= i <= 193]
assert licence == list(range(151, 194)), licence[:5]

ordered = [by_index[i] for i in sorted(by_index) if i <= 150]
ordered += [(f, d) for _, f, d in fix]
ordered += [by_index[i] for i in sorted(by_index) if i >= 194]

total = sum(d for _, d in ordered)
listfile = pathlib.Path("D:/NaijaDrugWatch/.playwright-mcp/v2/list-fixed.txt")
with listfile.open("w", encoding="utf-8", newline="\n") as fh:
    for f, d in ordered:
        fh.write("file '" + f.as_posix() + "'\n")
        fh.write("duration " + f"{d:.2f}" + "\n")
    fh.write("file '" + ordered[-1][0].as_posix() + "'\n")

print("frames in the cut:", len(ordered), "| replaced 43 with", len(fix))
print("total seconds: %.2f" % total)
print("fade out from: %.2f" % max(0.0, total - 4.4))
