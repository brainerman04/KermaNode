
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from peer_manager import PeerManager


class TestPeerManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "peers.json"
        self.manager = PeerManager(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_add_and_remove(self):
        # Check duplicates and removing peers
        await self.manager.add_and_save([
            "node1.example.org:18018",
            "node1.example.org:18018",
            "node2.example.org:18018"
        ])

        self.assertEqual(len(self.manager.get_peers()), 2)

        await self.manager.forget_and_save("node1.example.org:18018")
        self.assertEqual(len(self.manager.get_peers()), 1)

    async def test_invalid_address(self):
        # Invalid addresses should not be saved
        await self.manager.add_and_save([
            "127.0.0.1:18018",
            "invalid",
            "node1.example.org:18018"
        ])

        self.assertEqual(
            self.manager.get_peers(),
            ["node1.example.org:18018"]
        )

    async def test_save_and_load(self):
        # Check if peers are restored
        await self.manager.add_and_save(["node1.example.org:18018"])

        new_manager = PeerManager(self.path)
        await asyncio.to_thread(new_manager.load)

        self.assertEqual(
            new_manager.get_peers(),
            ["node1.example.org:18018"]
        )

    async def test_get_peers_limit(self):
        # Return at most 29 peers
        addresses = [
            f"node{i}.example.org:18018"
            for i in range(50)
        ]

        await self.manager.add_and_save(addresses)

        result = self.manager.get_peers(
            exclude={"node0.example.org:18018"}
        )

        self.assertEqual(len(result), 29)
        self.assertNotIn("node0.example.org:18018", result)

    async def test_concurrent_updates(self):
        # Save updates from multiple tasks
        await asyncio.gather(*[
            self.manager.add_and_save([f"node{i}.example.org:18018"])
            for i in range(20)
        ])

        saved = json.loads(self.path.read_text())
        self.assertEqual(len(saved), 20)

    async def test_corrupted_file(self):
        # Start with empty peers if file is corrupted
        self.path.write_text("invalid json")

        await asyncio.to_thread(self.manager.load)

        self.assertEqual(self.manager.get_peers(), [])


if __name__ == "__main__":
    unittest.main()
