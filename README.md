# 🎵 Qobuz-DL Unified // Full-Stack Audio Engine & Web Client

Aplicação unificada e integrada combinando o **frontend moderno do Qobuz-DL-main** com o **motor de downloads e marcação em Python FastAPI do qobuz-dl-master**.

---

## ⚡ Como Executar Tudo Junto (1 Único Comando)

### Opção 1: Servidor Integrado (Recomendado)
Executa a API FastAPI, WebSockets e a interface web completa em um único processo:

```bash
# 1. Instalar dependências do Python
pip install -r backend/requirements.txt

# 2. Iniciar o programa
python run.py
```
> Acesse diretamente no seu navegador: **`http://localhost:8000`**

---

### Opção 2: Modo de Desenvolvimento Concorrente (Next.js + FastAPI)
Para desenvolvedores que desejam alterar o código React com Hot-Reload (FastAPI na porta 8000 e Next.js na porta 3000):

```bash
# 1. Instalar dependências
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 2. Iniciar ambos concorrentemente
python run.py --dev
```

---

### Opção 3: Executar via Docker Compose
```bash
docker-compose up --build
```
> Acesse a interface web em **`http://localhost:3000`** com backend em **`http://localhost:8000`**.

---

## 🌟 Funcionalidades Integradas

- **Execução Unificada**: Um único comando (`python run.py`) inicia toda a aplicação.
- **Busca Global com Autocomplete**: Pesquisa em tempo real de álbuns, faixas e artistas no catálogo oficial da Qobuz.
- **Download Direto de Links**: Cole links de faixas ou álbuns (`open.qobuz.com/...`) para download imediato.
- **Barra de Status Flutuante**: Acompanhe o progresso percentual, velocidade de download (MB/s) e tempo estimado (ETA) via WebSocket.
- **Qualidade Studio Hi-Res**: Suporte a FLAC 24-Bit / 192 kHz, 24-Bit / 96 kHz, 16-Bit / 44.1 kHz (CD) e MP3 320 kbps.
- **Metadados & Tags Automáticas**: Incorporação de capas em alta resolução, tags Vorbis/ID3 e letras sincronizadas `.LRC` (LRCLib).
- **Gerenciador de Fila Assíncrono**: Pausa, retomada, cancelamento e histórico com prevenção de duplicatas via SQLite local.
