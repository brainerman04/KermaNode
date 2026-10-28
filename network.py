import asyncio
import json
import logging
import time
from config import HOST, PORT, MAX_LINE_BYTES, CONNECT_TIMEOUT, errorType, PUBLIC_HOST, RECONNECT_INTERVAL, OUTBOUND_TARGET
from protocol import error_msg, sendMessage, validate_hello, validate_message
from dataclasses import dataclass
from peer_manager import PeerManager

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
        
def on_outgoing_done(
    address: str,
    task: asyncio.Task,
    running: dict[str, asyncio.Task]
) -> None:

    # Beendeten Task aus dem Dictionary entfernen
    if running.get(address) is task:
        running.pop(address, None)

    # Regulär abgebrochene Tasks ignorieren
    if task.cancelled():
        return

    # Unerwartete Fehler überprüfen
    try:
        task.result()
    except Exception:
        log.exception("Outgoing task failed: %s", address)


async def maintain_outgoing(
    peer_manager: PeerManager,
    listen_port: int,
    running: dict[str, asyncio.Task]
) -> None:

    # Eigene veröffentlichte Adresse nicht anwählen
    self_address = (
        f"{PUBLIC_HOST}:{listen_port}"
        if PUBLIC_HOST else None
    )

    while True:

        # Aktuell bekannte Adressen abrufen
        candidates = peer_manager.get_peers(
            limit=len(peer_manager.known_peers)
        )

        for address in candidates:

            # Maximale Verbindungszahl erreicht?
            if len(running) >= OUTBOUND_TARGET:
                break

            # Nicht mit sich selbst verbinden
            if address == self_address:
                continue

            # Doppelte Verbindungen verhindern
            if address in running:
                continue

            host, port_text = address.rsplit(":", 1)
            port = int(port_text)

            # Ausgehende Verbindung parallel starten
            task = asyncio.create_task(
                connect_to_peer(host, port, peer_manager),
                name=f"outbound:{address}"
            )

            # Task merken
            running[address] = task

            # Bei Beendigung automatisch aufräumen
            task.add_done_callback(
                lambda finished, key=address:
                    on_outgoing_done(key, finished, running)
            )

        # Vor der nächsten Überprüfung warten
        await asyncio.sleep(RECONNECT_INTERVAL)

@dataclass
class Peer:
    host: str
    port: int
    writer: asyncio.StreamWriter

peers: dict[str, Peer] = {}   # "host:port" → Peer

async def handle_incoming(reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           peer_manager: PeerManager,
                           outbound_address: str | None = None) -> None:
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
                    await safe_send_error(
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
            if not data.endswith(b"\n"):
                    await safe_send_error(
                        writer,
                        errorType.INV_FORM,
                        "JSON string must end with new line."
                    )
                    return
            try:
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
                    await safe_send_error(writer, errorType.INV_HANDS, "Expected hello as first message.")
                    return
                if not await validate_hello(msg, writer):
                    # Die Fehlerantwort wurde im Validator bereits gesendet.
                    # return beendet den Handler; finally schließt die Verbindung.
                    return
                hello_received = True
                continue

            if isinstance(msg, dict) and msg.get("type") == "hello":
                await safe_send_error(writer, errorType.INV_HANDS, "Received a second hello after the handshake.")
                return
            
            if not validate_message(msg):
                await safe_send_error(writer, errorType.INV_FORM, "Invalid message format.")
                return

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

            if msg["type"] == "peers":
                await peer_manager.add_and_save(msg["peers"])

    except asyncio.IncompleteReadError:
        pass
    except ValueError as exc:
        log.warning("Invalid message size: %s", exc)

        await safe_send_error(
            writer,
            errorType.INV_FORM,
            "Message exceeds the allowed size."
        )
    except OSError as exc:
        log.warning("Network error with %s: %s", peer_id, exc)
    finally:
        # Läuft auch bei return und Exceptions. pop(..., None) ist auch dann
        # sicher, wenn der Eintrag bereits entfernt wurde.
        if peer_id in peers and peers[peer_id].writer is writer:
            peers.pop(peer_id, None)
            
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(),timeout=3)
        except (TimeoutError, OSError):
            log.warning("Could not close peer cleanly: %s", peer_id)



async def connect_to_peer(
    host: str,
    port: int,
    peer_manager: PeerManager
) -> None:
    address = f"{host}:{port}"

    try:
        # Verbindung mit Timeout aufbauen
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=CONNECT_TIMEOUT
        )

    except (TimeoutError, OSError) as exc:
        log.warning("Cannot connect to %s: %s", address, exc)

        # Nicht erreichbaren Peer vergessen
        try:
            await peer_manager.forget_and_save(address)
        except OSError:
            log.exception("Could not remove peer %s", address)

        return

    log.info("Connected to %s", address)

    try:
        # Gemeinsamen Nachrichten-Handler starten
        await handle_incoming(
            reader,
            writer,
            peer_manager,
            outbound_address=address
        )

    finally:
        # Bei normalem Shutdown keine Peers entfernen
        if not asyncio.current_task().cancelling():
            try:
                await peer_manager.forget_and_save(address)
            except OSError:
                log.exception("Could not remove peer %s", address)


async def main(
    listen_port: int,
    peer_manager: PeerManager
) -> None:

    running_outbound: dict[str, asyncio.Task] = {}
    running_inbound: set[asyncio.Task] = set()

    # Eingehende Verbindungen ebenfalls verwalten
    async def accept_peer(reader, writer):
        task = asyncio.current_task()

        if task is not None:
            running_inbound.add(task)

        try:
            await handle_incoming(
                reader,
                writer,
                peer_manager
            )
        finally:
            if task is not None:
                running_inbound.discard(task)

    # TCP-Server starten
    server = await asyncio.start_server(
        accept_peer,
        HOST,
        listen_port,
        limit=MAX_LINE_BYTES
    )

    log.info(
        "P2P node listening on %s:%d",
        HOST,
        listen_port
    )

    # Verbindungspflege im Hintergrund starten
    manager_task = asyncio.create_task(
        maintain_outgoing(
            peer_manager,
            listen_port,
            running_outbound
        ),
        name="maintain-outgoing"
    )

    try:
        # Eingehende Verbindungen dauerhaft annehmen
        async with server:
            await server.serve_forever()

    finally:
        # Verbindungspflege beenden
        manager_task.cancel()

        await asyncio.gather(
            manager_task,
            return_exceptions=True
        )

        # Alle aktiven Verbindungstasks beenden
        all_tasks = (
            list(running_outbound.values())
            + list(running_inbound)
        )

        for task in all_tasks:
            task.cancel()

        if all_tasks:
            await asyncio.gather(
                *all_tasks,
                return_exceptions=True
            )
