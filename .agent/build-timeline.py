import pathlib, re

DIR = pathlib.Path("D:/NaijaDrugWatch/.playwright-mcp/v2")
files = sorted(DIR.glob("f*.png"))
if not files:
    raise SystemExit("no frames")

entries = []
total = 0.0
for f in files:
    m = re.search(r"_(\d{4})\.png$", f.name)
    if not m:
        raise SystemExit("bad frame name: " + f.name)
    dur = int(m.group(1)) / 100.0
    total += dur
    entries.append((f, dur))

out = pathlib.Path("D:/NaijaDrugWatch/.playwright-mcp/v2/list.txt")
with out.open("w", encoding="utf-8", newline="\n") as fh:
    for f, dur in entries:
        fh.write("file '" + f.as_posix() + "'\n")
        fh.write("duration " + f"{dur:.2f}" + "\n")
    # concat demuxer needs the final frame once more to honour its duration
    fh.write("file '" + entries[-1][0].as_posix() + "'\n")

print("frames:", len(entries))
print("total seconds: %.2f" % total)
print("fade out should start at: %.2f" % max(0.0, total - 4.0))
