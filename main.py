import asyncio
import logging
import network
from config import *

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # TODO(T1-08): Persistente Peer-Liste laden und mit dem Bootstrap-Eintrag aus
    # config zusammenführen; anstelle von [] an network.main übergeben. Bei der
    # ersten Ausführung ohne Peer-Datei mit einem leeren Bestand plus Seed starten.
    # Datei erst über peer_manager importieren, wenn dessen Testclient ausgelagert
    # ist (T1-07); der aktuelle Modulimport würde selbst eine TCP-Verbindung öffnen.
    asyncio.run(network.main(PORT, []))
