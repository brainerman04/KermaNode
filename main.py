import asyncio
import logging
import os

import network
from config import *
from peer_manager import PeerManager

logging.basicConfig(level=logging.INFO)


if __name__ == "__main__":

    # Gemeinsamen PeerManager erstellen
    peer_manager = PeerManager(
        os.getenv("PEERS_FILE", "peers.json")
    )

    # Gespeicherte Peers laden
    peer_manager.load()

    # Bootstrap-Adressen einmal beim Start hinzufügen
    peer_manager.add_peers(BOOTSTRAP_PEERS)

    # Netzwerk starten
    asyncio.run(
        network.main(PORT, peer_manager)
    )
