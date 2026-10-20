# TODO(T1-07): Manuellen Testclient nach tests/manual_peer.py auslagern und dieses
# Modul für die Peer-Verwaltung nutzen. Beim Import keine Sockets öffnen.
# Benötigte Schnittstellen: load/save, add_peers, forget_peer und Auswahl für
# getpeers-Antworten/ausgehende Verbindungen. Bekannte Adressen als deduplizierten
# Bestand unabhängig von den aktiven Verbindungen in network halten.
# TODO(T1-07): Adressen lokal als JSON speichern, beim Neustart wieder einlesen.
# Änderungen atomar schreiben (temporäre Datei + os.replace); gleichzeitige
# Änderungen über einen zentralen Manager serialisieren, nicht gegenseitig
# überschreiben. Laden/Speichern darf die Eventloop nicht länger blockieren.
# Fehlende Datei als Erststart behandeln; beschädigte/unlesbare Datei kontrolliert
# loggen und mit definierter Wiederherstellung starten, statt den Node zu beenden.
# Offline/fehlerhafte ausgehende Peers entfernen und diese Änderung persistieren.
# Erneute Entdeckung und eingehende Verbindungen derselben Adresse weiter zulassen.

import socket

HOST = "127.0.0.1"  # The server's hostname or IP address
PORT = 18018  # The port used by the server

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    # TODO(T1-13, Testclient): Nach dem Auslagern gültiges hello mit \n senden;
    # den bisherigen Text mit \n als separaten INVALID_FORMAT-Test behalten.
    s.sendall(b"Hello, world")
    # TODO(T1-13, Testclient): Antworten zeilenweise lesen (z.B. makefile("rb")),
    # nicht ein recv() mit einer vollständigen Nachricht gleichsetzen. Initiales
    # hello/getpeers von der eigentlichen Testantwort unterscheiden. Socket-Timeout
    # setzen, damit Testfehler nicht unbegrenzt warten.
    data = s.recv(1024)

print(f"Received {data!r}")
