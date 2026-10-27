import asyncio
import json
import re
from config import errorType
import ipaddress

# TODO(T1-04): Validatoren für Task-1-Nachrichten ergänzen und aus network aufrufen.
# Basis: dict, type als String, bekannter Nachrichtentyp. getpeers hat exakt {type};
# peers exakt {type, peers}, wobei peers eine Liste mit 0..30 Strings sein muss.
# Fehlende/zusätzliche Schlüssel und falsche Datentypen -> INVALID_FORMAT.
# Für andere bekannte Typen verlangt Task 1 keine vollständige Inhaltsprüfung;
# nach erfolgreichem Handshake darf deren Empfang die Verbindung nicht schließen.
# TODO(T1-04): Adressvalidator ergänzen: host:port, ASCII-Dezimalport 1..65535.
# Host ist eine öffentliche IPv4-Adresse oder ein DNS-Name nach Kerma-Regeln.
# IPv4 z.B. mit ipaddress.IPv4Address prüfen; private/Loopback/Link-local sowie
# sonstige nicht öffentliche Adressen ausschließen. Keine IPv6-Adressen zulassen.
# DNS: fullmatch(r"[a-zA-Z0-9._-]{3,50}", host), mindestens ein ASCII-Buchstabe
# und mindestens ein Punkt im Inneren. Keine strengeren DNS-Regeln voraussetzen
# und zur reinen Formatprüfung keinen DNS-Lookup erzwingen. Erst die gesamte
# peers-Liste validieren, dann übernehmen. Grenzfälle stehen in tests/test_hello.py.


async def sendMessage(writer: asyncio.StreamWriter, message: dict) -> None:
    """Send exactly one newline-delimited JSON message to this writer."""
    # Gemeinsamer Encoder für Nachrichten und Fehler; genau eine JSON-Zeile je Aufruf.
    payload = (json.dumps(message, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    writer.write(payload)
    await asyncio.wait_for(
        writer.drain(),
        timeout=3
    )


async def validate_hello(msg: object, writer: asyncio.StreamWriter) -> bool:
    """Validate a parsed hello; send INVALID_FORMAT and return False on failure."""
    required_keys = {"type", "version", "agent"}

    # Reihenfolge beibehalten: Struktur prüfen, bevor Pflichtfelder gelesen werden.
    if not isinstance(msg, dict):
        explanation = "Hello message must be a JSON object."
    elif required_keys - set(msg):
        missing_keys = ", ".join(sorted(required_keys - set(msg)))
        explanation = f"Hello message is missing required fields: {missing_keys}."
    elif set(msg) - required_keys:
        explanation = "Hello message must only contain type, version and agent; additional fields are not allowed."
    elif not isinstance(msg["type"], str):
        explanation = "Hello field 'type' must be a string."
    elif msg["type"] != "hello":
        explanation = "Hello field 'type' must equal 'hello'."
    elif not isinstance(msg["version"], str):
        explanation = "Hello field 'version' must be a string."
    elif re.fullmatch(r"0\.10\.[0-9]", msg["version"]) is None:
        explanation = "Hello field 'version' must match 0.10.x with exactly one decimal digit for x."
    elif not isinstance(msg["agent"], str):
        explanation = "Hello field 'agent' must be a string."
    elif len(msg["agent"]) > 128:
        explanation = "Hello field 'agent' must not exceed 128 characters."
    elif not all(0x20 <= ord(char) <= 0x7E for char in msg["agent"]):
        # Leerzeichen ist gültig; Steuerzeichen und Nicht-ASCII-Zeichen sind es nicht.
        explanation = "Hello field 'agent' must contain only printable ASCII characters (0x20 to 0x7E)."
    else:
        return True

    # Genau eine Fehlerantwort senden; der Aufrufer übernimmt den Verbindungsabbau.
    await error_msg(writer, errorType.INV_FORM, explanation)
    return False


async def error_msg(writer: asyncio.StreamWriter, err_type: errorType, explanation: str) -> None:
    # baue eine Nachricht für den betroffenen Peer und rufe sendMessage() auf
    await sendMessage(writer, {
        "type": "error",
        "name": err_type.value,
        "msg": explanation,
    })

def validate_message(msg: object) -> bool:
    if not isinstance(msg, dict):
        return False

    if "type" not in msg:
        return False

    if not isinstance(msg["type"], str):
        return False

    allowed_types = {
        "hello",
        "getpeers",
        "peers",
        "getobject",
        "ihaveobject",
        "object",
        "getchaintip",
        "chaintip",
        "getmempool",
        "mempool",
        "error"
    }

    if msg["type"] not in allowed_types:
        return False

    if msg["type"] == "getpeers":
        if set(msg.keys()) != {"type"}:
            return False

    if msg["type"] == "peers":
        if set(msg.keys()) != {"type", "peers"}:
            return False
            
        if not isinstance(msg["peers"], list):
            return False

        if len(msg["peers"]) > 30:
            return False

        for peer in msg["peers"]:
            if not isinstance(peer, str):
                return False

            if not validate_peer_address(peer):
                return False
    return True

def validate_peer_address(address: str) -> bool:
    if not isinstance(address, str):
        return False
    
    if ":" not in address:
        return False

    parts = address.split(":")

    if len(parts) != 2:
        return False

    host = parts[0]
    port = parts[1]

    if not port.isdigit() or not port.isascii():
        return False

    port_number = int(port)

    if port_number < 1 or port_number > 65535:
        return False

    try:
        ip = ipaddress.IPv4Address(host)

        if ip.is_global:
            return True
        else:
            return False
        
    except ipaddress.AddressValueError:
        host_length = len(host)
        if host_length < 3 or host_length > 50:
            return False

        valid_symbols = re.fullmatch(r"[a-zA-Z0-9._-]+", host)
        if not valid_symbols:
            return False

        if "." not in host[1:-1]:
            return False

        if re.search(r"[a-zA-Z]+", host):
            return True

    return False