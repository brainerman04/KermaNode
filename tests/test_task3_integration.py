"""Real TCP integration tests; put into your repo's tests/ directory.

Run: python -m unittest discover -s tests -p 'test_task3_integration.py' -v
This uses ephemeral local sockets and a temporary object database, not Docker.
"""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

import network
from config import GEN_BLOCK_ID
from genesis import GENESIS_BLOCK
from object_hash import calculate_objectid
from object_store import ObjectStore
from peer_manager import PeerManager

COINBASE = {
    "type": "transaction", "height": 1,
    "outputs": [{
        "pubkey": "3f0bc71a375b574e4bda3ddf502fe1afd99aa020bf6049adfe525d9ad18ff33f",
        "value": 50000000000000,
    }],
}
BLOCK = {
    "type": "block",
    "T": "0000abc000000000000000000000000000000000000000000000000000000000",
    "created": 1671148800,
    "miner": "grader",
    "nonce": "0" * 59 + "463cf",
    "note": "This block has a coinbase transaction",
    "previd": GEN_BLOCK_ID,
    "txids": ["6ebfb4c8e8e9b19dcf54c6ce3e1e143da1f473ea986e70c5cb8899a4671c933a"],
}
COINBASE_ID = BLOCK["txids"][0]
BLOCK_ID = "000020cb0002575a71955763adf365c78182f0bb5bee767794ebc7346e0a2194"


class Task3IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ObjectStore(Path(self.tmp.name) / "objects.json")
        self.store.add_object(GENESIS_BLOCK)
        self.manager = PeerManager(Path(self.tmp.name) / "peers.json")
        self.clients = []
        self.tasks = set()
        self.errors = []
        network.peers.clear()
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.assertEqual(calculate_objectid(GENESIS_BLOCK), GEN_BLOCK_ID)
        self.assertEqual(calculate_objectid(COINBASE), COINBASE_ID)
        self.assertEqual(calculate_objectid(BLOCK), BLOCK_ID)

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            await network.handle_incoming(reader, writer, self.manager, self.store)
        except Exception as exc:
            self.errors.append(exc)
        finally:
            self.tasks.discard(task)

    async def asyncTearDown(self):
        for reader, writer in self.clients:
            writer.close()
            await writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
        proc = getattr(self.store, "block_processor", None)
        if proc:
            await proc.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        network.peers.clear()
        self.tmp.cleanup()
        self.assertEqual(self.errors, [])

    async def _receive(self, client, timeout=3):
        line = await asyncio.wait_for(client[0].readline(), timeout)
        return json.loads(line) if line else None

    async def _send(self, client, message):
        client[1].write((json.dumps(message) + "\n").encode("utf-8"))
        await client[1].drain()

    async def _connect(self):
        client = await asyncio.open_connection("127.0.0.1", self.port)
        self.clients.append(client)
        self.assertEqual((await self._receive(client))["type"], "hello")
        self.assertEqual((await self._receive(client))["type"], "getpeers")
        await self._send(client, {"type": "hello", "version": "0.10.0", "agent": "E2E"})
        await self._send(client, {"type": "getpeers"})
        self.assertEqual((await self._receive(client))["type"], "peers")
        return client

    async def _expect(self, client, kind, *, objectid=None, error=None, timeout=7):
        deadline = asyncio.get_running_loop().time() + timeout
        seen = []
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.fail(f"No {kind} (id={objectid}, error={error}); received {seen}")
            msg = await self._receive(client, timeout=remaining)
            if msg is None:
                self.fail(f"Connection closed before {kind}; received {seen}")
            seen.append(msg)
            if msg.get("type") != kind:
                continue
            if objectid is not None and msg.get("objectid") != objectid:
                continue
            if error is not None and msg.get("name") != error:
                continue
            return msg

    async def test_01_valid_coinbase_and_block_gossip_and_utxo(self):
        a, b = await self._connect(), await self._connect()
        await self._send(a, {"type": "object", "object": COINBASE})
        for client in (a, b):
            await self._expect(client, "ihaveobject", objectid=COINBASE_ID)
        await self._send(a, {"type": "object", "object": BLOCK})
        for client in (a, b):
            await self._expect(client, "ihaveobject", objectid=BLOCK_ID)
        await self._send(b, {"type": "getobject", "objectid": BLOCK_ID})
        self.assertEqual((await self._expect(b, "object"))["object"], BLOCK)
        self.assertEqual(self.store.get_utxo(BLOCK_ID), {
            (COINBASE_ID, 0): COINBASE["outputs"][0]
        })

    async def test_02_pending_block_requests_transaction_and_finishes(self):
        a, b = await self._connect(), await self._connect()
        await self._send(a, {"type": "object", "object": BLOCK})
        await self._expect(a, "getobject", objectid=COINBASE_ID)
        await self._expect(b, "getobject", objectid=COINBASE_ID)
        await self._send(a, {"type": "object", "object": COINBASE})
        for client in (a, b):
            await self._expect(client, "ihaveobject", objectid=COINBASE_ID)
            await self._expect(client, "ihaveobject", objectid=BLOCK_ID)
        self.assertTrue(self.store.has_object(BLOCK_ID))

    async def test_03_invalid_pow_is_rejected_without_store(self):
        a, b = await self._connect(), await self._connect()
        wrong = copy.deepcopy(BLOCK)
        wrong["nonce"] = "0" * 64
        await self._send(a, {"type": "object", "object": wrong})
        error = await self._expect(a, "error", error="INVALID_BLOCK_POW")
        self.assertEqual(error["name"], "INVALID_BLOCK_POW")
        self.assertFalse(self.store.has_object(calculate_objectid(wrong)))
        await self._send(b, {"type": "getpeers"})
        self.assertEqual((await self._expect(b, "peers"))["type"], "peers")

    async def test_04_missing_transaction_times_out_without_disconnecting(self):
        a = await self._connect()
        await self._send(a, {"type": "object", "object": BLOCK})
        await self._expect(a, "getobject", objectid=COINBASE_ID)
        await self._expect(a, "error", error="UNFINDABLE_OBJECT", timeout=7)
        await self._send(a, {"type": "getpeers"})
        await self._expect(a, "peers")
        self.assertFalse(self.store.has_object(BLOCK_ID))


if __name__ == "__main__":
    unittest.main()
