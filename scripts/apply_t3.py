#!/usr/bin/env python3
"""Apply T3 rewrite proposals to the live skills tree.

Two proposal conventions:
  --mode replace  : proposal dir IS the complete final skill (full-dir authors).
                    Live dir is replaced wholesale (old dir preserved in git history).
  --mode overlay  : proposal contains only changed/added files; they are copied over
                    the live dir; paths listed in the proposal's DELETIONS.txt are
                    removed from the live dir.

Only skills named on the command line are touched (explicit approval per batch).
Updates each ledger (stages.rewrite applied, sha_after) and appends IMPROVEMENTS.md rows.
Dry-run by default; --apply writes.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skills", nargs="+")
    ap.add_argument("--mode", choices=["replace", "overlay"], required=True)
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--run-dir", default=os.path.expanduser("~/.claude/skill-revamp-runs/current"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    props = os.path.join(args.run_dir, "proposals")
    led_dir = os.path.join(args.run_dir, "ledger")
    imp = os.path.join(args.run_dir, "IMPROVEMENTS.md")

    for skill in args.skills:
        prop = os.path.join(props, skill)
        live = os.path.realpath(os.path.join(args.root, skill))
        if not os.path.isfile(os.path.join(prop, "SKILL.md")):
            print(f"SKIP {skill}: no proposal SKILL.md")
            continue
        if not os.path.isdir(live):
            print(f"SKIP {skill}: no live dir")
            continue

        if not args.apply:
            n = sum(len(fs) for _, _, fs in os.walk(prop))
            print(f"WOULD APPLY [{args.mode}] {skill}: {n} proposal files -> {live}")
            continue

        if args.mode == "replace":
            shutil.rmtree(live)
            shutil.copytree(prop, live, symlinks=True,
                            ignore=shutil.ignore_patterns("RATIONALE.md", "DELETIONS.txt"))
        else:
            for dirpath, _, files in os.walk(prop):
                rel = os.path.relpath(dirpath, prop)
                for f in files:
                    if f in ("RATIONALE.md", "DELETIONS.txt"):
                        continue
                    dst_dir = os.path.join(live, rel) if rel != "." else live
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(os.path.join(dirpath, f), os.path.join(dst_dir, f))
            delf = os.path.join(prop, "DELETIONS.txt")
            if os.path.isfile(delf):
                for line in open(delf):
                    p = os.path.join(live, line.strip())
                    if line.strip() and os.path.isfile(p):
                        os.remove(p)

        lp = os.path.join(led_dir, skill + ".json")
        if os.path.exists(lp):
            d = json.load(open(lp))
            sha = subprocess.run(["git", "hash-object", os.path.join(live, "SKILL.md")],
                                 capture_output=True, text=True).stdout.strip()
            d["sha_after"] = sha
            d.setdefault("stages", {})["rewrite"] = {"status": "applied", "lane": f"T3-{args.mode}"}
            d.setdefault("stages", {})["review"] = {"status": "approved", "reviewer": "codex-cross-review+fable"}
            tmp = lp + ".tmp"
            json.dump(d, open(tmp, "w"), indent=1)
            os.replace(tmp, lp)
        if os.path.exists(imp):
            with open(imp, "a") as f:
                f.write(f"| {skill} | T3 | full rewrite ({args.mode}) | - | - |\n")
        print(f"APPLIED [{args.mode}] {skill}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
