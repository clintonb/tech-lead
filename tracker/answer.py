#!/usr/bin/env python3
"""Record the answer to a question the owner asked a lead: answer.py <lead-dir> <qN> "<answer>" | --pending "<who is finding out>" | --drop"""
import argparse
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "hooks"))
import lead_lib  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("id", nargs="?")
ap.add_argument("answer", nargs="?")
ap.add_argument("--pending")
ap.add_argument("--drop", action="store_true")
ap.add_argument("--list", action="store_true", help="print the questions that still need an answer")
a = ap.parse_args()
qs = lead_lib.load_questions(a.dir)
if a.list:
    for q in qs:
        if q["status"] in ("open", "pending"):
            print(f"{q['id']} [{q['status']}] {q['text']}" + (f" (pending: {q['pending']})" if q.get("pending") else ""))
    sys.exit(0)
q = next((q for q in qs if q["id"] == a.id), None)
if not q:
    sys.exit(f"no question {a.id} in {a.dir}/questions.json")
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
if a.drop:
    q.update(status="dropped", answeredAt=now)
elif a.pending:
    q.update(status="pending", pending=a.pending)
elif a.answer:
    q.update(status="answered", answer=a.answer, answeredAt=now)
else:
    sys.exit("give an answer, --pending or --drop")
lead_lib.save_questions(a.dir, qs)
print(f"{q['id']} is {q['status']}.")
