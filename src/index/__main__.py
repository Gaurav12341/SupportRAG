import argparse
import json

from . import run

ap = argparse.ArgumentParser()
ap.add_argument("--recreate", action="store_true",
                help="drop the collection and rebuild it (use after changing the embedding model)")
ap.add_argument("--prune", action="store_true", help="delete points whose chunk no longer exists")
a = ap.parse_args()
print(json.dumps(run(a.recreate, a.prune), indent=2))
