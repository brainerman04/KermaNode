import json
import unittest

import network
from config import errorType
from protocol import error_msg, validate_hello

# TODO(T1-13): TCP-Integrationstests ergänzen; die vorhandenen Fakes prüfen keinen
# echten TCP-Empfang. hello/getpeers-Reihenfolge in beiden Verbindungsrichtungen,
# Reconnect und zwei gleichzeitige Clients prüfen. Ein fehlerhafter Client darf
# weder den Server noch die jeweils andere Verbindung beenden.
# TODO(T1-13): Fragmentierte Zeilen (mit Pause zwischen Schreibvorgängen), mehrere
# Zeilen in einem Write und nichtkanonisches, aber gültiges JSON testen. Abdecken:
# fehlendes \n bei EOF, ungültiges UTF-8/JSON, NaN/Infinity, zu lange Zeilen sowie
# JSON-Skalare/Arrays, fehlender/falscher/unbekannter type auch nach dem Handshake.
# Jeder Fehler muss genau eine passende Error-Antwort und Verbindungsabbau liefern.
# TODO(T1-13): Schweigenden Peer und unvollständiges hello bis zur 20s-Deadline
# testen: INVALID_HANDSHAKE muss vor EOF eintreffen. Laufende Tests zeitlich begrenzen;
# bei Connect-, Lese- und Sendefehlern Cleanup und weiteres Accept verifizieren.
# TODO(T1-13): Schema-/Adresstests für getpeers/peers ergänzen: fehlende/zusätzliche
# Felder, falsche Listentypen, leere Liste, 30/31 Einträge, Ports 1/65535 vs. 0/65536,
# öffentliche/private/ungültige IPv4 und die eigenen DNS-Regeln des Protokolls.
# Beispiele: 256.2.3.4:18018, 1.2.3.4.5:678, 1.2.3.4:2000000,
# 192.168.0.2:18018, nodotindomain:1234 und kermanode.net zurückweisen.
# Eine teilweise ungültige peers-Liste darf den bekannten Bestand nicht verändern.
# TODO(T1-13): Peer-Discovery durchgängig prüfen: peers empfangen, Verbindung
# trennen, erneut verbinden und gespeicherte Adressen per getpeers wiederfinden.
# Zusätzlich Prozess/Container neu starten; Bestand muss erhalten bleiben.
# Antworten enthalten <=30 Adressen, eigene Adresse zuerst, keine Duplikate.
# Neue Peers werden gemäß Verbindungspolitik kontaktiert; offline/fehlerhafte
# ausgehende Ziele werden vergessen, dürfen aber später erneut entdeckt werden.
# TODO(T1-13): Empfangene error-Nachrichten und gültige andere Kerma-Typen dürfen
# nach dem Handshake keine Trennung/Fehlerantwortschleife auslösen. Bootstrap-Ausfall,
# DNS-Fehler und lange Laufzeit mit wechselnden Clients als Regression abdecken.


def hello(**changes):
    message = {"type": "hello", "version": "0.10.0", "agent": "TestNode"}
    message.update(changes)
    return message


class FakeWriter:
    """Record transmitted bytes without opening a TCP connection."""

    def __init__(self):
        self.payloads = []
        self.closed = False

    def get_extra_info(self, name):
        return ("127.0.0.1", 43210)

    def write(self, payload):
        self.payloads.append(payload)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def messages(self):
        return [json.loads(payload) for payload in self.payloads]


class FakeReader:
    def __init__(self, messages, writer):
        self.lines = [(json.dumps(message) + "\n").encode() for message in messages]
        self.writer = writer
        self.read_count = 0
        self.closed_while_reading = []

    async def readline(self):
        self.read_count += 1
        self.closed_while_reading.append(self.writer.closed)
        return self.lines.pop(0) if self.lines else b""


class HelloTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        network.peers.clear()

    async def test_valid_versions_and_agent_boundaries(self):
        agents = ["", "a" * 128, "".join(chr(code) for code in range(0x20, 0x7F))]
        for digit in range(10):
            for agent in agents:
                with self.subTest(digit=digit, agent=agent):
                    writer = FakeWriter()
                    self.assertTrue(await validate_hello(hello(version=f"0.10.{digit}", agent=agent), writer))
                    self.assertEqual(writer.payloads, [])

    async def test_invalid_hello_sends_one_specific_format_error(self):
        cases = [
            (None, "JSON object"),
            ([], "JSON object"),
            ("hello", "JSON object"),
            (42, "JSON object"),
            (True, "JSON object"),
            (hello(extra=True), "additional fields"),
            (hello(type=42), "'type' must be a string"),
            (hello(type=["hello"]), "'type' must be a string"),
            (hello(type="unknown"), "'type' must equal 'hello'"),
            (hello(version=None), "'version' must be a string"),
            (hello(version=0.10), "'version' must be a string"),
            (hello(agent=None), "'agent' must be a string"),
            (hello(agent=["node"]), "'agent' must be a string"),
            (hello(agent="a" * 129), "128 characters"),
        ]
        for key in ("type", "version", "agent"):
            message = hello()
            del message[key]
            cases.append((message, f"missing required fields: {key}"))
        for version in ("5.8.2", "0.10.10", "0.10.", "0.10.1\n", "0x10x1", "0.10.١"):
            cases.append((hello(version=version), "exactly one decimal digit"))
        for agent in ("a\nb", "a\tb", "a\x00b", "a\x7fb", "Grüße", "🙂"):
            cases.append((hello(agent=agent), "printable ASCII"))

        for message, reason in cases:
            with self.subTest(message=message):
                writer = FakeWriter()
                self.assertFalse(await validate_hello(message, writer))
                self.assertEqual(len(writer.payloads), 1)
                payload = writer.payloads[0]
                self.assertIsInstance(payload, bytes)
                self.assertTrue(payload.endswith(b"\n"))
                response = json.loads(payload)
                self.assertEqual(set(response), {"type", "name", "msg"})
                self.assertEqual(response["type"], "error")
                self.assertEqual(response["name"], "INVALID_FORMAT")
                self.assertIn(reason, response["msg"])

    async def test_error_msg_sends_only_to_its_writer(self):
        writer = FakeWriter()
        other_writer = FakeWriter()
        network.peers["other:18018"] = network.Peer("other", 18018, other_writer)
        self.assertIsNone(await error_msg(writer, errorType.INV_HANDS, "Expected hello."))
        self.assertEqual(writer.messages(), [{
            "type": "error", "name": "INVALID_HANDSHAKE", "msg": "Expected hello.",
        }])
        self.assertEqual(other_writer.payloads, [])

    async def test_invalid_hello_stops_handler_and_cleans_up(self):
        writer = FakeWriter()
        reader = FakeReader([hello(agent="bad\nagent"), hello()], writer)
        await network.handle_incoming(reader, writer)
        self.assertEqual(reader.read_count, 1)
        messages = writer.messages()
        self.assertEqual([message["type"] for message in messages], ["hello", "getpeers", "error"])
        self.assertEqual(messages[-1]["name"], "INVALID_FORMAT")
        self.assertTrue(writer.closed)
        self.assertEqual(network.peers, {})

    async def test_success_keeps_reading_until_peer_disconnects(self):
        writer = FakeWriter()
        reader = FakeReader([hello(), {"type": "getchaintip"}], writer)
        await network.handle_incoming(reader, writer)
        self.assertEqual(reader.read_count, 3)
        self.assertFalse(any(reader.closed_while_reading))
        self.assertEqual([message["type"] for message in writer.messages()], ["hello", "getpeers"])
        self.assertTrue(writer.closed)
        self.assertEqual(network.peers, {})

    async def test_message_before_hello_is_handshake_error(self):
        writer = FakeWriter()
        reader = FakeReader([{"type": "getpeers"}], writer)
        await network.handle_incoming(reader, writer)
        self.assertEqual(writer.messages()[-1]["name"], "INVALID_HANDSHAKE")
        self.assertTrue(writer.closed)
        self.assertEqual(network.peers, {})

    async def test_second_hello_is_handshake_error(self):
        writer = FakeWriter()
        reader = FakeReader([hello(), hello()], writer)
        await network.handle_incoming(reader, writer)
        self.assertEqual(writer.messages()[-1]["name"], "INVALID_HANDSHAKE")
        self.assertTrue(writer.closed)
        self.assertEqual(network.peers, {})


if __name__ == "__main__":
    unittest.main()
