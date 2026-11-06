import asyncio

from object_hash import calculate_objectid
from object_store import ObjectStore

test_obj = {
    "type": "transaction",
    "height": 0,
    "outputs": [
        {
            "pubkey": "85acb336a150b16a9c6c8c27a4e9c479d9f99060a7945df0bb1b53365e98969b",
            "value": 50000000000000
        }
    ]
}

store = ObjectStore()

obj = {
    "type": "transaction",
    "height": 0,
    "outputs": []
}

objectid = store.add_object(obj)
store.save()

new_store = ObjectStore("test_objects.json")
new_store.load()

print(calculate_objectid(test_obj))
print(store.has_object(objectid))
print(store.get_object(objectid))
print(store.has_object("unknown"))

new_store = ObjectStore("objects.json")
new_store.load()

print(new_store.has_object(objectid))
print(new_store.get_object(objectid))

async def test_concurrent():
    store = ObjectStore("test_objects.json")

    objects = [
        {"type": "transaction", "height": i, "outputs": []}
        for i in range(10)
    ]

    await asyncio.gather(
        *(store.add_and_save(obj) for obj in objects)
    )

    new_store = ObjectStore("test_objects.json")
    new_store.load()

    print("Gespeicherte Objekte:", len(new_store.objects))

asyncio.run(test_concurrent())

store = ObjectStore("test_invalid_objects.json")
store.load()

print(store.objects)