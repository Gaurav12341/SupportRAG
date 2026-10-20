import argparse
import json
import time

from . import run

ap = argparse.ArgumentParser()
ap.add_argument("--recreate", action="store_true",
                help="drop the collection and rebuild it (use after changing the embedding model)")
ap.add_argument("--prune", action="store_true", help="delete points whose chunk no longer exists")
ap.add_argument("--chunks", default="chunks.jsonl", help="chunks file in the processed folder (experiments)")
ap.add_argument("--collection", help="Qdrant collection (default: qdrant.collection in config.yaml)")
ap.add_argument("--embedding", help="embedding model (default: models.embedding in config.yaml)")
ap.add_argument("--device", help="device for the embedding model, e.g. cuda (default: models.device)")
a = ap.parse_args()
t0 = time.perf_counter()
stats = run(a.recreate, a.prune, a.chunks, a.collection, a.embedding, a.device)
stats["seconds"] = round(time.perf_counter() - t0, 1)
print(json.dumps(stats, indent=2))
