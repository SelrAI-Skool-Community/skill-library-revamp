#!/usr/bin/env python3
"""Find likely overlapping skills with stdlib TF-IDF cosine similarity."""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, save, stage_done
from scan_frontmatter import parse_frontmatter


THRESHOLD = 0.55
TOKENS = re.compile(r"[a-z0-9]+")
H2 = re.compile(r"^##\s+(.+?)\s*$", flags=re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.home() / ".claude/skills"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path.home() / ".claude/skill-revamp-runs/current",
    )
    return parser.parse_args()


def corpus_for(obj: dict) -> list[str]:
    skill_md = Path(obj["path"]) / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"SKILL.md missing for {obj['skill']}: {skill_md}")
    text = skill_md.read_text(encoding="utf-8")
    _, values = parse_frontmatter(text)
    corpus = " ".join(
        [
            values.get("name", obj["skill"]),
            values.get("description", ""),
            *H2.findall(text),
        ]
    )
    return TOKENS.findall(corpus.lower())


def tfidf_vectors(corpora: list[list[str]]) -> list[dict[str, float]]:
    document_count = len(corpora)
    document_frequency: Counter[str] = Counter()
    for tokens in corpora:
        document_frequency.update(set(tokens))

    vectors: list[dict[str, float]] = []
    for tokens in corpora:
        counts = Counter(tokens)
        total = sum(counts.values())
        vector: dict[str, float] = {}
        if total:
            for token, count in counts.items():
                tf = count / total
                idf = math.log((1 + document_count) / (1 + document_frequency[token])) + 1
                vector[token] = tf * idf
        vectors.append(vector)
    return vectors


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def markdown(pairs: list[tuple[str, str, float]]) -> str:
    lines = [
        "# Skill overlap candidates",
        "",
        "| Skill A | Skill B | Cosine |",
        "|---|---|---:|",
    ]
    lines.extend(
        f"| {left.replace('|', '\\|')} | {right.replace('|', '\\|')} | {score:.4f} |"
        for left, right, score in pairs
    )
    if not pairs:
        lines.extend(["", "No pairs met the 0.55 cosine threshold."])
    return "\n".join(lines) + "\n"


def run(root: Path, run_dir: Path) -> tuple[int, int]:
    del root
    ledgers = list(all_skills(run_dir))
    corpora = [corpus_for(obj) for obj in ledgers]
    vectors = tfidf_vectors(corpora)
    by_name = {obj["skill"]: obj for obj in ledgers}
    for obj in ledgers:
        obj.setdefault("flags", {})["overlap_candidates"] = []

    pairs: list[tuple[str, str, float]] = []
    for left_index, left in enumerate(ledgers):
        for right_index in range(left_index + 1, len(ledgers)):
            right = ledgers[right_index]
            score = cosine(vectors[left_index], vectors[right_index])
            if score < THRESHOLD:
                continue
            rounded = round(score, 4)
            pairs.append((left["skill"], right["skill"], rounded))
            by_name[left["skill"]]["flags"]["overlap_candidates"].append(
                {"peer": right["skill"], "cos": rounded}
            )
            by_name[right["skill"]]["flags"]["overlap_candidates"].append(
                {"peer": left["skill"], "cos": rounded}
            )

    pairs.sort(key=lambda item: (-item[2], item[0], item[1]))
    for obj in ledgers:
        obj["flags"]["overlap_candidates"].sort(
            key=lambda item: (-item["cos"], item["peer"])
        )
        stage_done(obj, "overlap_candidates")
        save(run_dir, obj["skill"], obj)
    atomic_write_text(run_dir / "OVERLAPS.md", markdown(pairs))
    return len(ledgers), len(pairs)


def main() -> int:
    args = parse_args()
    try:
        skills, pairs = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR overlap_candidates: {exc}", file=sys.stderr)
        return 1
    print(f"overlap_candidates: scanned={skills} pairs={pairs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
