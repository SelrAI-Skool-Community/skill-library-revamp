#!/usr/bin/env python3
"""Verify and apply T2 description-only proposals.

Contract enforced per proposal (proposals/<skill>/SKILL.md):
  - body (everything after the closing frontmatter ---) byte-identical to live skill
  - every frontmatter key except `description` byte-identical (order preserved)
  - new description: single-line flat string, 1..500 chars
Violations are reported and skipped; nothing partial is ever written.

--dry-run (default) prints per-skill verdicts + summary.
--apply writes conforming proposals over the live SKILL.md, updates the ledger
(stages.rewrite applied, sha_after) and appends a row to IMPROVEMENTS.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys

FM_RE = re.compile(r"^(---\n)(.*?)(\n---\n)(.*)$", re.S)


def split_doc(text):
    m = FM_RE.match(text)
    if not m:
        return None
    return m.group(2), m.group(4)  # frontmatter body, doc body


def fm_lines_excluding_description(fm):
    out, in_desc = [], False
    for line in fm.splitlines():
        if re.match(r"^description\s*:", line):
            in_desc = True
            continue
        if in_desc and line.startswith((" ", "\t")) and line.strip():
            continue  # multiline description continuation
        in_desc = False
        out.append(line)
    return out


def get_description(fm):
    m = re.search(r"^description\s*:\s*(.*)$", fm, re.M)
    if not m:
        return None
    desc = m.group(1).strip().strip('"').strip("'")
    idx = fm.splitlines().index(next(l for l in fm.splitlines() if re.match(r"^description\s*:", l)))
    for line in fm.splitlines()[idx + 1:]:
        if line.startswith((" ", "\t")) and line.strip():
            desc += " " + line.strip()
        else:
            break
    return " ".join(desc.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--run-dir", default=os.path.expanduser("~/.claude/skill-revamp-runs/current"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    props = os.path.join(args.run_dir, "proposals")
    led_dir = os.path.join(args.run_dir, "ledger")
    ok, bad = [], []
    for skill in sorted(os.listdir(props)):
        prop_path = os.path.join(props, skill, "SKILL.md")
        live_path = os.path.join(args.root, skill, "SKILL.md")
        if not os.path.isfile(prop_path):
            continue
        if not os.path.isfile(live_path):
            bad.append((skill, "live SKILL.md missing"))
            continue
        live = open(live_path, encoding="utf-8").read()
        prop = open(prop_path, encoding="utf-8").read()
        ls, ps = split_doc(live), split_doc(prop)
        if ls is None or ps is None:
            bad.append((skill, "frontmatter parse failure"))
            continue
        if ls[1] != ps[1]:
            bad.append((skill, "body changed"))
            continue
        if fm_lines_excluding_description(ls[0]) != fm_lines_excluding_description(ps[0]):
            bad.append((skill, "non-description frontmatter changed"))
            continue
        new_desc = get_description(ps[0])
        old_desc = get_description(ls[0])
        if not new_desc:
            bad.append((skill, "no description in proposal"))
            continue
        if len(new_desc) > 500:
            bad.append((skill, f"description {len(new_desc)} chars > 500"))
            continue
        if new_desc == old_desc:
            bad.append((skill, "description unchanged"))
            continue
        ok.append((skill, old_desc, new_desc, prop))

    print(f"conforming: {len(ok)}  rejected: {len(bad)}")
    for s, why in bad:
        print(f"  REJECT {s}: {why}")

    if not args.apply:
        return 0

    imp = os.path.join(args.run_dir, "IMPROVEMENTS.md")
    if not os.path.exists(imp):
        with open(imp, "w") as f:
            f.write("# Revamp improvements ledger\n\n| skill | tier | what changed | desc before (chars) | desc after (chars) |\n|---|---|---|---|---|\n")
    applied = 0
    for skill, old_desc, new_desc, prop in ok:
        live_path = os.path.join(args.root, skill, "SKILL.md")
        with open(live_path, "w", encoding="utf-8") as f:
            f.write(prop)
        lp = os.path.join(led_dir, skill + ".json")
        if os.path.exists(lp):
            d = json.load(open(lp))
            sha = subprocess.run(["git", "hash-object", live_path], capture_output=True, text=True).stdout.strip()
            d["sha_after"] = sha
            d.setdefault("stages", {})["rewrite"] = {"status": "applied", "lane": "T2-desc"}
            tmp = lp + ".tmp"
            json.dump(d, open(tmp, "w"), indent=1)
            os.replace(tmp, lp)
        with open(imp, "a") as f:
            f.write(f"| {skill} | T2 | description rewrite | {len(old_desc or '')} | {len(new_desc)} |\n")
        applied += 1
    print(f"applied: {applied}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
