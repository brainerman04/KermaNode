import asyncio
import object_hash
import json
import os
import tempfile
from pathlib import Path
from config import GEN_BLOCK_ID
from copy import deepcopy

class ObjectStore:
    def __init__(self, file_path="objects.json"):
        self.file_path = file_path
        self.objects = {}
        self.lock = asyncio.Lock()
        self.utxo_sets = {GEN_BLOCK_ID: {}}

    def has_object(self, objectid):
        return objectid in self.objects

    def get_object(self, objectid):
        return self.objects.get(objectid)

    def get_utxo(self, blockid):
        return deepcopy(self.utxo_sets.get(blockid))

    def set_utxo(self, blockid, utxo):
        self.utxo_sets[blockid] = deepcopy(utxo)

    def serialize_utxo_sets(self, snapshot = None):
        result = {}
        utxo_sets = self.utxo_sets if snapshot is None else snapshot

        for blockid, utxo in utxo_sets.items():
            result[blockid] = []

            for (txid, index), output in utxo.items():
                result[blockid].append({
                    "txid": txid,
                    "index": index,
                    "output": output
                })
        return result

    def deserialize_utxo_sets(self, data):
        result = {GEN_BLOCK_ID: {}}

        for blockid, entries in data.items():
            result[blockid] = {}

            for entry in entries:
                key = (entry["txid"], entry["index"])
                result[blockid][key] = entry["output"]

        return result

    def add_object(self, obj):
        objectid = object_hash.calculate_objectid(obj)
        self.objects[objectid] = obj
        return objectid

    async def add_and_save(self, obj):
        async with self.lock:
            objectid = self.add_object(obj)
            await asyncio.to_thread(self.save)
            return objectid

    async def add_and_save_if_new(self, obj) -> bool:
        """Atomically deduplicate concurrent receipts; publish only after saving."""
        objectid = object_hash.calculate_objectid(obj)
        async with self.lock:
            if objectid in self.objects:
                return False
            # Persist a snapshot first so failed writes never expose a new object.
            snapshot = dict(self.objects)
            snapshot[objectid] = obj
            await asyncio.to_thread(self.save, snapshot)
            self.objects[objectid] = obj
            return True

    async def add_validated_block(self, block, utxo):
        blockid = object_hash.calculate_objectid(block)

        async with self.lock:
            object_snapshot = dict(self.objects)
            object_snapshot[blockid] = block

            utxo_snapshot = deepcopy(self.utxo_sets)
            utxo_snapshot[blockid] = deepcopy(utxo)

            await asyncio.to_thread(
                self.save,
                object_snapshot,
                utxo_snapshot
            )

            self.objects = object_snapshot
            self.utxo_sets = utxo_snapshot

            return blockid

    def save(self, snapshot=None, utxo_snapshot = None):
        path = Path(self.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
                temp_path = file.name
                data = {
                    "objects": self.objects if snapshot is None else snapshot,
                    "utxo_sets": self.serialize_utxo_sets(utxo_snapshot)
                }
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_path, path)
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                os.remove(temp_path)

    def load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                raise ValueError("Invalid object database")

            if "objects" in data and "utxo_sets" in data:
                self.utxo_sets = self.deserialize_utxo_sets(
                    data["utxo_sets"]
                )
                data = data["objects"]
            else:
                self.utxo_sets = {GEN_BLOCK_ID: {}}

            valid_objects = {}

            for objectid, obj in data.items():
                if not isinstance(obj, dict):
                    continue

                if object_hash.calculate_objectid(obj) != objectid:
                    continue

                valid_objects[objectid] = obj

            self.objects = valid_objects

        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            self.objects = {}
            self.utxo_sets = {GEN_BLOCK_ID: {}}
