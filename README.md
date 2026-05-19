# qobuz-dl Master Edition

> **The Ultimate Lossless & Hi-Res Music Downloader for Qobuz**
> Fork aprimorado com letras automáticas, tradução via DeepL, Radar de novidades, sincronização bidirecional de playlists e muito mais.

[![Version](https://img.shields.io/badge/version-2.2.4.12-blue)](https://github.com/kaduvercosa/qobuz-dl)
[![Python](https://img.shields.io/badge/python-%3E%3D3.6-green)](https://www.python.org/)
[![License: GPL](https://img.shields.io/badge/license-GPL-orange)](LICENSE)
[![PyPI](https://img.shields.io/badge/PyPI-qobuz--dl--master-blueviolet)](https://pypi.org/project/qobuz-dl-master/)

---

## Índice

- [Funcionalidades](#funcionalidades)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Comandos](#comandos)
- [Opções Avançadas](#opções-avançadas)
- [Formatação de Nomes](#formatação-de-nomes)
- [Arquitetura do Projeto](#arquitetura-do-projeto)
- [Docker](#docker)
- [Google Colab](#google-colab)

---

## Funcionalidades

### Download de Áudio
- Suporte a **MP3 (320kbps)**, **FLAC 16-bit 44.1kHz (CD)**, **FLAC 24-bit <96kHz (Hi-Res)** e **FLAC 24-bit >96kHz (Hi-Res máximo)**
- Download de **faixas**, **álbuns**, **playlists**, **artistas** e **gravadoras** inteiros via URL do Qobuz
- Fallback de qualidade automático: se a qualidade solicitada não estiver disponível, o programa usa a melhor alternativa
- Downloads paralelos com número configurável de threads (`max_workers`)
- Atraso configurável entre downloads (`--delay`) para evitar bloqueios por rate-limit
- Suporte a **Digital Booklets** (PDFs de encartes) com flag `--booklet-only`
- Geração automática de playlists `.m3u` com ordenação fiel à playlist do Qobuz

### Metadados & Tags
- Tagging completo de FLAC e MP3 via `mutagen`: álbum, artista, título, data, gênero, compositor, ISRC, UPC, copyright, gravadora, número de faixa/disco, ReplayGain
- Embedding de capa (cover art) em alta resolução diretamente no arquivo de áudio
- Tags customizadas de ID Qobuz (`QOBUZTRACKID`, `QOBUZALBUMID`) para rastreamento interno
- Suporte a metadados de **múltiplos discos** com prefixo e formato configuráveis
- Geração de arquivo `Digital Booklet.txt` com créditos e resenha do álbum
- Controle granular: cada campo de tag pode ser desabilitado individualmente via flags `--no-*-tag`

### Letras Automáticas
- Busca letras sincronizadas (LRC) via **LRCLIB** como fonte primária
- Fallback para **Genius** (requer token de API) para letras não encontradas
- Tradução automática via **DeepL API** para qualquer idioma alvo (padrão: PT-BR)
- Detecção automática de idioma para evitar traduzir letras já no idioma alvo
- Injeção de letras em **FLAC** (`LYRICS`, `LYRICS_SYNCED`) e **MP3** (`USLT`)
- Geração de arquivos `.lrc` externos ao lado de cada faixa

### Retro Tagger (Injeção Retroativa)
- Comando `lyrics <dir>`: varre uma pasta local e injeta letras em arquivos FLAC/MP3 **já existentes** sem necessidade de re-download
- Modo `fix-lyrics <dir>`: interface interativa para corrigir letras com problemas (faltantes, erradas ou sem tradução) arquivo a arquivo
- Operação com multithreading para processar grandes bibliotecas rapidamente
- Flag `--overwrite` para forçar substituição de letras já existentes

### Radar (Vigilância de Novidades)
- Integração com **MusicButler RSS** para monitorar novos lançamentos dos artistas favoritos
- Compara lançamentos do RSS com o histórico local do banco de dados
- Busca automaticamente no Qobuz e baixa os álbuns novos encontrados
- Envia notificações via **Webhook** (n8n, Make.com, etc.) a cada novo download
- Link RSS salvo permanentemente no `config.ini` após o primeiro uso

### Sincronização de Playlists
- Comando `sync-playlist` / `sp`: sincronização **bidirecional** entre uma pasta local e uma playlist do Qobuz
  - Detecta faixas da playlist online que não existem localmente e as baixa
  - Detecta faixas locais que foram removidas da playlist online e pergunta ao usuário antes de deletar
  - Identifica faixas por `QOBUZTRACKID` nos metadados para correspondência exata

### Banco de Dados Local
- Banco SQLite (`qobuz_dl.db`) que registra todos os downloads para evitar duplicatas
- Migração automática de versões anteriores do schema
- Comando `stats` para exibir estatísticas: total de faixas, álbuns, artistas únicos e distribuição de qualidade
- Comando `--sync-db <dir>` para reconstruir o banco a partir de arquivos locais existentes (Reverse Lookup via tags)
- Comando `--purge` para limpar todo o histórico

### Modos de Operação
- **`dl` (Input Mode):** recebe uma ou mais URLs diretamente, ou um arquivo `.txt` com uma URL por linha
- **`lucky` (Lucky Mode):** busca no Qobuz por uma query de texto e baixa o primeiro (ou N) resultado(s)
- **`i` (Interactive Mode):** modo interativo com seleção via terminal para buscar e escolher o que baixar
- **Integração com Last.fm:** aceita URLs de playlists do Last.fm e converte automaticamente em downloads

### Outras Funcionalidades
- Verificação automática de atualizações ao iniciar
- **Blacklist de palavras-chave** (`blacklist.txt`): pula downloads que contenham termos indesejados (ex: "karaoke", "live")
- **Smart Discography**: filtra álbuns de spam/irrelevantes ao baixar toda a discografia de um artista
- Limpeza automática de arquivos `.tmp` em caso de interrupção
- Suporte a **caminhos longos no Windows** (prefixo `\\?\`)
- Compatibilidade com **Docker** e **Google Colab**
- Wizard de configuração interativo para primeiro uso

---

## Instalação

### Via PyPI (Recomendado)
```bash
pip install qobuz-dl-master
```

### Via código-fonte
```bash
git clone https://github.com/kaduvercosa/qobuz-dl.git
cd qobuz-dl
pip install -r requirements.txt
pip install .
```

### Via Docker
```bash
docker pull kaduvercosa/qobuz-dl:latest
docker run -it -v /sua/pasta/musica:/downloads kaduvercosa/qobuz-dl
```

---

## Configuração

Na primeira execução, o wizard interativo será iniciado automaticamente:

```bash
qobuz-dl
```

O wizard perguntará:
1. **E-mail** da conta Qobuz
2. **Auth Token** do navegador (F12 → Storage → Local Storage → `localuser` → `token`)  
   > ⚠️ A API do Qobuz bloqueou login direto por senha para apps de terceiros. O token do navegador é obrigatório.
3. Se deseja baixar letras automaticamente
4. Idioma alvo para tradução (ex: `PT-BR`, `EN-US`)
5. Chave da **DeepL API** (opcional, para tradução)
6. Token do **Genius** (opcional, como fallback de letras)
7. Chave de API de **IA** para Smart Playlists (OpenAI ou Gemini — opcional)
8. URL de **Webhook** para notificações (n8n / Make.com — opcional)
9. Pasta de destino dos downloads
10. Formato de nome de pasta
11. Qualidade padrão

O arquivo de configuração fica salvo em:
- **Linux/macOS:** `~/.config/qobuz-dl/config.ini`
- **Windows:** `%APPDATA%\qobuz-dl\config.ini`

Para reconfigurar a qualquer momento:
```bash
qobuz-dl -r
```

---

## Comandos

### Download direto por URL
```bash
qobuz-dl dl https://play.qobuz.com/album/0060254723893
qobuz-dl dl https://play.qobuz.com/artist/123456
qobuz-dl dl https://play.qobuz.com/playlist/12345678
```

Múltiplas URLs de uma vez:
```bash
qobuz-dl dl URL1 URL2 URL3
```

Via arquivo de texto (uma URL por linha):
```bash
qobuz-dl dl lista.txt
```

### Modo interativo
```bash
qobuz-dl i
qobuz-dl i --limit 50
```

### Modo Lucky (busca por texto)
```bash
qobuz-dl lucky "Pink Floyd Dark Side of the Moon"
qobuz-dl lucky --type track --number 5 "beethoven symphony"
```

### Sincronização de Playlist
```bash
qobuz-dl sp https://play.qobuz.com/playlist/12345
qobuz-dl sp https://play.qobuz.com/playlist/12345 --yes
```

### Injeção de Letras em Biblioteca Existente
```bash
qobuz-dl lyrics /caminho/para/musicas
qobuz-dl lyrics /caminho/para/musicas --overwrite
```

### Correção Interativa de Letras
```bash
qobuz-dl fix-lyrics /caminho/para/musicas
```

### Radar (Novos Lançamentos via MusicButler)
```bash
qobuz-dl radar
```

### Estatísticas da Biblioteca
```bash
qobuz-dl stats
```

### Reconstruir Banco de Dados
```bash
qobuz-dl --sync-db /caminho/para/musicas
```

### Gerenciar Configuração
```bash
qobuz-dl --show-config   # exibe o config.ini atual
qobuz-dl --purge         # limpa o banco de downloads
qobuz-dl -r              # reconfigura do zero
```

---

## Opções Avançadas

| Flag | Descrição |
|---|---|
| `-q, --quality` | Qualidade: `5` (MP3), `6` (CD), `7` (24-bit), `27` (Hi-Res máx) |
| `-d, --directory` | Pasta de destino dos downloads |
| `--no-db` | Ignora o banco de dados (permite re-download) |
| `--no-m3u` | Não gera arquivo `.m3u` para playlists |
| `--albums-only` | Ignora singles, EPs e compilações |
| `--no-fallback` | Não faz fallback de qualidade (pula se indisponível) |
| `--og-cover` | Salva capa em resolução original |
| `--no-cover` | Não salva capa |
| `--embed-art` | Embute capa nos metadados do arquivo |
| `--smart-discography` | Filtra álbuns irrelevantes ao baixar discografias |
| `--delay <segundos>` | Aguarda N segundos entre downloads |
| `--no-lyrics` | Desativa o download de letras para esta sessão |
| `--booklet-only` | Baixa apenas os PDFs de encartes digitais |
| `--native-lang` | Mantém metadados no idioma original da conta |
| `--no-credits` | Não gera o arquivo de créditos `Digital Booklet.txt` |
| `--blacklist <arquivo>` | Arquivo com palavras-chave para pular downloads |
| `--no-lrc-files` | Não gera arquivos `.lrc` externos |
| `--folder-format` | Formato customizado para nome de pasta |
| `--track-format` | Formato customizado para nome de faixa |

### Controle de Tags (flags `--no-*-tag`)

Cada campo de metadado pode ser desabilitado individualmente:
`--no-album-artist-tag`, `--no-track-artist-tag`, `--no-release-date-tag`, `--no-genre-tag`, `--no-track-number-tag`, `--no-disc-number-tag`, `--no-composer-tag`, `--no-explicit-tag`, `--no-copyright-tag`, `--no-label-tag`, `--no-upc-tag`, `--no-isrc-tag`

---

## Formatação de Nomes

Pastas e faixas podem ser formatadas com variáveis entre chaves:

### Variáveis disponíveis para pastas (`--folder-format`)
| Variável | Descrição |
|---|---|
| `{artist}` | Artista principal |
| `{album}` | Título do álbum |
| `{year}` | Ano de lançamento |
| `{bit_depth}` | Profundidade de bits (ex: `24`) |
| `{sampling_rate}` | Taxa de amostragem (ex: `96`) |
| `{label}` | Gravadora |
| `{release_type}` | Tipo: `Album`, `EP`, `Single` |
| `{format}` | Formato: `FLAC`, `MP3` |

### Variáveis disponíveis para faixas (`--track-format`)
| Variável | Descrição |
|---|---|
| `{track_number}` | Número da faixa |
| `{track_title}` | Título da faixa |
| `{track_artist}` | Artista da faixa |
| `{disc_number}` | Número do disco |
| `{isrc}` | Código ISRC |

**Exemplos:**
```
# Pasta com qualidade Hi-Res
{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]

# Faixa com número de disco
{disc_number}.{track_number} - {track_title}

# Subpastas com barra
{artist}/{year} - {album}
```

> O programa valida as variáveis no início da execução e sugere correções de typos automaticamente.

---

## Arquitetura do Projeto

```
qobuz_dl/
├── __init__.py          # Versão do pacote
├── __main__.py          # Ponto de entrada via `python -m qobuz_dl`
├── cli.py               # Parsing de argumentos, wizard de config, roteamento de comandos
├── commands.py          # Definição de todos os subcomandos e flags via argparse
├── core.py              # Classe principal QobuzDL: modos interativo, lucky, download por URL
├── downloader.py        # Motor de download: AES decrypt, progresso, paralelismo
├── qopy.py              # Cliente da API REST do Qobuz: autenticação, busca, stream URLs
├── metadata.py          # Escrita de tags FLAC/MP3 e embedding de capa via mutagen
├── lyrics_engine.py     # Motor de letras: LRCLIB, Genius, tradução DeepL
├── retro_tagger.py      # Injeção retroativa de letras em bibliotecas existentes
├── radar.py             # Vigilância de novos lançamentos via MusicButler RSS
├── sync.py              # Reconstrução do banco de dados a partir de arquivos locais
├── sync_playlist.py     # Sincronização bidirecional pasta local ↔ playlist Qobuz
├── lastfm_parser.py     # Parser de playlists do Last.fm (HTML scraping)
├── db.py                # Banco SQLite: histórico, deduplicação, migração, estatísticas
├── bundle.py            # Extração dinâmica de App ID e secrets da API do Qobuz
├── settings.py          # Dataclass QobuzDLSettings com todas as opções
├── utils.py             # Helpers: geração de M3U, formatação de nomes, paths
├── constants.py         # Constantes: formatos padrão de pasta/faixa
├── color.py             # Constantes de cores ANSI para o terminal
└── exceptions.py        # Exceções customizadas (AuthenticationError, NonStreamable, etc.)
```

---

## Docker

Um `Dockerfile` está incluído para uso sem instalação local:

```bash
# Build da imagem
docker build -t qobuz-dl .

# Execução com volume
docker run -it \
  -v /sua/pasta:/downloads \
  -v ~/.config/qobuz-dl:/root/.config/qobuz-dl \
  qobuz-dl dl https://play.qobuz.com/album/...
```

O workflow de CI/CD (`.github/workflows/docker.yml`) publica automaticamente a imagem Docker a cada release.

---

## Google Colab

Dois notebooks estão disponíveis para uso no Google Colab sem qualquer instalação local:

- **`Qobuz_Master_Colab.ipynb`** — versão completa com todas as funcionalidades
- **`Qobuz_Ultimate_Colab.ipynb`** — versão simplificada para uso rápido

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kaduvercosa/qobuz-dl/blob/master/Qobuz_Master_Colab.ipynb)

---

## Dependências

| Pacote | Finalidade |
|---|---|
| `aiohttp` / `aiofiles` | Requisições HTTP assíncronas e I/O de arquivos |
| `mutagen` | Leitura e escrita de tags FLAC/MP3 |
| `pycryptodome` | Descriptografia AES dos streams de áudio |
| `tqdm` | Barra de progresso no terminal |
| `pathvalidate` | Sanitização de nomes de arquivos e pastas |
| `beautifulsoup4` | Parsing HTML (Last.fm) |
| `questionary` | Interface interativa de perguntas no terminal |
| `pick` | Seletor de itens no modo interativo |
| `lyricsgenius` | Busca de letras via API do Genius |
| `langdetect` | Detecção automática de idioma das letras |
| `deepl` | Tradução automática via DeepL API oficial |
| `colorama` | Suporte a cores ANSI no Windows |

---

## Licença

Este projeto é distribuído sob a **GNU General Public License (GPL)**. Consulte o arquivo [LICENSE](LICENSE) para os termos completos.

---

> **Aviso:** Este software é destinado exclusivamente para uso pessoal de conteúdo ao qual o usuário possui assinatura ativa. O uso para distribuição não autorizada de conteúdo protegido por direitos autorais é de responsabilidade exclusiva do usuário.
