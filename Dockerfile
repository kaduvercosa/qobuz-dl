# Usa una versione ufficiale e leggera di Python 3.11
FROM python:3.11-slim

# Installa FFmpeg (fondamentale per la tua Ultimate Edition)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Imposta la cartella di lavoro dentro il contenitore
WORKDIR /app

# Copia tutti i file del tuo progetto dentro il contenitore
COPY . .

# Installa le dipendenze e il programma stesso
RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir .

# Dichiara il comando di base (così l'utente deve solo passare gli argomenti come 'dl' o '--sync-db')
ENTRYPOINT ["python", "-m", "qobuz_dl"]