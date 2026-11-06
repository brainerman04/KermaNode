
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from object_store import ObjectStore
from object_hash import calculate_objectid


class TestObjectStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "objects.json"
        self.store = ObjectStore(self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_object_hash(self):
        obj = {
            "type": "transaction",
            "height": 0,
            "outputs": [
                {
                    "pubkey": "85acb336a150b16a9c6c8c27a4e9c479d9f99060a7945df0bb1b53365e98969b",
                    "value": 50000000000000
                }
            ]
        }

        expected = "d46d09138f0251edc32e28f1a744cb0b7286850e4c9c777d7e3c6e459b289347"

        self.assertEqual(calculate_objectid(obj), expected)

    def test_canonical_json(self):
        obj1 = {"type": "transaction", "height": 0, "outputs": []}
        obj2 = {"outputs": [], "height": 0, "type": "transaction"}

        self.assertEqual(
            calculate_objectid(obj1),
            calculate_objectid(obj2)
        )

    def test_add_object(self):
        obj = {"type": "transaction", "height": 0, "outputs": []}

        objectid = self.store.add_object(obj)

        self.assertTrue(self.store.has_object(objectid))
        self.assertEqual(self.store.get_object(objectid), obj)

    def test_unknown_object(self):
        self.assertFalse(self.store.has_object("unknown"))
        self.assertIsNone(self.store.get_object("unknown"))

    def test_duplicate_object(self):
        obj = {"type": "transaction", "height": 0, "outputs": []}

        id1 = self.store.add_object(obj)
        id2 = self.store.add_object(obj)

        self.assertEqual(id1, id2)
        self.assertEqual(len(self.store.objects), 1)

    def test_save_and_load(self):
        obj = {"type": "transaction", "height": 0, "outputs": []}

        objectid = self.store.add_object(obj)
        self.store.save()

        new_store = ObjectStore(self.file_path)
        new_store.load()

        self.assertTrue(new_store.has_object(objectid))
        self.assertEqual(new_store.get_object(objectid), obj)

    def test_missing_file(self):
        self.store.load()

        self.assertEqual(self.store.objects, {})

    def test_corrupted_json(self):
        self.file_path.write_text(
            "{invalid json",
            encoding="utf-8"
        )

        self.store.load()

        self.assertEqual(self.store.objects, {})

    def test_invalid_database_format(self):
        self.file_path.write_text(
            '["object1", "object2"]',
            encoding="utf-8"
        )

        self.store.load()

        self.assertEqual(self.store.objects, {})

    def test_invalid_object_id(self):
        obj = {"type": "transaction", "height": 0, "outputs": []}
        correct_id = calculate_objectid(obj)

        data = {
            correct_id: obj,
            "invalid_id": obj
        }

        self.file_path.write_text(
            json.dumps(data),
            encoding="utf-8"
        )

        self.store.load()

        self.assertEqual(len(self.store.objects), 1)
        self.assertTrue(self.store.has_object(correct_id))
        self.assertFalse(self.store.has_object("invalid_id"))

    def test_concurrent_updates(self):
        async def run_test():
            objects = [
                {"type": "transaction", "height": i, "outputs": []}
                for i in range(10)
            ]

            await asyncio.gather(
                *(self.store.add_and_save(obj) for obj in objects)
            )

            new_store = ObjectStore(self.file_path)
            new_store.load()

            self.assertEqual(len(new_store.objects), 10)

            for obj in objects:
                objectid = calculate_objectid(obj)
                self.assertTrue(new_store.has_object(objectid))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
