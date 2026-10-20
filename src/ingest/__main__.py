import argparse

from . import print_summary, run

ap = argparse.ArgumentParser()
ap.add_argument("--strategy", choices=["fixed", "headings", "recursive"], help="override chunking.strategy")
ap.add_argument("--size", type=int, help="override chunking.size_tokens")
ap.add_argument("--overlap", type=int, help="override chunking.overlap_tokens")
ap.add_argument("--out", help="write only this chunks file (in the processed folder) instead of replacing chunks.jsonl")
a = ap.parse_args()
print_summary(run(a.strategy, a.size, a.overlap, a.out))
