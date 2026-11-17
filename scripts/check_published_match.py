"""Prove the two published copies of the vintage are still the same vintage.

WHY. The export is published twice: as GitHub release assets, which the restore job downloads and
restores, and as a Hugging Face dataset, which is the copy anyone would cite and reuse. Only one of them
is exercised by CI, so without this check the two can drift apart silently - someone re-uploads one, and
the dataset a reader downloads is no longer the thing that was restored and tested. A vintage is only
frozen if every copy of it is identical.

WHAT IT DOES. Takes MANIFEST.json from the release as the authority - it records the sha256 of every
file in the vintage - then downloads each of those files from Hugging Face and compares the hash. It also
hashes the release's own dump, because that is the file the restore job actually loads.

    .venv\\Scripts\\python.exe -X utf8 scripts/check_published_match.py

EXIT CODE. 0 when every published file matches the manifest, 1 on any difference or missing file, 2 when
the manifest cannot be fetched at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

RELEASE_MANIFEST = (
    "https://github.com/batestguy/NaijaDrugWatch/releases/download/vintage-2026-11-16/MANIFEST.json"
)
RELEASE_DUMP = (
    "https://github.com/batestguy/NaijaDrugWatch/releases/download/vintage-2026-11-16/naijadrugwatch.dump"
)
HF_REPO = "JBZABC/naijadrugwatch-vintage-2026-11-16"
HF_FILE = "https://huggingface.co/datasets/{repo}/resolve/main/{name}"
UA = "NaijaDrugWatch/0.1 (+https://github.com/batestguy/NaijaDrugWatch) vintage check"


def sha256_url(url: str, attempts: int = 3) -> str:
    """Hash a remote file without holding it in memory, retrying a download that times out.

    A timeout is not a mismatch. The first run of this script lost a 1.7 MB file to a read timeout and
    reported it as a failure, which is the right exit code but the wrong reason - so retry, and keep the
    two verdicts apart in the output.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                for block in iter(lambda: response.read(1 << 20), b""):
                    digest.update(block)
            return digest.hexdigest()
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise OSError(f"after {attempts} attempts: {last}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compare the two published copies of the vintage.")
    parser.add_argument("--release-manifest", default=RELEASE_MANIFEST)
    parser.add_argument("--release-dump", default=RELEASE_DUMP)
    parser.add_argument("--hf-repo", default=HF_REPO)
    args = parser.parse_args(argv[1:])

    try:
        with urllib.request.urlopen(
            urllib.request.Request(args.release_manifest, headers={"User-Agent": UA}), timeout=60
        ) as response:
            manifest = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"cannot read the release manifest: {exc}", file=sys.stderr)
        return 2

    entries = [e for e in manifest["files"] if e.get("sha256")]
    print(f"manifest lists {len(entries)} files with a checksum")
    print(f"authority: {args.release_manifest}")
    print(f"compared against: huggingface.co/datasets/{args.hf_repo}\n")

    fails: list[str] = []
    unverified: list[str] = []
    for entry in entries:
        name, want = entry["file"], entry["sha256"]
        url = HF_FILE.format(repo=args.hf_repo, name=name)
        try:
            got = sha256_url(url)
        except (urllib.error.URLError, OSError) as exc:
            print(f"UNVERIFIED  {name}: could not be downloaded ({exc})")
            unverified.append(name)
            continue
        if got == want:
            print(f"PASS  {name}  {want[:12]}...")
        else:
            print(f"FAIL  {name}\n      manifest    {want}\n      huggingface {got}")
            fails.append(name)

    # The release dump is the file the restore job actually loads, so hash that too rather than trusting
    # that the release and its manifest were uploaded together.
    dump_entry = next((e for e in entries if e["file"].endswith(".dump")), None)
    if dump_entry:
        try:
            got = sha256_url(args.release_dump)
            if got == dump_entry["sha256"]:
                print(f"PASS  release dump matches its manifest  {got[:12]}...")
            else:
                print(f"FAIL  release dump\n      manifest {dump_entry['sha256']}\n      release  {got}")
                fails.append("release dump")
        except (urllib.error.URLError, OSError) as exc:
            print(f"FAIL  release dump: cannot download ({exc})")
            fails.append("release dump")

    print()
    if fails or unverified:
        if fails:
            print(f"{len(fails)} file(s) DIFFER from the manifest: " + ", ".join(fails))
        if unverified:
            print(f"{len(unverified)} file(s) could not be verified: " + ", ".join(unverified))
        return 1
    print("BOTH PUBLISHED COPIES ARE IDENTICAL TO THE MANIFEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
