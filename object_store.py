import asyncio
import object_hash
import json
import os
import tempfile
from pathlib import Path

class ObjectStore:
    def __init__(self, file_path="objects.json"):
        self.file_path = file_path
        self.objects = {}
        self.lock = asyncio.Lock()

    def has_object(self, objectid):
        return objectid in self.objects

    def get_object(self, objectid):
        return self.objects.get(objectid)

    def add_object(self, obj):
        objectid = object_hash.calculate_objectid(obj)
        self.objects[objectid] = obj
        return objectid

    async def add_and_save(self, obj):
        async with self.lock:
            objectid = self.add_object(obj)
            await asyncio.to_thread(self.save)
            return objectid

    def save(self):
        path = Path(self.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
                temp_path = file.name
                json.dump(self.objects, file)
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
