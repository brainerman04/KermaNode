
from enum import Enum

# TODO(T1-10): Für Docker HOST auf 0.0.0.0 setzen; Abgabeport bleibt 18018.
# Bind-Adresse und öffentlich angebotene Listening-Adresse getrennt konfigurieren:
# 0.0.0.0/127.0.0.1 sind keine gültigen Einträge in peers-Nachrichten.
HOST = "0.0.0.0"
PORT = 18018
MAX_LINE_BYTES = 1024 * 1024 * 5

OUTBOUND_TARGET = 3
CONNECT_TIMEOUT = 5
RECONNECT_INTERVALL = 10
PUBLIC_HOST = None

# TODO(T1-08): Bootstrap-Liste mit 128.130.122.101:18018 hinterlegen (Task-1-Vorgabe).
# Beim Start gemeinsam mit dem gespeicherten Adressbestand laden; nicht bei jedem
# Verbindungsversuch ungeprüft wieder hinzufügen. Einen Ausfall tolerieren.
# TODO(T1-05): Eigene öffentliche IPv4-/DNS-Adresse plus Listening-Port als
# Konfiguration ergänzen und in peers-Antworten an erste Stelle setzen. Sie darf
# für den Grader fest konfiguriert sein; nicht aus einer TCP-Gegenstelle ableiten.
# TODO(T1-07): Pfad der Peer-Datei konfigurieren und im Container unter dem
# persistenten Datenverzeichnis ablegen (siehe docker-compose.yml).
# TODO(T1-09): Zielzahl ausgehender Verbindungen und Connect-Timeout festlegen.
# Das ist eine eigene Verbindungspolitik; die Spezifikation gibt keine feste Zahl vor.

class errorType(Enum):
  INV_FORM = "INVALID_FORMAT"
  INV_HANDS = "INVALID_HANDSHAKE"
  INV_TX_CON = "INVALID_TX_CONSERVATION"
  INV_TX_SIG = "INVALID_TX_SIGNATURE"
  INV_TX_OUT = "INVALID_TX_OUTPOINT"
  INV_BLOCK_POW = "INVALID_BLOCK_POW"
  INV_BLOCK_TS = "INVALID_BLOCK_TIMESTAMP"
  INV_BLOCK_CB = "INVALID_BLOCK_COINBASE"
  INV_GEN = "INVALID_GENISIS"
  UNKNOWN_OBJ = "UNKNOWN_OBJECT"
  UNFINDABLE_OBJ = "UNFINDABLE_OBJECT"
  INV_ANC = "INVALID_ANCESTRY"
