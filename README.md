# qobuz-dl Master Edition

> **The Ultimate Lossless & Hi-Res Music Downloader for Qobuz**
> Fork aprimorado com letras automáticas, tradução via DeepL, Radar de novidades, sincronização bidirecional de playlists, ReplayGain nativo, suporte a Roon/DAP e muito mais.

[![Version](https://img.shields.io/pypi/v/qobuz-dl-master?style=plastic&color=fedcba)](https://pypi.org/project/qobuz-dl-master/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.6-green)](https://www.python.org/)
[![License: GPL](https://img.shields.io/badge/license-GPL-orange)](LICENSE)

-----

## Índice

- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
  - [Windows](#-windows)
  - [macOS](#-macos)
  - [Linux](#-linux)
  - [iOS / iPadOS (iSH Shell)](#-ios--ipados-ish-shell)
  - [Android (Termux)](#-android-termux)
  - [Docker](#-docker)
  - [Google Colab](#-google-colab)
- [Configuração Inicial](#configuração-inicial)
  - [Localização do config.ini](#localização-do-configini)
  - [Obtendo o Auth Token](#obtendo-o-auth-token)
- [Comandos e Modos de Uso](#comandos-e-modos-de-uso)
  - [dl — Download por URL](#dl--download-por-url)
  - [interactive — Modo Interativo](#interactive--modo-interativo)
  - [lucky — Busca e Baixa](#lucky--busca-e-baixa)
  - [lyrics — Injeção Retroativa de Letras](#lyrics--injeção-retroativa-de-letras)
  - [fix-lyrics — Corretor Interativo de Letras](#fix-lyrics--corretor-interativo-de-letras)
  - [sync-playlist — Sincronização Bidirecional](#sync-playlist--sincronização-bidirecional)
  - [radar — Vigilância de Novidades](#radar--vigilância-de-novidades)
  - [stats — Estatísticas da Biblioteca](#stats--estatísticas-da-biblioteca)
  - [ost_hunter — Trilhas Sonoras](#ost_hunter--trilhas-sonoras)
  - [Comandos Globais](#comandos-globais)
- [Opções Avançadas](#opções-avançadas)
- [Controle de Tags](#controle-de-tags)
- [Opções de Capa](#opções-de-capa)
- [Downloads Paralelos](#downloads-paralelos)
- [Formatação de Nomes](#formatação-de-nomes)
- [Funcionalidades em Detalhe](#funcionalidades-em-detalhe)
- [Arquitetura do Projeto](#arquitetura-do-projeto)
- [Dependências](#dependências)

-----

## Pré-requisitos

> ⚠️ **Obrigatório:** Uma **assinatura ativa** do Qobuz (Studio ou acima para Hi-Res).

- **Python 3.6+**
- **FFmpeg** — necessário para download segmentado e remuxagem. Deve estar instalado e disponível no `PATH`.
- **Auth Token do Qobuz** — a API do Qobuz bloqueou login direto por senha para apps de terceiros. É necessário extrair o token do navegador (veja [Obtendo o Auth Token](#obtendo-o-auth-token)).

-----

## Instalação

### 🖥️ Windows

#### Via PyPI (recomendado)

1. Instale o [Python 3.10+](https://www.python.org/downloads/) (marque a opção **“Add Python to PATH”** durante a instalação).
1. Instale o [FFmpeg](https://ffmpeg.org/download.html) e adicione-o ao PATH do sistema.
1. Abra o **Prompt de Comando** (cmd) ou **PowerShell** e execute:

```cmd
pip install qobuz-dl-master
```

1. Verifique a instalação:

```cmd
qobuz-dl --help
```

> **Nota sobre caminhos longos no Windows:** O programa adiciona automaticamente o prefixo `\\?\` para suportar caminhos com mais de 260 caracteres. Para habilitar definitivamente no Windows 10/11, vá em: *Configurações → Sistema → Para desenvolvedores → Ativar suporte a caminhos longos*.

#### Via código-fonte

```cmd
git clone https://github.com/kaduvercosa/qobuz-dl.git
cd qobuz-dl
pip install -r requirements.txt
pip install .
```

-----

### 🍎 macOS

#### Via PyPI (recomendado)

1. Instale o [Homebrew](https://brew.sh) caso ainda não tenha.
1. Instale Python e FFmpeg:

```bash
brew install python ffmpeg
```

1. Instale o qobuz-dl:

```bash
pip3 install qobuz-dl-master
```

1. Se o comando `qobuz-dl` não for encontrado após a instalação, adicione o diretório de scripts do pip ao seu PATH:

```bash
# Adicione ao ~/.zshrc ou ~/.bash_profile
export PATH="$PATH:$(python3 -m site --user-base)/bin"
```

#### Via código-fonte

```bash
git clone https://github.com/kaduvercosa/qobuz-dl.git
cd qobuz-dl
pip3 install -r requirements.txt
pip3 install .
```

-----

### 🐧 Linux

#### Debian / Ubuntu / Pop!_OS

```bash
# Instalar dependências do sistema
sudo apt update
sudo apt install python3 python3-pip ffmpeg -y

# Instalar o qobuz-dl
pip3 install qobuz-dl-master
```

Se o pip bloquear por “externally managed environment” (Python 3.11+):

```bash
pip3 install qobuz-dl-master --break-system-packages
```

#### Fedora / RHEL / CentOS

```bash
sudo dnf install python3 python3-pip ffmpeg -y
pip3 install qobuz-dl-master
```

#### Arch Linux / Manjaro

```bash
sudo pacman -S python python-pip ffmpeg
pip install qobuz-dl-master
```

#### Via código-fonte (qualquer distro)

```bash
git clone https://github.com/kaduvercosa/qobuz-dl.git
cd qobuz-dl
pip3 install -r requirements.txt
pip3 install .
```

-----

### 📱 iOS / iPadOS (iSH Shell)

> O iSH executa um ambiente Alpine Linux emulado no dispositivo. A instalação padrão do pip falha porque o Alpine não tem compiladores C/Rust instalados por padrão. Siga os passos abaixo **na ordem exata**.

1. Instale o [iSH Shell](https://ish.app) pela App Store (gratuito)

1.1 Abra o iSH e execute:

```bash
# 1. Atualizar repositórios e instalar dependências essenciais
apk update
apk add python3 py3-pip
pip install --upgrade pip setuptools wheel pybind11 --ignore-installed --no-cache-dir
apk add gcc musl-dev python3-dev libffi-dev make
apk add py3-aiohttp py3-pycryptodome py3-beautifulsoup4 py3-lxml py3-pillow

# 2. Instalar dependências Python que requerem compilação prévia
python3 -m pip install --upgrade "typing-extensions>=4.0.0" beautifulsoup4 langdetect lyricsgenius mutagen

# 3. Instalar o qobuz-dl (com flag para Alpine moderno)
pip install qobuz-dl-master
```

1. Verifique a instalação:

```bash
qobuz-dl --help
```

> **Dicas para iOS:**
> 
> - O arquivo `config.ini` é salvo em `~/Documents/qobuz-dl/config.ini` (pasta Documents do iSH) para evitar erros de permissão.
> - O banco de dados SQLite também fica em `~/Documents/qobuz-dl/qobuz_dl.db`.
> - Para acessar os arquivos baixados no app Arquivos do iOS, certifique-se de que o iSH tem acesso à pasta desejada nas configurações do app.
> - Downloads lentos são normais no iSH por ser emulação. Use `-q 6` (FLAC CD) para melhor desempenho.

-----

### 🤖 Android (Termux)

1. Instale o [Termux](https://f-droid.org/en/packages/com.termux/) pelo F-Droid (recomendado).
1. Execute:

```bash
# Atualizar pacotes
pkg update && pkg upgrade -y

# Instalar dependências
pkg install python ffmpeg -y

# Instalar o qobuz-dl
pip install qobuz-dl-master
```

1. Para armazenar downloads no armazenamento do Android:

```bash
termux-setup-storage
# Os arquivos ficarão acessíveis em ~/storage/shared/
qobuz-dl dl URL -d ~/storage/shared/Music/Qobuz
```

-----

### 🐳 Docker

Ideal para uso em servidores ou NAS (Synology, Unraid, TrueNAS, etc.) sem poluir o ambiente Python do sistema.

#### Usando a imagem oficial do Docker Hub

```bash
docker pull kaduvercosa/qobuz-dl:latest

# Executar com volume para a pasta de músicas
docker run -it \
  -v /sua/pasta/musica:/downloads \
  -v ~/.config/qobuz-dl:/root/.config/qobuz-dl \
  kaduvercosa/qobuz-dl dl https://play.qobuz.com/album/...
```

#### Build local a partir do código-fonte

```bash
git clone https://github.com/kaduvercosa/qobuz-dl.git
cd qobuz-dl

# Construir a imagem
docker build -t qobuz-dl .

# Executar
docker run -it \
  -v /sua/pasta/musica:/downloads \
  -v ~/.config/qobuz-dl:/root/.config/qobuz-dl \
  qobuz-dl dl https://play.qobuz.com/album/...
```

#### docker-compose (uso recorrente)

```yaml
version: "3.8"
services:
  qobuz-dl:
    image: kaduvercosa/qobuz-dl:latest
    volumes:
      - /sua/pasta/musica:/downloads
      - ~/.config/qobuz-dl:/root/.config/qobuz-dl
    stdin_open: true
    tty: true
```

```bash
docker-compose run qobuz-dl dl https://play.qobuz.com/album/...
```

-----

### ☁️ Google Colab

Dois notebooks prontos estão incluídos no repositório para uso sem qualquer instalação local:

|Notebook                    |Descrição                                   |
|----------------------------|--------------------------------------------|
|`Qobuz_Master_Colab.ipynb`  |Versão completa com todas as funcionalidades|
|`Qobuz_Ultimate_Colab.ipynb`|Versão simplificada para uso rápido         |

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kaduvercosa/qobuz-dl/blob/master/Qobuz_Master_Colab.ipynb)

> Os notebooks já incluem todas as células de instalação. Basta abrir, inserir suas credenciais e executar.

-----

## Configuração Inicial

Na **primeira execução**, o wizard interativo é iniciado automaticamente:

```bash
python3 -m qobuz_dl ou qdl ou qobuz-dl
```

O wizard perguntará, em ordem:

|# |Campo             |Obrigatório|Descrição                                                               |
|--|------------------|-----------|------------------------------------------------------------------------|
|1 |E-mail            |Sim        |E-mail da conta Qobuz                                                   |
|2 |Auth Token        |Sim        |Token extraído do navegador (veja abaixo)                               |
|3 |Letras automáticas|Não        |Ativar busca de letras no download                                      |
|4 |Idioma alvo       |Não        |Ex: `PT-BR`, `EN-US` (para tradução DeepL)                              |
|5 |DeepL API Key     |Não        |Chave da API DeepL para tradução automática                             |
|6 |Token do Genius   |Não        |Fallback de letras via Genius API                                       |
|7 |Chave de IA       |Não        |OpenAI ou Gemini (para Smart Playlists)                                 |
|8 |URL de Webhook    |Não        |n8n, Make.com, etc. para notificações                                   |
|9 |Pasta de destino  |Sim        |Onde os arquivos serão salvos                                           |
|10|Formato de pasta  |Não        |Padrão: `{album_artist} - {album_title} ({year}) [{format} {bit_depth}]`|
|11|Qualidade padrão  |Sim        |`5` MP3, `6` FLAC CD, `7` Hi-Res, `27` Hi-Res máximo                    |

Para **reconfigurar** a qualquer momento:

```bash
qobuz-dl -r
# ou
qobuz-dl --reset
```

Para **ver a configuração atual**:

```bash
qobuz-dl -sc
# ou
qobuz-dl --show-config
```

### Localização do config.ini

|Sistema      |Caminho                                                  |
|-------------|---------------------------------------------------------|
|Linux / macOS / ISH |`~/.config/qobuz-dl/config.ini`                          |
|Windows      |`%APPDATA%\qobuz-dl\config.ini`                          |
|iOS    |`~/Documents/qobuz-dl/config.ini`                        |
|Docker       |`/root/.config/qobuz-dl/config.ini` (dentro do container)|

### Obtendo o Auth Token

A API do Qobuz bloqueou login direto por senha para aplicações de terceiros. O Auth Token é obrigatório.

**Passo a passo (qualquer navegador):**

1. Acesse [play.qobuz.com](https://play.qobuz.com) e faça login.
1. Pressione **F12** para abrir o DevTools.
1. Vá na aba **Application** (Chrome/Edge) ou **Storage** (Firefox).
1. No painel esquerdo, expanda **Local Storage** → `https://play.qobuz.com`.
1. Procure pela chave `localuser` ou `user-auth-token`.
1. Copie o valor do campo `token` (string longa).
1. Cole no wizard quando solicitado.

> **Alternativa via aba Network:** No DevTools, vá em Network, faça qualquer ação no player e filtre por “user/login” ou “stream”. Procure o header `X-User-Auth-Token` nas requisições.

-----

## Comandos e Modos de Uso

O alias `qdl` funciona como atalho para `qobuz-dl` em todos os sistemas.

-----

### `dl` — Download por URL

Baixa diretamente por URL do Qobuz ou do Last.fm.

```bash
qobuz-dl dl <URL ou ARQUIVO> [opções]
```

**Exemplos:**

```bash
# Baixar um álbum
qobuz-dl dl https://play.qobuz.com/album/0060254723893

# Baixar uma faixa
qobuz-dl dl https://play.qobuz.com/track/123456789

# Baixar toda a discografia de um artista
qobuz-dl dl https://play.qobuz.com/artist/123456

# Baixar uma playlist
qobuz-dl dl https://play.qobuz.com/playlist/12345678

# Baixar todo o catálogo de uma gravadora
qobuz-dl dl https://play.qobuz.com/label/123

# Baixar a partir de uma playlist do Last.fm
qobuz-dl dl https://www.last.fm/user/seuusuario/playlists/12345

# Múltiplas URLs de uma vez
qobuz-dl dl URL1 URL2 URL3

# Via arquivo de texto (uma URL por linha)
qobuz-dl dl lista_de_downloads.txt

# Baixar em qualidade Hi-Res para pasta específica
qobuz-dl dl URL -q 27 -d /mnt/musicas/hires

# Baixar discografia filtrando álbuns relevantes
qobuz-dl dl URL --smart-discography

# Baixar com blacklist de palavras indesejadas
qobuz-dl dl URL -b blacklist.txt

# Baixar apenas os PDFs/booklets sem o áudio
qobuz-dl dl URL --booklet-only

# Baixar com delay de 3s entre faixas (anti-ban)
qobuz-dl dl URL --delay 3
```

> **Memória de arquivo de texto:** Ao usar um `.txt` como fila, o programa marca cada link com `[CONCLUÍDO]` após o download. Se interrompido, basta rodar novamente — os links concluídos são pulados automaticamente.

-----

### `interactive` — Modo Interativo

Aliases: `i`, `fun`

Abre uma interface de navegação no terminal para buscar e selecionar músicas, álbuns, artistas e favoritos da sua conta.

```bash
qobuz-dl i
qobuz-dl fun
qobuz-dl interactive

# Com limite de resultados
qobuz-dl i --limit 50
```

**Controles:**

- `↑ ↓` — navegar
- `Barra de Espaço` — selecionar múltiplos itens
- `Enter` — confirmar e baixar
- `Esc` / `q` — voltar / sair

-----

### `lucky` — Busca e Baixa

Busca no Qobuz por texto e baixa automaticamente o(s) primeiro(s) resultado(s).

```bash
qobuz-dl lucky "<QUERY>" [opções]
```

**Argumentos:**

|Flag          |Padrão |Descrição                                   |
|--------------|-------|--------------------------------------------|
|`-t, --type`  |`album`|Tipo: `album`, `track`, `artist`, `playlist`|
|`-n, --number`|`1`    |Número de resultados a baixar               |

**Exemplos:**

```bash
# Baixar o primeiro álbum encontrado
qobuz-dl lucky "Daft Punk Discovery"

# Baixar as 3 primeiras faixas encontradas
qobuz-dl lucky -t track -n 3 "Billie Jean"

# Baixar o primeiro artista encontrado
qobuz-dl lucky -t artist "Pink Floyd"

# Baixar os 5 primeiros álbuns com qualidade Hi-Res
qobuz-dl lucky -n 5 -q 7 "beethoven symphony"
```

-----

### `lyrics` — Injeção Retroativa de Letras

Varre uma pasta local com arquivos FLAC/MP3 **já existentes** e injeta letras sincronizadas (e traduzidas) sem precisar re-baixar o áudio.

```bash
qobuz-dl lyrics <DIRETÓRIO> [--overwrite]
```

**Exemplos:**

```bash
# Injetar letras faltantes em toda a biblioteca
qobuz-dl lyrics "/mnt/musicas/Minha Biblioteca"

# Forçar sobrescrever todas as letras (útil após configurar DeepL)
qobuz-dl lyrics "/mnt/musicas" --overwrite

# Windows
qobuz-dl lyrics "C:\Users\Usuario\Music"
```

**O que o comando faz:**

- Busca letras sincronizadas (LRC) via **Musicmath** (fonte principal)
- Fallback para **LRCLIB** se não encontrar
- Traduz automaticamente via **DeepL** se configurado
- Detecta o idioma para não traduzir músicas já no idioma alvo
- Injeta letras em tags FLAC (`LYRICS`, `LYRICS_SYNCED`) e MP3 (`USLT`)
- Gera arquivos `.lrc` externos ao lado de cada faixa
- Processa com multithreading para bibliotecas grandes

-----

### `fix-lyrics` — Corretor Interativo de Letras

Aliases: `fl`

Interface interativa para corrigir letras problemáticas (desincronizadas, incorretas ou sem tradução) arquivo a arquivo.

```bash
qobuz-dl fix-lyrics [DIRETÓRIO]
qobuz-dl fl [DIRETÓRIO]

# Usar o diretório atual
qobuz-dl fl

# Especificar diretório
qobuz-dl fl "/mnt/musicas/Album Especifico"
```

-----

### `sync-playlist` — Sincronização Bidirecional

Aliases: `sp`

Mantém uma pasta local **perfeitamente espelhada** com uma playlist do Qobuz.

- Baixa faixas que estão na playlist online mas faltam localmente
- Detecta faixas locais removidas da playlist online e pergunta antes de deletar
- Identifica faixas por `QOBUZTRACKID` nas tags para correspondência exata

```bash
qobuz-dl sp <URL_DA_PLAYLIST> [opções]
qobuz-dl sync-playlist <URL_DA_PLAYLIST> [opções]
```

**Exemplos:**

```bash
# Sincronizar uma playlist
qobuz-dl sp https://play.qobuz.com/playlist/12345678

# Sincronizar pulando confirmações (modo automático/cron)
qobuz-dl sp https://play.qobuz.com/playlist/12345678 --yes

# Sincronizar para pasta específica
qobuz-dl sp https://play.qobuz.com/playlist/12345678 -d /mnt/musicas/Playlists

# Sincronizar em qualidade Hi-Res
qobuz-dl sp https://play.qobuz.com/playlist/12345678 -q 7
```

> **Lógica de Pasta Inteligente:** Ao usar `-d .` ou um caminho genérico, o programa cria automaticamente uma subpasta com o nome da playlist, evitando a exclusão acidental de arquivos no diretório raiz.

-----

### `radar` — Vigilância de Novidades

Verifica novidades baseadas nos artistas seguidos, e dá a opção de salvar nos favoritos ou adicionar a uma playlist

```bash
qobuz-dl radar
```

-----

### `stats` — Estatísticas da Biblioteca

Exibe estatísticas detalhadas da sua biblioteca baseadas no banco de dados local.

```bash
qobuz-dl stats
```

**Informações exibidas:**

- Total de faixas baixadas
- Total de álbuns únicos
- Total de artistas únicos
- Distribuição por qualidade (MP3 / FLAC CD / Hi-Res 24-bit)

-----

### `ost_hunter` — Trilhas Sonoras

Aliases: `ost`

Busca e baixa seletivamente álbuns de trilhas sonoras (filmes, animes, séries) ou gera playlists OST.

```bash
qobuz-dl ost_hunter "oppenheimer"
qobuz-dl ost "oppenheimer"
```

-----

### Comandos Globais

```bash
# Reconfigurar do zero (wizard)
qobuz-dl -r
qobuz-dl --reset

# Limpar banco de dados (permite re-download de tudo)
qobuz-dl -p
qobuz-dl --purge

# Mostrar configuração atual
qobuz-dl -sc
qobuz-dl --show-config

# Reconstruir banco a partir de arquivos locais (Reverse Lookup)
qobuz-dl --sync-db /caminho/para/musicas

# Ajuda geral
qobuz-dl --help

# Ajuda de um comando específico
qobuz-dl dl --help
qobuz-dl lucky --help
```

-----

## Opções Avançadas

Disponíveis para os comandos `dl`, `i`, `lucky` e `sp`:

|Flag                             |Padrão          |Descrição                                                                     |
|---------------------------------|----------------|------------------------------------------------------------------------------|
|`-q, --quality`                  |`6`             |Qualidade: `5`=MP3 320kbps, `6`=FLAC CD, `7`=24-bit ≤96kHz, `27`=24-bit >96kHz|
|`-d, --directory`                |`QobuzDownloads`|Pasta de destino dos downloads                                                |
|`-ff, --folder-format`           |—               |Padrão de formatação do nome da pasta                                         |
|`-fbff, --fallback-folder-format`|—               |Padrão fallback se o principal falhar                                         |
|`-tf, --track-format`            |—               |Padrão de formatação do nome da faixa                                         |
|`--albums-only`                  |false           |Ignorar singles, EPs e compilações                                            |
|`--no-m3u`                       |false           |Não gerar arquivo `.m3u` para playlists                                       |
|`--no-fallback`                  |false           |Não fazer downgrade de qualidade (pula se indisponível)                       |
|`--no-db`                        |false           |Ignorar o banco de dados (permite re-download)                                |
|`-s, --smart-discography`        |false           |Filtrar álbuns irrelevantes em discografias                                   |
|`--delay <segundos>`             |`0`             |Aguardar N segundos entre downloads (anti-ban)                                |
|`--no-lyrics`                    |false           |Desativar letras para esta sessão                                             |
|`--booklet-only`                 |false           |Baixar apenas booklets e PDFs (sem áudio)                                     |
|`--native-lang`                  |false           |Manter metadados no idioma original da conta                                  |
|`--no-credits`                   |false           |Não gerar o arquivo `Digital Booklet.txt`                                     |
|`--with-credits`                 |false           |Forçar geração do `Digital Booklet.txt`                                       |
|`--no-lrc-files`                 |false           |Não gerar arquivos `.lrc` externos                                            |
|`-b, --blacklist <arquivo>`      |—               |Arquivo com palavras-chave para pular downloads                               |
|`--max-workers <N>`              |`3`             |Número máximo de downloads paralelos                                          |

-----

## Controle de Tags

Cada campo de metadado pode ser desabilitado individualmente:

|Flag                   |Descrição                              |
|-----------------------|---------------------------------------|
|`--no-album-artist-tag`|Não adicionar tag de artista do álbum  |
|`--no-album-title-tag` |Não adicionar tag de título do álbum   |
|`--no-track-artist-tag`|Não adicionar tag de artista da faixa  |
|`--no-track-title-tag` |Não adicionar tag de título da faixa   |
|`--no-release-date-tag`|Não adicionar tag de data de lançamento|
|`--no-media-type-tag`  |Não adicionar tag de tipo de mídia     |
|`--no-genre-tag`       |Não adicionar tag de gênero            |
|`--no-track-number-tag`|Não adicionar tag de número de faixa   |
|`--no-track-total-tag` |Não adicionar tag de total de faixas   |
|`--no-disc-number-tag` |Não adicionar tag de número do disco   |
|`--no-disc-total-tag`  |Não adicionar tag de total de discos   |
|`--no-composer-tag`    |Não adicionar tag de compositor        |
|`--no-explicit-tag`    |Não adicionar tag de conteúdo explícito|
|`--no-copyright-tag`   |Não adicionar tag de copyright         |
|`--no-label-tag`       |Não adicionar tag de gravadora         |
|`--no-upc-tag`         |Não adicionar tag UPC/barcode          |
|`--no-isrc-tag`        |Não adicionar tag ISRC                 |

-----

## Opções de Capa

|Flag                 |Padrão|Opções                                        |Descrição                             |
|---------------------|------|----------------------------------------------|--------------------------------------|
|`-e, --embed-art`    |false |—                                             |Embutir capa nos metadados do arquivo |
|`--no-cover`         |false |—                                             |Não baixar capa                       |
|`--og-cover`         |true |—                                             |Capa em resolução original       |
|`--embedded-art-size`|`org` |`50`, `100`, `150`, `300`, `600`, `max`, `org`|Tamanho da capa embutida              |
|`--saved-art-size`   |`org` |`50`, `100`, `150`, `300`, `600`, `max`, `org`|Tamanho da capa salva em disco        |

### Opções de Múltiplos Discos

|Flag                          |Padrão                                        |Descrição                                        |
|------------------------------|----------------------------------------------|-------------------------------------------------|
|`--multiple-disc-prefix`      |`CD`                                          |Prefixo de pasta para álbuns com múltiplos discos|
|`--multiple-disc-one-dir`     |false                                         |Armazenar todos os discos em um único diretório  |
|`--multiple-disc-track-format`|`{disc_number}.{track_number} - {track_title}`|Formato de faixa para múltiplos discos           |

-----

## Downloads Paralelos

```bash
# Usar 6 threads paralelas
qobuz-dl dl URL --max-workers 6

# Usar 1 thread com delay (modo furtivo)
qobuz-dl dl URL --max-workers 1 --delay 5
```

> Com `--delay`, o programa usa logging estático (sem barras de progresso animadas conflitantes). Com múltiplas threads, exibe tamanhos precisos em MB por faixa.

-----

## Formatação de Nomes

### Variáveis para Pastas (`--folder-format` / `-ff`)

|Variável          |Exemplo de saída                                |
|------------------|------------------------------------------------|
|`{album_id}`      |`0060254723893`                                 |
|`{album_title}`   |`Discovery`                                     |
|`{album_artist}`  |`Daft Punk`                                     |
|`{album_genre}`   |`Electronic`                                    |
|`{album_composer}`|`Thomas Bangalter`                              |
|`{label}`         |`Parlophone`                                    |
|`{copyright}`     |`© 2001 Daft Life Ltd`                          |
|`{upc}`           |`724384952518`                                  |
|`{barcode}`       |`724384952518`                                  |
|`{release_date}`  |`2001-03-07`                                    |
|`{year}`          |`2001`                                          |
|`{format}`        |`FLAC`                                          |
|`{bit_depth}`     |`24`                                            |
|`{sampling_rate}` |`96`                                            |
|`{release_type}`  |`Album`, `EP`, `Single`                         |
|`{album_version}` |`Remastered`, `Deluxe Edition`                  |
|`{disc_count}`    |`1`                                             |
|`{track_count}`   |`13`                                            |
|`{ExplicitFlag}`  |`[E]` (vazio se não explícito)                  |
|`{version_tag}`   |` - Live in Heidelberg` (vazio se edição padrão)|

### Variáveis para Faixas (`--track-format` / `-tf`)

|Variável            |Exemplo de saída              |
|--------------------|------------------------------|
|`{track_number}`    |`01`                          |
|`{track_title}`     |`One More Time`               |
|`{track_title_base}`|`One More Time` (sem versão)  |
|`{track_artist}`    |`Daft Punk`                   |
|`{track_composer}`  |`Thomas Bangalter`            |
|`{disc_number}`     |`1`                           |
|`{isrc}`            |`GBDCE0100099`                |
|`{bit_depth}`       |`24`                          |
|`{sampling_rate}`   |`96`                          |
|`{version}`         |`Radio Edit`                  |
|`{year}`            |`2001`                        |
|`{release_date}`    |`2001-03-07`                  |
|`{album_title}`     |`Discovery`                   |
|`{album_artist}`    |`Daft Punk`                   |
|`{ExplicitFlag}`    |`[E]` (vazio se não explícito)|

### Exemplos de Formatação

```bash
# Padrão (FLAC Hi-Res com info técnica)
{album_artist} - {album_title} ({year}) [{format} {bit_depth}]
# → "Daft Punk - Discovery (2001) [FLAC 24]"

# Subdiretórios por tipo de lançamento
{release_type}/{album_artist} - {album_title}
# → "Album/Daft Punk - Discovery"

# Estrutura Artista/Ano - Álbum
{album_artist}/{year} - {album_title}
# → "Daft Punk/2001 - Discovery"

# Com versão do álbum (vazio se edição padrão)
{album_artist} - {album_title}{version_tag}
# → "The National - The Sunset Violent"
# → "The National - The Sunset Violent - Live in Heidelberg"

# Com flag explícito
{album_artist} - {album_title} {ExplicitFlag}
# → "Eminem - The Eminem Show [E]"

# Faixa simples
{track_number} - {track_title}
# → "01 - One More Time"

# Faixa com artista (para playlists)
{track_artist} - {track_title}
# → "Daft Punk - One More Time"

# Multi-disco
{disc_number}.{track_number} - {track_title}
# → "1.01 - One More Time"
```

> O programa valida as variáveis no início e usa `difflib` para sugerir correções em caso de typos.

-----

## Funcionalidades em Detalhe

### Sistema de Download

- **Qualidades suportadas:**
  - `5` — MP3 320kbps
  - `6` — FLAC 16-bit 44.1kHz (Qualidade CD, Lossless)
  - `7` — FLAC 24-bit ≤96kHz (Hi-Res)
  - `27` — FLAC 24-bit >96kHz (Hi-Res máximo)
- **Fallback automático de qualidade:** se a qualidade solicitada não estiver disponível, usa a melhor alternativa
- **Download segmentado + FFmpeg:** contorna limitações do CDN Akamai
- **Downloads paralelos** com número configurável de threads
- **Estado de pasta em 3 estágios:** `[IN PROGRESS]` → `[INCOMPLETE]` → nome final limpo
- **Retomada inteligente:** detecta arquivos existentes e pula automaticamente
- **Anti-ban:** mascaramento de User-Agent e Client Hints do Chrome/Windows (`Sec-Ch-Ua`, `Sec-Fetch-Site`)
- **Playlists ilimitadas:** paginação dinâmica para superar o limite de 50 faixas da API
- **Downloads em lote com estado:** arquivo `.txt` com marcação `[CONCLUÍDO]`

### Letras e Tradução

- Busca via **Musicmath** (letras sincronizadas LRC) como fonte primária
- Fallback para **Genius API** (requer token)
- Tradução automática via **DeepL API** (detecta idioma para não traduzir músicas já no idioma alvo)
- Injeção em tags FLAC (`LYRICS`, `LYRICS_SYNCED`) e MP3 (`USLT`)
- Geração de arquivos `.lrc` externos (desativável via `--no-lrc-files`)

### Metadados e Tags

- Tags completas via `mutagen`: álbum, artista, título, data, gênero, compositor, ISRC, UPC, copyright, gravadora, número de faixa/disco, ReplayGain
- **ReplayGain nativo:** extrai e embute `REPLAYGAIN_TRACK_GAIN` e `REPLAYGAIN_TRACK_PEAK` direto da API do Qobuz
- **Múltiplos artistas:** detecta e divide artistas principais/convidados em tags separadas (compatível com Roon, Plexamp, Kodi)
- **Capa em alta resolução** embutida diretamente no arquivo
- Tags personalizadas `QOBUZTRACKID` e `QOBUZALBUMID` para rastreamento interno

### Banco de Dados

- SQLite local (`qobuz_dl.db`) registra todos os downloads
- Migração automática de versões anteriores do schema
- Reconstrução via `--sync-db` (Reverse Lookup por ISRC/UPC/título nas tags existentes)
- Limpeza via `--purge`

### Digital Booklet

- Arquivo `.txt` com faixas, duração total, créditos e resenha do álbum
- Letras de todas as faixas (texto puro) anexadas automaticamente
- PDFs oficiais (“Goodies”) baixados junto
- Flag `--booklet-only` para baixar apenas esses arquivos sem áudio

### Last.fm

- Aceita URLs de playlists do Last.fm diretamente no comando `dl`
- **Fuzzy Matching matemático** para evitar downloads incorretos:
  - Acima de 75%: aceite automático
  - Abaixo de 60%: ignorado automaticamente
  - Entre 60% e 74%: prompt interativo `[y/n]`

### Caracteres e Compatibilidade de Nomes

- Por padrão, usa caracteres Unicode de largura total (ex: `／`) para substituir caracteres inválidos em sistemas de arquivos
- Opção `legacy_charmap = true` no `config.ini` para usar substituições ASCII clássicas (ex: `/` → `-`)
- Suporte a caminhos longos no Windows (prefixo `\\?\`)

-----

## Arquitetura do Projeto

```
qobuz_dl/
├── __init__.py           # Versão do pacote e exports
├── __main__.py           # Ponto de entrada: python -m qobuz_dl
├── cli.py                # Parsing de argumentos, wizard de configuração,
│                         # roteamento de comandos, detecção de plataforma (iOS)
├── commands.py           # Definição de todos os subcomandos e flags (argparse)
├── core.py               # Classe principal QobuzDL: modos interativo, lucky,
│                         # download por URL, processamento de artistas/gravadoras
├── downloader.py         # Motor de download: AES decrypt, progresso, paralelismo,
│                         # segmentação CDN, remuxagem FFmpeg
├── qopy.py               # Cliente da API REST do Qobuz: autenticação via token,
│                         # busca, obtenção de stream URLs, paginação
├── metadata.py           # Escrita de tags FLAC/MP3 via mutagen, embedding de capa,
│                         # ReplayGain, múltiplos artistas
├── lyrics_engine.py      # Motor de letras: LRCLIB, Genius, tradução DeepL,
│                         # detecção de idioma, geração .lrc
├── retro_tagger.py       # Injeção retroativa de letras em bibliotecas existentes,
│                         # modo fix-lyrics interativo
├── radar.py              # Vigilância de novos lançamentos via MusicButler RSS,
│                         # integração webhook n8n/Make
├── sync.py               # Reconstrução do banco de dados a partir de arquivos locais
│                         # via ISRC/UPC tags (Reverse Lookup)
├── sync_playlist.py      # Sincronização bidirecional pasta local ↔ playlist Qobuz
├── lastfm_parser.py      # Parser de playlists Last.fm (HTML scraping + fuzzy match)
├── db.py                 # Banco SQLite: histórico, deduplicação, migração, stats
├── bundle.py             # Extração dinâmica de App ID e secrets da API do Qobuz
├── settings.py           # Dataclass QobuzDLSettings com todas as opções de config
├── utils.py              # Helpers: geração M3U, formatação de nomes, sanitização
│                         # de paths, algoritmo de matching O(1) para playlists
├── constants.py          # Constantes: formato padrão de pasta e faixa
├── color.py              # Constantes de cores ANSI para terminal
├── exceptions.py         # Exceções customizadas (AuthenticationError,
│                         # NonStreamable, etc.)
└── lid.176.ftz           # Modelo FastText para detecção de idioma das letras
```

-----

## Dependências

|Pacote          |Versão |Finalidade                                   |
|----------------|-------|---------------------------------------------|
|`aiohttp`       |—      |Requisições HTTP assíncronas (API Qobuz)     |
|`aiofiles`      |—      |I/O de arquivos assíncrono                   |
|`mutagen`       |—      |Leitura e escrita de tags FLAC/MP3           |
|`pycryptodome`  |—      |Descriptografia AES dos streams de áudio     |
|`tqdm`          |—      |Barras de progresso no terminal              |
|`pathvalidate`  |—      |Sanitização de nomes de arquivos e pastas    |
|`beautifulsoup4`|—      |Parsing HTML (Last.fm scraping)              |
|`questionary`   |—      |Interface interativa de prompts no terminal  |
|`pick`          |`1.6.0`|Seletor de itens no modo interativo          |
|`lyricsgenius`  |—      |Busca de letras via API do Genius            |
|`langdetect`    |—      |Detecção automática de idioma                |
|`deepl`         |—      |Tradução automática via DeepL API oficial    |
|`colorama`      |—      |Suporte a cores ANSI no Windows              |
|`requests`      |—      |Requisições HTTP síncronas (auxiliar)        |
|`ffmpeg`        |—      |Remuxagem e download segmentado (**sistema**)|

-----

**Blacklist exemplo** (`blacklist.txt`):

```
karaoke
tribute
instrumental version
live at
cover version
```

-----

## Licença

Este projeto é distribuído sob a **GNU General Public License v3 (GPL-3.0-or-later)**. Consulte o arquivo <LICENSE> para os termos completos.

-----

> **Aviso Legal:** Este software é destinado exclusivamente ao uso pessoal de conteúdo ao qual o usuário possui assinatura ativa e válida. O uso para distribuição não autorizada de conteúdo protegido por direitos autorais é de responsabilidade exclusiva do usuário e pode configurar violação de leis de direitos autorais em sua jurisdição.
