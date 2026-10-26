import hashlib
import random


def stable_seed(seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def rng_for(seed: int, namespace: str) -> random.Random:
    return random.Random(stable_seed(seed, namespace))