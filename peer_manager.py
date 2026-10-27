import json
import os
import tempfile
import asyncio
import random
import logging
from pathlib import Path
from protocol import validate_peer_address

log = logging.getLogger(__name__)

class PeerManager:
    def __init__(self, file_path="peers.json"):
        self.file_path = file_path
        self.known_peers = set() # Store known peers without duplicates
        self.lock = asyncio.Lock()  # Protect peer updates

    # Add new peers
    def add_peers(self, addresses):
        for address in addresses:
            if validate_peer_address(address):
                self.known_peers.add(address)

    # Remove a peer
    def forget_peer(self, address):
        self.known_peers.discard(address)

    # Return known peers without excluded addresses
    def get_peers(self, limit=29, exclude=None):
        excluded = set(exclude or [])
        peers = list(self.known_peers - excluded)

        if len(peers) > limit:
            peers = random.sample(peers, limit)

        return peers

    # Save peers safely to a JSON file
    def save(self):
        path = Path(self.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None

        try:
            # Write peers to a temporary file
            with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    delete=False
            ) as file:
                temp_path = file.name
                json.dump(sorted(self.known_peers), file)
                file.flush()
                os.fsync(file.fileno())

            # Replace the old file
            os.replace(temp_path, path)

        finally:
            # Remove the temporary file if something failed
            if temp_path is not None and os.path.exists(temp_path):
                os.remove(temp_path)

    # Load peers from a JSON file
    def load(self):
        try:
            with open(self.file_path, "r") as file:
                addresses = json.load(file)

            if not isinstance(addresses, list):
                raise ValueError("Invalid peer file")

            if not all(isinstance(address, str) for address in addresses):
                raise ValueError("Invalid peer addresses")

            self.known_peers = {
                address for address in addresses
                if validate_peer_address(address)
            }

        except FileNotFoundError:
            self.known_peers = set()  # First start

        except (json.JSONDecodeError, ValueError, OSError) as error:
            log.warning("Could not load peers: %s", error)
            self.known_peers = set()

    # Add peers and save changes
    async def add_and_save(self, addresses):
        async with self.lock:
            self.add_peers(addresses)
            await asyncio.to_thread(self.save)

    # Remove a peer and save changes
    async def forget_and_save(self, address):
        async with self.lock:
            self.forget_peer(address)
            await asyncio.to_thread(self.save)