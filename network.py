import asyncio
import json
import logging
import time
from config import HOST, PORT, MAX_LINE_BYTES, CONNECT_TIMEOUT, errorType, PUBLIC_HOST
from protocol import error_msg, sendMessage, validate_hello, validate_message
from dataclasses import dataclass
from peer_manager import PeerManager

peer_manager = PeerManager()
log = logging.getLogger(__name__)

def reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")

async def safe_send_error(writer, err_type, explanation):
    try:
        await asyncio.wait_for(
            error_msg(writer, err_type, explanation),
            timeout=3
        )

    except (TimeoutError, OSError):
        log.warning("Could not deliver error message to peer.")

@dataclass
class Peer:
    host: str
    port: int
    writer: asyncio.StreamWriter

peers: dict[str, Peer] = {}   # "host:port" → Peer
# TODO(T1-07): Aktive Verbindungen und bekannte Listening-Adressen getrennt halten.
# Den persistenten Adressbestand über peer_manager verwalten; StreamWriter und
# eingehende TCP-Quellports gehören nicht in diesen Bestand.

async def handle_incoming(reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           outbound_address=None) -> None:
    # Jede Verbindung hat ihre eigene Deadline und ihren eigenen Handshake-Zustand.
    deadline = time.monotonic() + 20
    hello_received = False
    answer_hello = {"type":"hello","version":"0.10.0","agent":"SuperCoolNodeTeam08"}
    getpeers = {"type": "getpeers"}
    addr = writer.get_extra_info("peername")
    peer_id = outbound_address or f"{addr[0]}:{addr[1]}"
    log.info("[+] Incoming peer: %s", peer_id)
    peers[peer_id] = Peer(addr[0], addr[1], writer)

    try:
        await sendMessage(writer, answer_hello)
        await sendMessage(writer, getpeers)
        while True:
            if not hello_received:
                remaining = max(0, deadline - time.monotonic())
                try:
                    data = await asyncio.wait_for(
                        reader.readline(),
                        timeout=remaining
                    )

                except TimeoutError:
                    await error_msg(
                        writer,
                        errorType.INV_HANDS,
                        "Hello not received within 20 seconds."
                    )
                    return
            else:
                # Nach dem Handshake offenbleiben, ohne dessen 20-Sekunden-Frist.
                data = await reader.readline()
            if not data:
                # b"" bedeutet normales Verbindungsende, keinen Handshake-Fehler.
                return
            # TODO(T1-01): Die drei Empfangsfehler unten korrekt abschließen:
            # error_msg(writer, errorType.INV_FORM, begruendung) aufrufen und danach
            # jeweils return. Aktuell fehlt writer; ohne return würde msg trotz
            # Parsefehler weiterverwendet (undefiniert oder aus der vorigen Nachricht).
            if not data.endswith(b"\n"):
                    await safe_send_error(
                        writer,
                        errorType.INV_FORM,
                        "JSON string must end with new line."
                    )
                    return
            try:
                # TODO(T1-02): Strikten JSON-Parser verwenden: NaN/Infinity über
                # parse_constant zurückweisen und als INVALID_FORMAT behandeln.
                # Empfangene Schlüsselreihenfolge/Leerzeichen weiter akzeptieren;
                # eingehende Nachrichten müssen nicht kanonisch serialisiert sein.
                # readline() puffert TCP-Fragmente und mehrere Zeilen bereits.
                msg = json.loads(data.decode("utf-8"),
                                 parse_constant=reject_json_constant)
                log.info("Message from %s: %s", peer_id, msg)
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError
            ) as exc:
                log.warning("Invalid JSON from %s: %s", peer_id, exc)
                await safe_send_error(
                    writer,
                    errorType.INV_FORM,
                    "Invalid JSON."
                )
                return
            if not hello_received:
                # Die Reihenfolge hängt vom Verbindungszustand ab und gehört
                # deshalb hierher. Die Formatdetails prüft nur validate_hello().
                if isinstance(msg, dict) and msg.get("type") in (
                    "getpeers", "peers", "getobject", "ihaveobject", "object",
                    "getchaintip", "chaintip", "getmempool", "mempool", "error",
                ):
                    await error_msg(writer, errorType.INV_HANDS, "Expected hello as first message.")
                    return
                if not await validate_hello(msg, writer):
                    # Die Fehlerantwort wurde im Validator bereits gesendet.
                    # return beendet den Handler; finally schließt die Verbindung.
                    return
                hello_received = True
                continue

            if isinstance(msg, dict) and msg.get("type") == "hello":
                await error_msg(writer, errorType.INV_HANDS, "Received a second hello after the handshake.")
                return
            # TODO(T1-04): Gemeinsame Nachrichtenvalidierung aus protocol aufrufen:
            # JSON-Objekt, type als String, bekannter Typ; getpeers/peers vollständig
            # prüfen. Bei INVALID_FORMAT antworten und return. Hello-Formatprüfung
            # und Handshake-Zustand nicht in diesen neuen Dispatcher duplizieren.
            # Andere bekannte Typen (z.B. getchaintip/object) nach dem Handshake
            # für Task 1 weiter ignorieren; keine Blockchain-Validierung ergänzen.
            # Empfangene error-Nachrichten höchstens loggen, keine Antwortschleife.
            if not validate_message(msg):
                await error_msg(writer, errorType.INV_FORM, "Invalid message format.")
                return

            # TODO(T1-05): Gültiges getpeers nur diesem writer mit peers beantworten.
            # Eigene konfigurierte Listening-Adresse zuerst, insgesamt <=30 Einträge
            # inklusive eigener Adresse. Deduplizieren und für größere Bestände eine
            # Auswahlregel festlegen (z.B. zufällige Auswahl der übrigen Plätze).
            # Bei kleinem Bestand alle passenden bekannten Adressen weitergeben;
            # nie die ephemeren Quellports aus dem aktiven peers-Dictionary anbieten.
            if msg["type"] == "getpeers":
                if PUBLIC_HOST is not None:
                    my_address = f"{PUBLIC_HOST}:{PORT}"
                    known_peers = peer_manager.get_peers(limit=29,exclude=[my_address])
                    all_peers = [my_address] + known_peers
                else:
                    known_peers = peer_manager.get_peers(limit=30)
                    all_peers = known_peers

                response = {
                    "type": "peers",
                    "peers": all_peers[:30]  # Limit to 30 entries 
                }
                await sendMessage(writer, response)
            
            # TODO(T1-06): Gültige peers-Nachricht vollständig validieren, dann den
            # Adressbestand aktualisieren und persistieren (T1-07). Auch freiwillig
            # gesendete peers verarbeiten. Bei einem ungültigen Eintrag nichts
            # übernehmen: INVALID_FORMAT senden, Verbindung schließen.
            if msg["type"] == "peers":
                await peer_manager.add_and_save(msg["peers"])


    # TODO(T1-03): TimeoutError abfangen: INVALID_HANDSHAKE mit Erklärung senden,
    # danach Handler beenden. Die Deadline/Abschaltung ist vorhanden; die Antwort
    # fehlt noch. TimeoutError vor OSError behandeln, da es davon abgeleitet ist.
    # TODO(T1-02): ValueError von readline() bei überschrittenem Zeilenlimit mit
    # INVALID_FORMAT beantworten und beenden. Das Limit explizit festlegen und für
    # gültige Task-1-Nachrichten ausreichend wählen; unbegrenzt puffern vermeiden.
    # TODO(T1-03): ConnectionError/OSError beim Lesen und Senden abfangen/loggen.
    # Auch drain() einer Fehlerantwort kann scheitern; Cleanup muss trotzdem laufen.
    # Für Sendepuffer bei nicht lesenden Clients ein begrenztes Schreib-Timeout
    # vorsehen und dabei Netzwerkfehler von der Hello-Empfangsfrist unterscheiden.
    except asyncio.IncompleteReadError:
        pass
    except ValueError as exc:
        log.warning("Invalid message size: %s", exc)

        await error_msg(
            writer,
            errorType.INV_FORM,
            "Message exceeds the allowed size."
        )
    except OSError as exc:
        log.warning("Network error with %s: %s", peer_id, exc)
    finally:
        # Läuft auch bei return und Exceptions. pop(..., None) ist auch dann
        # sicher, wenn der Eintrag bereits entfernt wurde.
        peers.pop(peer_id, None)
        # TODO(T1-07): Bei fehlerhaften/offline AUSGEHENDEN Peers zusätzlich die
        # ursprünglich kontaktierte Adresse aus dem bekannten Bestand entfernen
        # und speichern. Bei eingehenden Peers keine Listening-Adresse aus addr,
        # agent oder dem ersten peers-Eintrag erraten. Keine dauerhafte Sperrliste:
        # erneute eingehende Verbindung und spätere Neuentdeckung zulassen.
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        log.info("[-] Peer disconnected: %s", peer_id)


