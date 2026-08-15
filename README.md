# Qobuz-DL Unified (Next.js Frontend + Python FastAPI Backend)

Aplicação integrada unindo o frontend moderno do **Qobuz-DL-main** (Next.js 15, React, Tailwind CSS, Shadcn UI) com o motor de downloads de alta performance em **Python FastAPI** do **qobuz-dl-master**.

## 🚀 Funcionalidades

- **Frontend Moderno**: Interface em Next.js com Shadcn UI, suporte a Dark/Light mode, visualização em tempo real de capas, álbuns e lançamentos.
- **Busca Rápida com Autocomplete**: Busque por artistas, álbuns e faixas no catálogo global da Qobuz ou cole links diretos.
- **Fila & Status em Tempo Real**: WebSocket (`/ws/live`) integrado com barra de status flutuante e modal de gerenciamento de fila.
- **Motor Hi-Res Lossless**: Downloads em FLAC 24-Bit / 192 kHz com marcação completa de tags (Mutagen) e capas em alta resolução.
- **Letras Sincronizadas (.LRC)**: Extração automática de letras sincronizadas via LRCLib.
- **Tokens Dinâmicos**: Scraper dinâmico integrado do Web Player Qobuz para manter credenciais sempre atualizadas.

## 🛠️ Como Executar

### 1. Iniciar o Backend (FastAPI)
```bash
cd backend
pip install -r requirements.txt
python run.py
```
*API e WebSockets disponíveis em `http://localhost:8000`.*

### 2. Iniciar o Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev
```
*Interface acessível em `http://localhost:3000`.*

### 3. Execução via Docker Compose
```bash
docker-compose up --build
```
