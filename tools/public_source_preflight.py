"""Check that a source-only network-register export excludes private state and bundles."""
from pathlib import Path
import json
import subprocess
import sys

def main():
    root=Path(__file__).resolve().parents[1]
    out=subprocess.check_output(["git","-C",str(root),"ls-files","-s","-z"])
    files={}
    for line in filter(None,out.decode().split("\0")):
        meta,path=line.split("\t",1)
        mode,sha,stage=meta.split()
        files[path]=mode
    required=("LICENSE","LICENSES/BSD-3-Clause.txt",
              "LICENSES/GPL-3.0-only.txt","THIRD-PARTY-NOTICES.md",
              "src/zog/network_register/__init__.py","zog-component.json")
    issues=[]
    for p in required:
        if p not in files:issues.append(("missing",p))
    for p,mode in files.items():
        if mode!="100644":issues.append(("mode",p))
        if p.startswith("recovery/") or p in (
            "COPYRIGHT","version-share-handoff.json",
            "tools/host_deploy-0.9.0-py3-none-any.whl"):
            issues.append(("private",p))
        if p.endswith((".whl",".zip",".tar",".tgz",".pyc",".sqlite3",".db")):
            issues.append(("bundle",p))
        b=(root/p).read_bytes()
        if b"\0" in b:issues.append(("NUL",p))
        try:b.decode("utf-8")
        except UnicodeDecodeError:issues.append(("UTF8",p))
    component=json.loads((root/"zog-component.json").read_text())
    if component.get("license_notice_paths")!=list(required[:4]):
        issues.append(("notice_manifest","zog-component.json"))
    for p in ("LICENSE","pyproject.toml"):
        if "BSD-3-Clause OR GPL-3.0-only" not in (root/p).read_text():
            issues.append(("license",p))
    print(json.dumps({"tracked_files":len(files),"findings":issues},sort_keys=True))
    return 1 if issues else 0

if __name__=="__main__":sys.exit(main())
