# Qobuz-DL Master Edition

[![PyPI version](https://img.shields.io/pypi/v/qobuz-dl-master)](https://pypi.org/project/qobuz-dl-master/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/qobuz-dl-master?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/qobuz-dl-master)

Pesquise, explore e baixe músicas Lossless e Hi-Res do [Qobuz](https://www.qobuz.com/).

**Este é um projeto aprimorado e rico em recursos do projeto original qobuz-dl, projetado para a melhor experiência audiófila. Ele inclui um mecanismo de download resiliente com filtragem anti-spam inteligente, personalização profunda para manter sua biblioteca perfeitamente organizada e suporte amplo e nativo a metadados de música clássica.**

---

## 🆕 O que há de novo na v2.2.0

A atualização **v2.2.0** traz melhorias massivas no processamento de metadados, resiliência de downloads e introduz um poderoso sistema de tradução de letras.

* **Tradução Automática de Letras (`deep-translator`):** O mecanismo de letras agora suporta a tradução automática das letras sincronizadas (`.lrc`) e incorporadas para o idioma de sua preferência, mantendo os timestamps originais intactos e exibindo o texto bilíngue. Use a flag de configuração no `config.ini` ou terminal para definir seu `target_lang` (ex: `pt`, `en`).
* **Download em Lote com Threads Seguras (Thread-Safe):** A lógica de processamento em lote para o download massivo via arquivos `.txt` (onde vários URLs são lidos) foi aprimorada com `threading.Lock()`. Isso previne a "bagunça" no terminal e a corrupção visual durante operações massivas assíncronas, garantindo atualizações seguras da tag `[CONCLUÍDO]` mesmo com `--max_workers` ativados.
* **Tagueamento Retroativo Turbinado (`retro_tagger`):** 
  * Agora você pode forçar a sobrescrita das letras locais existentes usando a nova flag `--overwrite`.
  * O scanner agora usa a tag `Album Artist` primariamente para as buscas no LRCLIB e Genius, reduzindo falsos positivos.
  * O terminal apresenta logs limpos com trava de thread (Thread-safe printing) e um resumo com cores, ideal para execução contínua no iSH Shell/iOS.
* **Tratamento Fino de Erros 404:** Ao detectar que um arquivo ou capa (Cover Art) foi removido dos servidores (Erro 404), o downloader agora não quebra. Ele limpa gentilmente arquivos de tamanho zero (0 KB) que ficaram para trás, avisa no terminal, e prossegue com a fila graciosamente sem loops infinitos de retentativas ("Definitive timeout").

---

## ✨ Recursos

### 🎧 Mecanismo para Audiófilos e Metadados
* **Otimizado para Roon & DAP:** Metadados, artes de capa e letras são meticulosamente formatados para garantir uma integração perfeita e imediata com servidores Roon e Digital Audio Players (Reprodutores de Áudio Digital).
* **Letras Sincronizadas Prontas para Roon:** O mecanismo formata de forma inteligente e incorpora dados `.lrc` com marcação de tempo diretamente nos arquivos de áudio (Comentários Vorbis `[LYRICS]`), garantindo que o Roon exiba letras rolando em estilo karaokê nativamente em sua visualização "Tocando Agora". Se você preferir uma estrutura de pastas minimalista e sem bagunça, pode desativar totalmente a geração de arquivos `.lrc` externos via linha de comando (`--no-lrc-files`) ou `config.ini` (`no_lrc_files = true`), mantendo suas letras sincronizadas puramente incorporadas aos metadados.
* **Controle Massivo de Tags:** O mecanismo de tags refatorado suporta metadados altamente detalhados de música clássica. Quase todas as tags individuais podem ser ativadas/desativadas via argumentos de linha de comando.
* **Taggeamento Nativo de Múltiplos Artistas:** Detecta e divide automaticamente artistas principais e convidados. Ao contrário dos baixadores padrão, ele grava múltiplas tags discretas para arquivos FLAC (Comentários Vorbis) e strings padrão separadas por nulos para MP3s (ID3v2), garantindo interpretação impecável por players de ponta como Roon, Plexamp ou Kodi, sem a necessidade de ferramentas externas como o MusicBrainz Picard.
* **Suporte Nativo ao ReplayGain:** Extrai e incorpora automaticamente as tags `REPLAYGAIN_TRACK_GAIN` e `REPLAYGAIN_TRACK_PEAK` diretamente dos dados ocultos da API do Qobuz. Isso garante um nivelamento de volume perfeito e não destrutivo de fábrica para reprodutores de áudio digital de ponta (DAPs) e servidores audiófilos como o Roon.
* **Mecanismo Automático de Letras e Tagueador Retroativo:** Busca e injeta letras sincronizadas (`.lrc`) e não sincronizadas usando o LRCLIB (com a API do Genius como alternativa). Inclui um comando independente `lyrics` para escanear e injetar retroativamente letras ausentes em sua biblioteca local existente, sem precisar baixar o áudio novamente. Use a flag `--overwrite` caso queira substituir os textos já existentes (Novidade v2.2.0).
* **Livrinhos Digitais Aprimorados (Digital Booklets):** Compila automaticamente um arquivo `.txt` maravilhosamente formatado com uma lista de faixas completa, tempo de reprodução, créditos totais, metadados e resenhas. Ao terminar, o mecanismo varre de forma inteligente a pasta, remove as marcações de tempo dos arquivos `.lrc` e anexa as letras em texto puro de todo o álbum diretamente no livrinho. Os arquivos PDF oficiais ("Goodies") também são baixados junto. **Você agora pode usar a flag `--booklet-only` para baixar exclusivamente esses arquivos de metadados, arte da capa e PDFs, pulando graciosamente todas as faixas pesadas de áudio.**

### 🚀 Mecanismo de Download Resiliente
* **Fila À Prova de Balas:** Tratamento avançado de exceções em nível de faixa. Se uma única faixa estiver bloqueada geograficamente ou ausente dos servidores (erro 404), o mecanismo a pula graciosamente e continua perfeitamente o download do resto do seu álbum ou playlist sem travar (Aprimorado na v2.2.0).
* **Recuperação e Sincronização de Banco de Dados:** Inclui um mecanismo especializado `--sync-db` para restaurar entradas ausentes em seu banco de dados local, verificando suas pastas de música existentes.
* **Sincronização Bidirecional de Playlist (`sync-playlist`):** Um poderoso mecanismo de espelhamento para playlists dinâmicas. Mantenha suas pastas locais perfeitamente sincronizadas com as mudanças online (baixando novas faixas e excluindo de forma limpa as removidas). **A v2.0.1 introduz a Lógica de Pasta Inteligente:** ao usar `-d .` ou caminhos genéricos, cria automaticamente uma subpasta com o nome da playlist, prevenindo a exclusão acidental de arquivos em seu diretório raiz.
* **Tabela Profissional de Faixas Ausentes:** Se o mecanismo de sincronização detectar faixas em sua playlist online que estão faltando no seu disco local, ele agora gera uma tabela ASCII limpa e codificada por cores com Título, Artista e ID para fácil rastreamento.
* **Busca Reversa Inteligente:** Identifica automaticamente arquivos legados lendo suas tags **ISRC** ou **UPC** e consultando a API do Qobuz para restaurar os IDs corretos no banco de dados.
* **Validação Inteligente de Configuração Pré-Voo:** Introduzido na v2.0.3, um sistema de validação inteligente varre as strings de formato do seu `config.ini` antes do início de qualquer download. Se detectar uma variável não reconhecida, o mecanismo aborta graciosamente o processo e usa `difflib` para sugerir inteligentemente a variável correta, evitando exceções `KeyError` silenciosas.
* **Download Segmentado e Remuxagem:** Ignora a limitação do CDN da Akamai com um mecanismo de download segmentado de alta velocidade e remuxagem automática com o FFmpeg.
* **Download Multithread:** Downloads concorrentes de faixas para obtenção extremamente rápida de álbuns.
* **Interface Multithread Limpa:** Muda inteligentemente para um sistema de registro (logging) estático e sem bagunça, exibindo tamanhos de arquivo precisos (MB) durante downloads concorrentes. Isso evita falhas visuais no terminal e "guerras de cursor" com o Mecanismo de Letras, enquanto preserva as clássicas barras de progresso animadas para downloads sequenciais (`--delay`).
* **Redução Inteligente de Qualidade (Fallback):** Faz o downgrade automático para a próxima melhor qualidade disponível se a camada solicitada for restrita pelo servidor, garantindo que sua fila de download nunca trave.
* **Bypass de Autenticação:** Faça o login com segurança usando o **Auth Token** do seu navegador se a autenticação padrão por senha estiver bloqueada. Lida perfeitamente com contas Free/Studio.
* **Mascaramento Furtivo Anti-Ban (Stealth Spoofing):** WAFs (Web Application Firewalls) modernos bloqueiam requisições de API originadas de scripts invisíveis (headless). Este mecanismo apresenta mascaramento furtivo criptográfico completo, injetando as exatas Dicas de Cliente (Client Hints) do Windows/Chrome (`Sec-Ch-Ua`, `Sec-Fetch-Site`) para tornar sua sessão completamente indistinguível de um usuário legítimo navegando no Web Player do Qobuz, reduzindo significativamente os erros 403 e evitando banimentos de conta.
* **Playlists Ilimitadas:** Supera as restrições da API do Qobuz por meio de paginação dinâmica de pedaços de solicitações, permitindo enfileirar e baixar playlists enormes sem o gargalo padrão de 50 faixas.
* **Retomada Inteligente (Sem Substituições):** Detecta inteligentemente arquivos existentes em seu disco local e os pula automaticamente. Se o download de uma discografia gigantesca for interrompido, ele é retomado instantaneamente sem desperdiçar tempo ou banda baixando as faixas existentes novamente.
* **Mecanismo de Lista Negra Anti-Spam:** Filtra automaticamente lançamentos "lixo" indesejados (ex: versões de Karaokê, Covers Instrumentais, Álbuns de Tributo) ao baixar discografias massivas de artistas ou catálogos de gravadoras. Você pode passar um arquivo `.txt` contendo suas palavras-chave personalizadas (ex: `Karaoke`, `(Live)`, `Original Soundtrack`) via a flag `-b` no terminal ou defini-lo permanentemente no seu `config.ini`. O mecanismo une dinamicamente as tags de título principal e versão, garantindo a filtragem impecável antes mesmo de um único byte de áudio ser baixado.
* **Download em Lote com Estado (Memória de Arquivo de Texto):** Ao baixar filas massivas a partir de um arquivo `.txt`, o mecanismo age como um banco de dados vivo. Ele valida os URLs automaticamente e adiciona uma tag `[CONCLUÍDO]` ao lado dos links concluídos diretamente no seu arquivo de texto. Se a sua conexão cair ou você abortar o processo, basta executar o comando novamente: o mecanismo pulará os links concluídos e continuará a fila perfeitamente de onde parou.
* **Geração Impecável de `.m3u`:** Gera arquivos de playlist automaticamente com caminhos de pasta relativos corretos. **A v2.0.1 apresenta um algoritmo robusto de correspondência em 4 etapas** (ID -> ISRC -> Título -> Nome do arquivo) que garante que o arquivo `.m3u` espelhe perfeitamente a ordem da API, mesmo quando as faixas não têm prefixos numéricos em seus nomes de arquivo.
* **Mecanismo de Correspondência O(1) Ultra-Rápido:** O gerador de playlist agora usa indexação de dicionário de alto desempenho. Ele identifica os arquivos locais instantaneamente, reduzindo o tempo de processamento para playlists massivas de segundos para milissegundos. (Agradecimentos a marrobHD)

### 📁 Formatação e Armazenamento Avançados

O Qobuz-DL Ultimate permite uma personalização profunda da estrutura de sua biblioteca usando variáveis.

* **Suporte Verdadeiro a Playlists (Nativo):** Lida perfeitamente com playlists do Qobuz e do Last.fm com uma lógica especializada projetada para a organização da biblioteca (Corrige #257).
  * **Estrutura de Pasta Plana:** Baixa automaticamente todas as faixas para um único diretório com o nome da playlist, impedindo a criação de dezenas de subpastas de álbuns espalhadas.
  * **Nomenclatura Independente de Posição:** Arquivos de áudio são salvos de forma limpa (ex: `Artista - Título.flac`) sem prefixos numéricos codificados. Essa abordagem padrão da indústria garante que, se a ordem de uma playlist mudar online, seus arquivos locais sejam reconhecidos instantaneamente, evitando re-downloads duplicados massivos.
  * **`.m3u` Inteligente Direcionado por API:** A ordem de reprodução é garantida por um arquivo `.m3u` gerado dinamicamente que espelha perfeitamente a sequência exata ditada pelos servidores do Qobuz, independentemente dos nomes físicos dos arquivos.
  * **Gerenciamento Inteligente de Capa:** Elimina o bug de "Conflito de Capa". O mecanismo gerencia a arte incorporada de forma dinâmica, garantindo que cada faixa receba sua capa correta e única sem deixar arquivos `cover.jpg` duplicados na pasta.
* **Variáveis Poderosas:** `folder_format` e `track_format` agora suportam dezenas de novas variáveis (ex: `{isrc}`, `{barcode}`, `{label}`, `{track_composer}`).
* **Tipo de Lançamento (`{release_type}`):** Identifica automaticamente a categoria da publicação nas APIs do Qobuz (ex: `Album`, `EP`, `Single`), permitindo que você encaminhe downloads de forma dinâmica para subdiretórios ou use isso como um prefixo de nomeação sem impor uma estrutura fixa.
  * *Exemplo de Pasta (Subdiretório):* `folder_format = {release_type}/{album_artist} - {album_title}` ➔ `Album/Daft Punk - Discovery`
  * *Exemplo de Pasta (Prefixo):* `folder_format = {release_type} - {album_artist} - {album_title}` ➔ `Single - Gorillaz - Silent Running`
* **Tag de Conteúdo Explícito (`{explicit}` ou `{ExplicitFlag}`):** Adiciona automaticamente uma tag `[E]` se a faixa ou álbum for marcado com um aviso de restrição de idade no Qobuz. Se o conteúdo for limpo, a variável permanece vazia sem deixar espaços finais indesejados. **Você pode aplicar isso permanentemente adicionando as variáveis ao seu arquivo `config.ini`, ou temporariamente via terminal usando as flags `-ff` e `-tf`.**
  * *Exemplo de Pasta:* `folder_format = {artist} - {album} {ExplicitFlag}` ➔ `Eminem - The Eminem Show [E]`
  * *Exemplo de Faixa:* `track_format = {track_number} - {track_title} {ExplicitFlag}` ➔ `02 - Without Me [E].flac`
* **Tag de Versão do Álbum (`{version_tag}`):** Adiciona automaticamente a versão do álbum (ex: Ao Vivo, Remasterizado, Edição Deluxe) ao nome da sua pasta ou faixa. Se o lançamento for uma edição padrão, a variável permanece completamente vazia, evitando espaços ou traços finais indesejados.
  * *Exemplo de Pasta (Padrão):* `folder_format = {album_artist} - {album_title}{version_tag}` ➔ `The Sunset Violent`
  * *Exemplo de Pasta (Edição Especial):* `folder_format = {album_artist} - {album_title}{version_tag}` ➔ `The Sunset Violent - Live in Heidelberg`
* **Roteamento de Múltiplos Discos:** Armazene lançamentos de vários discos em um único diretório ou divida-os usando prefixos personalizáveis (ex: `CD 01`).
* **Geração Universal de Playlists:** Arquivos `.m3u` são rigorosamente codificados em UTF-8, garantindo geração 100% livre de travamentos mesmo com caracteres Unicode complexos ou japoneses (Corrige #304).
* **Substituição de Caracteres Legados (`legacy_charmap`):** Por padrão, a Ultimate Edition usa caracteres Unicode estéticos de largura total (ex: `／`) para contornar com segurança as restrições de nome de arquivo do SO sem perder a estética do título original. No entanto, os puristas podem ativar a opção `legacy_charmap = true` no `config.ini` para forçar substituições ASCII padrão (ex: substituindo `/` por `-` ou removendo `?`), restaurando a convenção de nomenclatura clássica e antiga do qobuz-dl original.

### ❤️ Sincronização Nativa de Favoritos e Menu Interativo
Faça uma ponte perfeita entre seus hábitos de escuta móveis e sua biblioteca local offline. Em vez de copiar URLs manualmente, inicie o Modo Interativo (`fun`) para acessar com segurança sua conta pessoal do Qobuz e navegar por seus **Álbuns, Faixas, Artistas e Playlists Favoritos** diretamente do terminal.
* **Fluxo de Trabalho de Digitação Zero:** Busque sua biblioteca privada com um único clique sem nunca sair do terminal.
* **Download Massivo em Lote:** Use a `Barra de Espaço` para selecionar várias dezenas de seus lançamentos favoritos da interface minimalista e limpa e colocá-los na fila para download em segundos.
* **Filtro Inteligente de Lançamentos (Mecanismo Heurístico):** Ao buscar a discografia de um artista, o mecanismo executa um algoritmo heurístico local super-rápido para categorizar lançamentos (Álbuns, EPs, Singles, Ao Vivo). Ele apresenta instantaneamente uma interface de caixa de seleção de múltipla escolha, permitindo que você filtre singles ou compilações indesejadas antes mesmo do início do download, economizando quantidades maciças de tempo e armazenamento.

### 🌉 Integração Inteligente com Last.fm e Modo Interativo
Conecte perfeitamente o seu mundo Last.fm ao Qobuz. Baixe suas playlists personalizadas e "Loved Tracks" (Faixas Amadas) com facilidade.
Para evitar o download de músicas incorretas, este fork utiliza um **Algoritmo de Correspondência Difusa (Fuzzy Matching)** matemático:
* **Aceitação Automática (> 75%):** Correspondências perfeitas são enfileiradas automaticamente.
* **Ignorar Automático (< 60%):** Faixas completamente erradas são puladas automaticamente.
* **Seleção Interativa (60% - 74%):** Para correspondências limítrofes, o mecanismo pausa e ativa um aviso interativo permitindo que você aprove ou rejeite a faixa manualmente (`[y/n]`).

### 📡 Radar RSS do MusicButler (Sincronização Automatizada de Favoritos)
Nunca perca um novo lançamento dos artistas que você acompanha. O novo comando `radar` integra-se perfeitamente com seu feed RSS privado do **MusicButler** para automatizar seu fluxo de trabalho de descoberta.
* **Análise Inteligente de Feed:** Busca e analisa automaticamente seu feed RSS/Atom privado para encontrar os lançamentos mais recentes dos artistas que você segue.
* **Correspondência Difusa no Qobuz:** Consulta o banco de dados do Qobuz para encontrar as correspondências exatas em alta resolução para os seus novos lançamentos diários.
* **Interface de Caixa de Seleção Interativa:** Apresenta um menu de terminal interativo e limpo onde você pode selecionar várias opções (`Barra de Espaço`) dos novos lançamentos e injetá-los instantaneamente em seus Favoritos do Qobuz (`Enter`), prontos para serem baixados mais tarde por meio do modo `fun`.

### 🛡️ Gerenciamento de Pastas À Prova de Falhas e Retomada Inteligente
Diga adeus a bibliotecas bagunçadas e downloads corrompidos. O baixador agora apresenta um sistema de estado de pastas dinâmico de 3 estágios para manter sua biblioteca de músicas perfeitamente organizada:
* **`[IN PROGRESS]`**: As pastas são marcadas assim enquanto o download está ativamente em execução.
* **`[INCOMPLETE]`**: Se você abortar o processo (tratamento gracioso de `CTRL+C`) ou se algumas faixas forem puladas (ex: bloqueadas geograficamente ou indisponíveis), a pasta é marcada de forma segura como incompleta.
* **Estado Limpo**: Apenas quando um álbum é baixado com **100% de sucesso**, a pasta será renomeada para seu estado final e limpo (ex: `Artista - Álbum`).

*Nota: O mecanismo é inteligente o suficiente para retomar downloads sem problemas diretamente em pastas `[INCOMPLETE]` ou `[IN PROGRESS]` na sua próxima execução!*

## 🕹️ Comandos e Atalhos do Qobuz-DL

Abaixo estão todos os comandos e modos de operação disponíveis no Qobuz-DL Master Edition, com exemplos práticos de como utilizá-los.

### `qobuz-dl fun` ou `qobuz-dl interactive` ou `qobuz-dl i`
**O que faz:** Abre o Modo Interativo no terminal. Permite navegar na sua conta (Favoritos, Playlists, Artistas) e buscar músicas usando uma interface de seleção visual.
* **Exemplo:** `qobuz-dl fun`
* **Dica:** Use as setas para navegar, a Barra de Espaço para selecionar vários itens e o Enter para iniciar o download massivo.

### `qobuz-dl dl`
**O que faz:** O modo clássico de download por URL. Permite baixar álbuns, faixas, playlists ou até URLs do Last.fm inserindo o link diretamente ou através de um arquivo de texto.
* **Exemplo URL:** `qobuz-dl dl https://play.qobuz.com/album/12345`
* **Exemplo Arquivo (Lote):** `qobuz-dl dl fila_de_downloads.txt`
* **Dica:** O mecanismo lembrará os downloads concluídos no arquivo `.txt` adicionando a tag `[CONCLUÍDO]`.

### `qobuz-dl lucky`
**O que faz:** Busca um termo no Qobuz e baixa automaticamente o primeiro resultado (ou os primeiros "N" resultados). Ótimo para baixar rápido sem navegar.
* **Exemplo (Baixar 1 álbum):** `qobuz-dl lucky "Daft Punk Discovery"`
* **Exemplo (Baixar 3 faixas):** `qobuz-dl lucky -t track -n 3 "Billie Jean"`
* **Argumentos:** `-t` ou `--type` (album, track, artist, playlist) e `-n` (número de resultados).

### `qobuz-dl lyrics`
**O que faz:** Modo de injeção retroativa. Escaneia uma pasta local cheia de arquivos FLAC/MP3 e busca/injetar as letras sincronizadas (e traduzidas) que estiverem faltando, sem precisar baixar o áudio novamente.
* **Exemplo:** `qobuz-dl lyrics "C:\Musicas\Meus Albuns"`
* **Sobrescrever:** Adicione `--overwrite` para forçar a substituição das letras existentes (útil se você configurou a tradução automática recentemente e quer atualizar as músicas antigas).

### `qobuz-dl sync-playlist` ou `qobuz-dl sp`
**O que faz:** Mantém uma pasta local espelhada com uma Playlist do Qobuz. Ele baixa as faixas novas e deleta do seu computador as faixas que foram removidas da playlist online.
* **Exemplo:** `qobuz-dl sp https://play.qobuz.com/playlist/12345`
* **Confirmação:** Adicione `--yes` ou `-y` para pular o aviso de confirmação antes de deletar arquivos locais.

### `qobuz-dl smart-mix` ou `qobuz-dl sm`
**O que faz:** Lê a sua biblioteca local de músicas baixadas e utiliza uma IA (OpenAI ou Gemini) para criar playlists `.m3u` personalizadas baseadas em um "conceito" (clima, ritmo, tema).
* **Exemplo:** `qobuz-dl sm "Músicas relaxantes para ler em dias de chuva"`
* **Limite:** Adicione `-n 15` para limitar a playlist a 15 faixas.
* **Atenção:** Você precisa configurar a sua chave de API via Assistente (`qobuz-dl -r`) ou no seu arquivo `config.ini` antes de rodar este comando.

### `qobuz-dl panel` ou `qobuz-dl p`
**O que faz:** Inicia a **Central de Controle Interativa (TUI)** do Qobuz-DL. Este é um painel minimalista e profissional no próprio terminal que permite acessar todos os recursos do programa através de um menu de fácil navegação com o teclado, em vez de memorizar comandos.
* **Exemplo:** `qobuz-dl panel`

### `qobuz-dl stats`
**O que faz:** Exibe um resumo estatístico da sua biblioteca baseado no banco de dados local (Total de faixas, álbuns, artistas únicos e distribuição por qualidade/resolução).
* **Exemplo:** `qobuz-dl stats`

### `qobuz-dl radar`
**O que faz:** Conecta com o feed RSS privado do MusicButler, escaneia novos lançamentos de seus artistas favoritos e permite injetá-los diretamente em seus Favoritos do Qobuz para download posterior.
* **Exemplo:** `qobuz-dl radar`

### Atualização e Limpeza
* **Mostrar Config:** `qobuz-dl -sc` ou `--show-config`
* **Resetar Config:** `qobuz-dl -r` ou `--reset` (Executa o Assistente de Configuração).
* **Limpar DB:** `qobuz-dl -p` ou `--purge` (Deleta o banco de dados local para baixar faixas ignoradas/repetidas).


## 📥 Instalação e Configuração

> ⚠️ **Requisito:** Você precisa de uma **assinatura ativa** do Qobuz.

### 🖥️ 1. Instalação no Computador (Windows / Mac / Linux)
A maneira mais fácil e oficial de instalar a Ultimate Edition. O `pip` cuida de tudo sozinho. Abra seu terminal e execute:
```bash
pip install qobuz-dl-master
```

### 🍏 2. Instalação no iSH Shell (iOS / iPadOS)
Se você estiver utilizando o aplicativo **iSH Shell** no iOS, a instalação padrão falhará pela falta de compiladores C (que são necessários para pacotes de criptografia).
Para resolver isso, você deve instalar os pré-requisitos através do pacote do Alpine (APK) antes do `pip`:

```bash
apk update

apk add nano ffmpeg python3 py3-pip py3-pycryptodome py3-aiohttp

python3.9 -m pip install --upgrade typing-extensions beautifulsoup4 deep-translator lyricsgenius mutagen

pip install qobuz-dl-master

```

### 🤖 3. Instalação no Termux (Android)
O Termux possui um ambiente Linux restrito. Portanto, você deve compilar os headers criptográficos básicos e ferramentas de build antes da instalação principal. Execute os comandos um a um:

```bash
pkg update
pkg install python build-essential libffi libxml2 libxslt
pip install qobuz-dl-master
```
