#!/usr/bin/env python3
"""Runs the tech-lead:prose-judge agent on a PR title and body, and records a pass that pr-prose-gate.py requires.

Usage: prose-check.py [--title TITLE] [--body-file PATH] [--approve]
--approve records the text as passing without the judge. It is for the owner, typed as `! <plugin>/bin/prose-check.py --approve ...`. pr-prose-gate.py refuses it from agents.
Pass the exact text you will send to gh. Exit 0 on PASS, 1 on REWRITE (the judge's reasons and rewrite are printed).
"""
import argparse
import hashlib
import pathlib
import shlex
import subprocess
import sys

import os  # noqa: E402

MARKS = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude") / "tech-lead" / "state" / "prose"


def digest(kind, text):
    return hashlib.sha256(f"{kind}\0{text.strip()}".encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title")
    ap.add_argument("--body-file")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    if a.title is None and a.body_file is None:
        ap.error("give --title, --body-file or both")
    body = pathlib.Path(a.body_file).read_text() if a.body_file else None
    if a.approve:
        MARKS.mkdir(parents=True, exist_ok=True)
        mark(a.title, body)
        print("Approved. The gate now allows this exact text.")
        return 0
    parts = []
    if a.title is not None:
        parts.append(f"TITLE:\n{a.title}")
    if body is not None:
        parts.append(f"BODY:\n{body}")
    prompt = "Judge this PR text.\n\n" + "\n\n".join(parts)
    out = subprocess.run(
        ["claude", "-p", "--agent", "tech-lead:prose-judge", "--model", "sonnet", prompt],
        capture_output=True, text=True, timeout=300,
    )
    verdict = out.stdout.strip()
    if out.returncode != 0 or not verdict:
        print(f"prose-check: the judge did not run ({out.stderr.strip()[:300]})", file=sys.stderr)
        return 2
    print(verdict)
    MARKS.mkdir(parents=True, exist_ok=True)
    if verdict.splitlines()[0].strip() == "PASS":
        mark(a.title, body)
        return 0
    title, body = rewrite(verdict, a.title, body)
    if title is None and body is None:
        print("prose-check: the judge gave no TITLE/BODY rewrite. Fix the listed problems and run again.", file=sys.stderr)
        return 1
    mark(title, body)
    if body is not None and a.body_file:
        out = pathlib.Path(a.body_file + ".rewrite")
        out.write_text(body.strip() + "\n")
        print(f"\nThe judge's rewrite is recorded as passing. Use it verbatim: --title {shlex.quote(title or '')} --body-file {out}", file=sys.stderr)
    else:
        print(f"\nThe judge's rewrite is recorded as passing. Use it verbatim: --title {shlex.quote(title or '')}", file=sys.stderr)
    return 1


def mark(title, body):
    if title is not None:
        (MARKS / digest("title", title)).touch()
    if body is not None:
        (MARKS / digest("body", body)).touch()


def rewrite(verdict, had_title, had_body):
    """The judge's TITLE:/BODY: block, limited to the parts that were judged."""
    lines = verdict.splitlines()
    title = body = None
    for i, line in enumerate(lines):
        if line.startswith("TITLE:"):
            title = line[len("TITLE:"):].strip().strip("`")
        elif line.strip() == "BODY:":
            body = "\n".join(l for l in lines[i + 1:] if l.strip() != "```").strip()
            break
    return (title if had_title is not None else None), (body if had_body is not None else None)


if __name__ == "__main__":
    sys.exit(main())
