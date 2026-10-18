"""Smoke test: Groq key + model list, LM Studio models, and one real call to each LLM."""
import json
import os
import time
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI

from src.llm import LLMClient

load_dotenv()
key = os.getenv("GROQ_API_KEY")
print("GROQ_API_KEY set:", bool(key), "| length:", len(key or ""), "| starts gsk_:", (key or "").startswith("gsk_"))

req = urllib.request.Request(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {key}", "User-Agent": "supportrag/0.1"},
)
try:
    ids = sorted(m["id"] for m in json.load(urllib.request.urlopen(req, timeout=20))["data"])
    print("Groq models available to this key:")
    for i in ids:
        print("  ", i)
except Exception as e:
    ids = []
    print("Groq models call failed:", type(e).__name__, e)

client = LLMClient()
print("configured Groq model present:", client.cfg["groq"]["model"] in ids)

lm = json.load(urllib.request.urlopen("http://localhost:1234/api/v0/models", timeout=10))["data"]
print("LM Studio models:")
for m in lm:
    print("  ", m["id"], "|", m["state"], "|", m.get("quantization"))

msg = [{"role": "user", "content": "Reply with exactly one word: pong"}]
t = time.time()
print("local call:", client.chat(msg), f"{time.time() - t:.1f}s")

groq = OpenAI(base_url=client.cfg["groq"]["base_url"], api_key=key, max_retries=0, timeout=30)
t = time.time()
try:
    out = client._call(groq, client.cfg["groq"]["model"], msg, max_tokens=200)
    print("groq direct call:", repr(out), f"{time.time() - t:.1f}s")
except Exception as e:
    print("groq direct call failed:", type(e).__name__, e)
