import asyncio
import logging
import os

import network
from config import *
from peer_manager import PeerManager

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":

    peer_manager = PeerManager(os.getenv("PEERS_FILE", "peers.json"))
    peer_manager.load()
    known_peers = peer_manager.known_peers

    all_peers = set(known_peers)
    all_peers.update(BOOTSTRAP_PEERS)

    peer_tuples = []

    for address in all_peers:
        host, port = address.split(":")
        port = int(port)
        peer_tuples.append((host, port))

    asyncio.run(network.main(PORT, peer_tuples))
