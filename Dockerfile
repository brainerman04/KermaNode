# TODO(T1-11): Lauffähiges Python-Image definieren, passenden WORKDIR setzen und
# die benötigten Projektdateien kopieren. main.py als Vordergrundprozess starten
# (z.B. python -u main.py), damit Container-Lifecycle und Logs korrekt funktionieren.
# Abhängigkeiten bei Bedarf reproduzierbar installieren; .venv nicht übernehmen.
# Port 18018 dokumentieren; die Host-Freigabe erfolgt separat über Compose.
FROM python:3.11-slim
WORKDIR /app
COPY . .
CMD ["python", "-u", "main.py"]
