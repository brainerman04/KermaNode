import asyncio
import logging
import os

import network
from config import *
from peer_manager import PeerManager
from object_store import ObjectStore

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":

    # Gemeinsamen PeerManager erstellen
    peer_manager = PeerManager(os.getenv("PEERS_FILE", "peers.json"))

    # Gemeinsamen ObjectStore erstellen
    object_store = ObjectStore(os.getenv("OBJECTS_FILE", "objects.json"))

    # Gespeicherte Peers laden
    peer_manager.load()

    # Gespeicherte Objects laden
    object_store.load()

    # Bootstrap-Adressen einmal beim Start hinzufügen
    peer_manager.add_peers(BOOTSTRAP_PEERS)

    # Netzwerk starten
    # TODO: ObjectStore später an network.main() übergeben
    asyncio.run(network.main(PORT, peer_manager))
