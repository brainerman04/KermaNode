<!--
TODO(T1-14): Start-/Testanleitung und Abgabecheck dokumentieren. Offene Arbeiten
sind direkt im Code mit T1-01 bis T1-14 markiert; gleiche IDs gehören zusammen.
Reihenfolge: Empfangsfehler/Timeout (01-03), Nachrichten/Discovery (04-06),
Persistenz/Bootstrap/Verbindungspflege (07-09), Betrieb (10-12), Abnahme (13-14).

Abnahme gegen Kerma-Task-1.pdf und Protokollabschnitte 5.1-5.3/5.11:
- Start lokal und über Docker, Konfiguration und Peer-Dateipfad beschreiben.
- python -m unittest discover -s tests -v und die neuen TCP-Tests dokumentieren.
- Frisch entpacktes Archiv mit docker-compose build, docker-compose up -d,
  Grader-Verbindung zu localhost:18018, docker-compose down -v prüfen.
- Dockerfile und docker-compose.yml liegen direkt im Archiv-Hauptverzeichnis;
  alle Laufzeitdateien/Abhängigkeiten sind dabei. Keine .venv, .git, lokalen
  Zustandsdateien, absoluten Rechnerpfade oder vorbefüllte Blockchain mitliefern.
- Ausgehend/ankommend Hello + GetPeers, Fragmentierung, Fehlercodes, 20s-Timeout,
  Reconnect, parallele Clients, Peer-Antworten und Neustart-Persistenz abhaken.

Task-1-Grenze: Transaktions-/Blockprüfung, Mining, Mempool und Chain-Sync sind
hier nicht umzusetzen. Öffentliche Bereitstellung ist optional; Docker-Abgabe
und die lokale Erreichbarkeit des Graders sind erforderlich.
-->
