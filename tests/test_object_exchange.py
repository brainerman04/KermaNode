import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import network
from config import errorType
from object_hash import calculate_objectid
from object_store import ObjectStore
from peer_manager import PeerManager
from protocol import ObjectValidationError, validate_message, object_exchange_format_error


class ExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ObjectStore(Path(self.temp.name) / "objects.json")
        self.manager = PeerManager(Path(self.temp.name) / "peers.json")
        self.tasks = set()
        self.clients = []
        self.errors = []
        # Only the exchange is under test; this is NOT a transaction validator.
        self.validator = Mock(return_value=None)
        self.patch = patch("network.validate_object", self.validator)
        self.patch.start()
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.obj = {"type": "transaction", "height": 0, "outputs": []}
        self.oid = calculate_objectid(self.obj)

    async def accept(self, reader, writer):
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
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        network.peers.clear()
        self.patch.stop()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    async def receive(self, client):
        line = await asyncio.wait_for(client[0].readline(), 2)
        return json.loads(line) if line else None

    async def send(self, client, msg):
        client[1].write((json.dumps(msg) + "\n").encode())
        await client[1].drain()

    async def connect(self, handshake=True):
        client = await asyncio.open_connection("127.0.0.1", self.port)
        self.clients.append(client)
        self.assertEqual((await self.receive(client))["type"], "hello")
        self.assertEqual((await self.receive(client))["type"], "getpeers")
        if handshake:
            await self.send(client, {"type":"hello", "version":"0.10.0", "agent":"Test"})
            # A response acts as a barrier: the server processed the handshake.
            await self.send(client, {"type":"getpeers"})
            self.assertEqual((await self.receive(client))["type"], "peers")
        return client

    async def barrier(self, client):
        await self.send(client, {"type":"getpeers"})
        self.assertEqual((await self.receive(client))["type"], "peers")

    async def test_two_peers_exchange_dedup_and_reload(self):
        a, b = await self.connect(), await self.connect()
        await self.send(a, {"type":"ihaveobject", "objectid":self.oid})
        self.assertEqual(await self.receive(a), {"type":"getobject", "objectid":self.oid})
        await self.send(a, {"type":"object", "object":self.obj})
        for client in (a, b):
            self.assertEqual(await self.receive(client), {"type":"ihaveobject", "objectid":self.oid})
            await self.send(client, {"type":"getobject", "objectid":self.oid})
            self.assertEqual(await self.receive(client), {"type":"object", "object":self.obj})
        await self.send(a, {"type":"object", "object":self.obj})
        await self.send(a, {"type":"ihaveobject", "objectid":self.oid})
        await self.barrier(a)
        await self.barrier(b)
        self.validator.assert_called_once()
        self.store = ObjectStore(self.store.file_path)
        self.store.load()
        c = await self.connect()
        await self.send(c, {"type":"getobject", "objectid":self.oid})
        self.assertEqual((await self.receive(c))["object"], self.obj)

    async def test_unknown_lookup_and_dependency_keep_connection(self):
        a = await self.connect()
        await self.send(a, {"type":"getobject", "objectid":self.oid})
        self.assertEqual((await self.receive(a))["name"], "UNKNOWN_OBJECT")
        await self.barrier(a)
        self.validator.side_effect = ObjectValidationError(errorType.UNKNOWN_OBJ, "Missing input transaction.")
        await self.send(a, {"type":"object", "object":self.obj})
        self.assertEqual((await self.receive(a))["msg"], "Missing input transaction.")
        await self.barrier(a)
        self.assertFalse(self.store.has_object(self.oid))

    async def test_invalid_transaction_disconnects_without_gossip(self):
        a, b = await self.connect(), await self.connect()
        self.validator.side_effect = ObjectValidationError(errorType.INV_TX_SIG, "Invalid input signature.")
        await self.send(a, {"type":"object", "object":self.obj})
        self.assertEqual((await self.receive(a))["name"], "INVALID_TX_SIGNATURE")
        self.assertIsNone(await self.receive(a))
        await self.barrier(b)
        self.assertFalse(self.store.has_object(self.oid))

    async def test_missing_validator_does_not_accept_or_blame_peer(self):
        a = await self.connect()
        self.validator.side_effect = NotImplementedError
        with self.assertLogs("network", level="ERROR"):
            await self.send(a, {"type":"object", "object":self.obj})
            await self.barrier(a)
        self.assertFalse(self.store.has_object(self.oid))

    async def test_malformed_envelopes_send_explanation_and_close(self):
        cases = [({"type":"object"}, "missing"),
                 ({"type":"object", "object":None}, "JSON object"),
                 ({"type":"ihaveobject", "objectid":"abc"}, "64"),
                 ({"type":"getobject", "objectid":"A"*64}, "lowercase")]
        for msg, reason in cases:
            a = await self.connect()
            await self.send(a, msg)
            error = await self.receive(a)
            self.assertEqual(error["name"], "INVALID_FORMAT")
            self.assertIn(reason, error["msg"])
            self.assertIsNone(await self.receive(a))

    async def test_no_gossip_before_handshake(self):
        pending = await self.connect(handshake=False)
        a = await self.connect()
        await self.send(a, {"type":"object", "object":self.obj})
        self.assertEqual((await self.receive(a))["type"], "ihaveobject")
        await self.send(pending, {"type":"hello", "version":"0.10.0", "agent":"Test"})
        await self.barrier(pending)

    async def test_concurrent_objects_gossip_once(self):
        a, b = await self.connect(), await self.connect()
        await asyncio.gather(*(self.send(c, {"type":"object", "object":self.obj}) for c in (a,b)))
        for c in (a,b):
            self.assertEqual((await self.receive(c))["type"], "ihaveobject")
            await self.barrier(c)

    async def test_broken_peer_does_not_stop_broadcast(self):
        a = await self.connect()
        broken = Mock()
        broken.write.side_effect = ConnectionResetError
        network.peers["broken"] = network.Peer("broken", 1, broken)
        with self.assertLogs("network", level="WARNING"):
            await network.broadcast_ihaveobject(self.oid)
        self.assertEqual((await self.receive(a))["objectid"], self.oid)
        broken.close.assert_called_once()

    async def test_failed_persistence_does_not_publish(self):
        with patch.object(self.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.store.add_and_save_if_new(self.obj)
        self.assertFalse(self.store.has_object(self.oid))

    async def test_outgoing_connection_uses_shared_store(self):
        remote_done = asyncio.Event()
        remote_errors = []
        self.store.add_object(self.obj)
        async def remote(reader, writer):
            try:
                await asyncio.wait_for(reader.readline(), 2)
                await asyncio.wait_for(reader.readline(), 2)
                writer.write((json.dumps({"type":"hello","version":"0.10.0","agent":"Remote"})+"\n"+
                              json.dumps({"type":"getobject","objectid":self.oid})+"\n").encode())
                await writer.drain()
                reply = json.loads(await asyncio.wait_for(reader.readline(), 2))
                self.assertEqual(reply, {"type":"object", "object":self.obj})
            except Exception as exc:
                remote_errors.append(exc)
            finally:
                writer.close()
                await writer.wait_closed()
                remote_done.set()
        server = await asyncio.start_server(remote, "127.0.0.1", 0)
        try:
            await asyncio.wait_for(network.connect_to_peer("127.0.0.1", server.sockets[0].getsockname()[1], self.manager, self.store), 3)
            await asyncio.wait_for(remote_done.wait(), 2)
            self.assertEqual(remote_errors, [])
        finally:
            server.close()
            await server.wait_closed()

    async def test_outgoing_maintenance_passes_store_and_cleans_up(self):
        self.manager.add_peers(["node.example:18018"])
        running = {}
        called = asyncio.Event()

        async def connect(host, port, manager, store):
            self.assertIs(store, self.store)
            self.assertIs(manager, self.manager)
            called.set()

        with patch("network.connect_to_peer", side_effect=connect):
            task = asyncio.create_task(network.maintain_outgoing(
                self.manager, 18018, running, self.store))
            try:
                await asyncio.wait_for(called.wait(), 2)
                await asyncio.gather(*list(running.values()))
                await asyncio.sleep(0)
                self.assertEqual(running, {})
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class EnvelopeTests(unittest.TestCase):
    def test_ids_and_object_envelopes(self):
        for kind in ("ihaveobject", "getobject"):
            self.assertTrue(validate_message({"type":kind,"objectid":"a"*64}))
            for value in ("", "a"*63, "a"*65, "A"*64, "g"*64, None, 1, [], {}):
                msg = {"type":kind, "objectid":value}
                self.assertFalse(validate_message(msg))
                self.assertIsNotNone(object_exchange_format_error(msg))
        self.assertTrue(validate_message({"type":"object", "object":{"type":"transaction"}}))
        self.assertFalse(validate_message({"type":"object", "object":{"type":"block"}}))
