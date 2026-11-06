import json
import hashlib

def calculate_objectid(obj):
    canonical_json = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    canonical_json = canonical_json.encode("utf-8")
    hash_hex = hashlib.blake2s(canonical_json).hexdigest()
    return hash_hex