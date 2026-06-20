class Tema:
    OFF     = "\033[0m"
    BOLD    = "\033[1m"
    TXT_WHITE = "\033[97m"

    # --- ÁLBUM (Verde) ---
    BG_ALBUM      = "\033[48;5;22m"     # Cor Primária (Fundo Escuro)
    BG_ALBUM_SEC  = "\033[48;5;71m"     # Cor Secundária (Fundo Pastel)
    TXT_ALBUM     = "\033[38;5;71m"     # Texto da Árvore

    # --- PLAYLIST (Roxo) ---
    BG_PLAYLIST   = "\033[48;5;54m"
    BG_PLAYLIST_SEC = "\033[48;5;97m"
    TXT_PLAYLIST  = "\033[38;5;97m"

    # --- LOTE (Azul) ---
    BG_LOTE       = "\033[48;5;24m"
    BG_LOTE_SEC   = "\033[48;5;68m"
    TXT_LOTE      = "\033[38;5;68m"

    # --- SINGLE (Teal/Ciano) ---
    BG_SINGLE     = "\033[48;5;23m"
    BG_SINGLE_SEC = "\033[48;5;73m"
    TXT_SINGLE    = "\033[38;5;73m"

    GREEN   = "\033[32m"
    PURPLE  = "\033[35m"

album_title = "Future Nostalgia"
artist = "Dua Lipa"
track_title = "Levitating"
file_format = "FLAC"
bit_depth = "24"
sampling_rate = "44.1"

print("\n" + "="*50)
print("🧪 LABORATORIO DE CORES - FUNDO SECUNDARIO")
print("="*50)

# ------------------------------------------
# 1. TESTE VISUAL: ÁLBUM / EP
# ------------------------------------------
t_album = f"  💿 ALBUM | {album_title}  "
print(f"\n{Tema.BG_ALBUM}{Tema.TXT_WHITE}{Tema.BOLD}{t_album}{Tema.OFF}")
print(f"{Tema.TXT_ALBUM} ├── Artista: {artist}{Tema.OFF}")
print(f"{Tema.TXT_ALBUM} ├── Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz){Tema.OFF}")
print(f"{Tema.TXT_ALBUM} └── Faixas na Fila: 12\n{Tema.OFF}")

print(f"{Tema.BG_ALBUM_SEC}{Tema.TXT_WHITE}{Tema.BOLD} ▶ [01/12] 🎵 {artist} - {track_title} {Tema.OFF}")
print(f"{Tema.TXT_ALBUM}   ├── 🖼️ cover.jpg {Tema.PURPLE}[Apple]{Tema.OFF}")
print(f"{Tema.TXT_ALBUM}   ├── 🎧 {Tema.BOLD}{track_title}{Tema.OFF} {Tema.GREEN}[24b/44.1kHz]{Tema.OFF}")
print(f"{Tema.TXT_ALBUM}   ├── 📝 Letra: NATIVA Qobuz (Sync) (Trad: 50/50){Tema.OFF}")
print(f"{Tema.TXT_ALBUM}   └── ✔️ {Tema.GREEN}Finalizado{Tema.OFF}\n")

# ------------------------------------------
# 2. TESTE VISUAL: PLAYLIST
# ------------------------------------------
pl_name = "MUSICAS POP 2026"
t_pl = f"  📋 PLAYLIST | {pl_name}  "
print(f"{Tema.BG_PLAYLIST}{Tema.TXT_WHITE}{Tema.BOLD}{t_pl}{Tema.OFF}\n")

print(f"{Tema.BG_PLAYLIST_SEC}{Tema.TXT_WHITE}{Tema.BOLD} ▶ [01/50] 🎵 {artist} - {track_title} {Tema.OFF}")
print(f"{Tema.TXT_PLAYLIST}   ├── Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz){Tema.OFF}")
print(f"{Tema.TXT_PLAYLIST}   ├── 🖼️ embed_cover.jpg {Tema.PURPLE}[Apple]{Tema.OFF}")
print(f"{Tema.TXT_PLAYLIST}   ├── 🎧 {Tema.BOLD}{track_title}{Tema.OFF} {Tema.GREEN}[24b/44.1kHz]{Tema.OFF}")
print(f"{Tema.TXT_PLAYLIST}   ├── 📝 Letra: NATIVA Qobuz (Sync) (Trad: 50/50){Tema.OFF}")
print(f"{Tema.TXT_PLAYLIST}   └── ✔️ {Tema.GREEN}Finalizado{Tema.OFF}\n")

# ------------------------------------------
# 3. TESTE VISUAL: LOTE DE SINGLES
# ------------------------------------------
t_lote = f"  🎵 LOTE DE SINGLES  "
print(f"{Tema.BG_LOTE}{Tema.TXT_WHITE}{Tema.BOLD}{t_lote}{Tema.OFF}\n")

print(f"{Tema.BG_LOTE_SEC}{Tema.TXT_WHITE}{Tema.BOLD} ▶ [01/05] 🎵 {artist} - {track_title} {Tema.OFF}")
print(f"{Tema.TXT_LOTE}   ├── Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz){Tema.OFF}")
print(f"{Tema.TXT_LOTE}   ├── 🖼️ embed_cover.jpg {Tema.PURPLE}[Apple]{Tema.OFF}")
print(f"{Tema.TXT_LOTE}   ├── 🎧 {Tema.BOLD}{track_title}{Tema.OFF} {Tema.GREEN}[24b/44.1kHz]{Tema.OFF}")
print(f"{Tema.TXT_LOTE}   ├── 📝 Letra: NATIVA Qobuz (Sync) (Trad: 50/50){Tema.OFF}")
print(f"{Tema.TXT_LOTE}   └── ✔️ {Tema.GREEN}Finalizado{Tema.OFF}\n")

# ------------------------------------------
# 4. TESTE VISUAL: SINGLE
# ------------------------------------------
t_single = f"  🎵 SINGLE | {artist} - {track_title}  "
print(f"{Tema.BG_SINGLE}{Tema.TXT_WHITE}{Tema.BOLD}{t_single}{Tema.OFF}\n")

print(f"{Tema.BG_SINGLE_SEC}{Tema.TXT_WHITE}{Tema.BOLD} ▶ [01/01] 🎵 {artist} - {track_title} {Tema.OFF}")
print(f"{Tema.TXT_SINGLE}   ├── Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz){Tema.OFF}")
print(f"{Tema.TXT_SINGLE}   ├── 🖼️ cover.jpg {Tema.PURPLE}[Apple]{Tema.OFF}")
print(f"{Tema.TXT_SINGLE}   ├── 🎧 {Tema.BOLD}{track_title}{Tema.OFF} {Tema.GREEN}[24b/44.1kHz]{Tema.OFF}")
print(f"{Tema.TXT_SINGLE}   ├── 📝 Letra: NATIVA Qobuz (Sync) (Trad: 50/50){Tema.OFF}")
print(f"{Tema.TXT_SINGLE}   └── ✔️ {Tema.GREEN}Finalizado{Tema.OFF}\n")
