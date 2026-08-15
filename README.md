# ( NOTHING ) QOBUZ-DL // HIGH-RES AUDIO ENGINE

> **Edição Especial com Design System Nothing OS**, processamento ao vivo com espectro de frequência dot-matrix, configurações modulares avançadas e gerenciador de filas em lote para download de faixas e álbuns em **FLAC 24-Bit / 192 kHz (Lossless)**.

---

## ✨ Principais Melhorias Implementadas

### 1. 🔴 Estética Nothing OS (Design System)
- **Tipografia Dot-Matrix & Monospace**: Títulos, crachás de qualidade Hi-Res e indicadores com estilo Nothing Dot.
- **Paleta Minimalista & Alto Contraste**: Fundo *Pure Void Black* (`#000000`), cartões translúcidos com *glassmorphism* (`backdrop-filter: blur(24px)`), bordas sutis e acento vermelho icônico da Nothing (`#D71921`).
- **Interface Glyph Interativa**: Linhas LED no topo que pulsam em tempo real durante downloads ativos.
- **Widgets em Squircles**: Cantos arredondados (`border-radius: 28px`), botões táteis tipo pílula e interruptores Nothing.

### 2. ⚡ Processamento ao Vivo & Visualizador de Frequência
- **Hero Card do Stream Ativo**: Visualização da capa com efeito vinil translúcido, artista, álbum, formato de áudio (`24-Bit / 192 kHz FLAC • Lossless`).
- **Barra de Progresso Dotted LED**: Segmentos luminosos com porcentagem em tempo real e indicação da fase atual (`RESOLVING` ➔ `DOWNLOADING` ➔ `EMBEDDING ART` ➔ `SYNCING LYRICS` ➔ `FINALIZING`).
- **Espectro de Frequência Dot-Matrix**: Visualizador reativo de áudio em tempo real renderizado via Canvas em 60 FPS.
- **Métricas em 4 Widgets**: Velocidade instantânea (`MB/s`), Baixado / Total (`MB`), Tempo Restante Estimado (`ETA`) e Fase do Processamento.

### 3. ⚙️ Central de Configurações Modular
- **01 // Conta & Autenticação**: E-mail, Senha, User Auth Token, App ID oficial e botão de **Teste de Conexão em tempo real**.
- **02 // Áudio & Qualidade FLAC**: Seletor de qualidade padrão (24/192, 24/96, 16/44.1, MP3 320), resolução da capa embutida (até resolução máxima original), embutimento de letras sincronizadas `.LRC` e normalização de volume ReplayGain.
- **03 // Pastas & Nomenclatura**: Templates dinâmicos customizáveis (`{artist}`, `{album}`, `{year}`, `{quality}`, `{track_number}`, `{title}`), sanitização FAT32/exFAT para cartões SD/DAP e **Painel de Pré-visualização do Caminho em Tempo Real**.
- **04 // Desempenho & Concorrência**: Número de workers simultâneos (1 a 16), tamanho do buffer de stream e política de sobreposição.
- **05 // Integrações**: Suporte a notificações e upload automático no Telegram e Webhooks do Discord.

---

## 🚀 Como Executar

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Iniciar o servidor
python run.py
```

Acesse no navegador: **`http://localhost:8000`**

---

## 📂 Estrutura do Projeto

```
qobuz_nothing/
├── app/
│   ├── main.py              # FastAPI app & WebSockets para eventos ao vivo
│   ├── config_manager.py    # Gerenciador de configurações com persistência JSON
│   ├── qobuz_service.py     # Cliente Qobuz e pipeline de download/tags
│   ├── progress.py          # Broker de progresso ao vivo e espectro de áudio
│   ├── queue_manager.py     # Pool assíncrono de workers e fila de downloads
│   ├── utils_delivery.py    # Integrações com Telegram e Discord
│   └── static/
│       ├── index.html       # Interface Nothing OS completa
│       ├── css/nothing.css  # Design System Nothing (Dot Matrix, Glass, Red)
│       └── js/app.js        # Lógica reativa com WebSockets e Canvas Spectrum
├── qobuz_dl/
│   ├── constants.py
│   ├── exceptions.py
│   └── utils.py
├── run.py                   # Script de inicialização rápida
├── requirements.txt         # Dependências do projeto
└── README.md
```
