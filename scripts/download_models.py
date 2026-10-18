"""Pre-download the local models from Hugging Face and print their on-disk sizes."""
from huggingface_hub import snapshot_download

from src.llm import load_config

# Skip duplicate weight formats so we only pull what sentence-transformers needs.
IGNORE = ["*.onnx", "*.msgpack", "*.h5", "onnx/*", "openvino/*", "*.ot"]


def main() -> None:
    for role, name in load_config()["models"].items():
        if role == "device":
            continue
        path = snapshot_download(name, ignore_patterns=IGNORE)
        size = sum(f.stat().st_size for f in __import__("pathlib").Path(path).rglob("*") if f.is_file())
        print(f"{role}: {name} -> {size / 1e6:.0f} MB ({path})")


if __name__ == "__main__":
    main()
