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