async def connect_to_peer(host: str, port: int) -> None:
    """Initiate an outbound connection to another peer."""
    try:
        # TODO(T1-09): Verbindungsaufbau/DNS mit Timeout begrenzen; OSError inklusive
        # DNS-Fehler und Timeout behandeln. Ein unerreichbarer Peer darf den Start
        # oder die Pflege anderer Verbindungen nicht aufhalten. Danach gemäß T1-07
        # aus dem bekannten Bestand entfernen, statt ihn endlos sofort neu anzuwählen.
        peer_id = f"{host}:{port}"
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=CONNECT_TIMEOUT
        )

    except (TimeoutError, OSError) as exc:
        log.warning("Cannot connect to %s: %s", peer_id, exc)

        # TODO: Mit Person 3 abstimmen:
        # Fehlgeschlagenen Peer aus der bekannten Liste entfernen.
        return
    except ConnectionRefusedError:
        log.warning("Peer %s:%d refused connection", host, port)
        return
        # TODO(T1-09): Registrierung auf eine Stelle reduzieren. handle_incoming()
        # registriert denselben Stream erneut, ggf. mit IP statt DNS-Namen. Die
        # ursprüngliche Zieladresse separat an den gemeinsamen Handler übergeben,
        # damit Cleanup und Entfernen aus known_peers dieselbe Verbindung betreffen.
    peers[peer_id] = Peer(host, port, writer)
    log.info("[→] Connected to %s", peer_id)

    # TODO(T1-09): Hintergrundtasks in einer Sammlung halten, abgeschlossene
    # Tasks entfernen und Exceptions loggen. Beim Shutdown verbleibende Tasks
    # abbrechen/abwarten; eingehende Handler dabei ebenfalls berücksichtigen.
    # asyncio.create_task(handle_incoming(reader, writer))
    await handle_incoming(
        reader,
        writer,
        outbound_address=address
    )

async def main(listen_port: int, known_peers: list[tuple[str, int]]) -> None:
    peer_manager.load()  # Load known peers from file
    server = await asyncio.start_server(
        # TODO(T1-10): Hier und im folgenden Log PORT durch listen_port ersetzen.
        # Container muss auf 0.0.0.0:18018 lauschen (Konfiguration siehe config.py).
        handle_incoming, HOST, PORT, limit=MAX_LINE_BYTES
    )
    log.info("P2P node listening on %s:%d", HOST, listen_port)

    # TODO(T1-09): Die einmalige Schleife durch eine laufende Verbindungspflege
    # ergänzen: wenige ausgehende Verbindungen als Ziel festlegen, neue bekannte
    # Peers nachziehen und aktive/laufende Verbindungsversuche deduplizieren.
    # Eigene veröffentlichte Adresse nicht anwählen. Ausgehende Versuche begrenzen,
    # eingehende Verbindungen weiter unabhängig annehmen (mindestens zwei parallel).
    # Langsame Verbindungen dürfen weder Eventloop noch Listener blockieren.
    for host, port in known_peers:
        await connect_to_peer(host, port)

    async with server:
        await asyncio.gather(server.serve_forever())
