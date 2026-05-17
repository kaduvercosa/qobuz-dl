import os
import sys
import asyncio
from pick import pick

from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN, BOLD

async def run_tui_panel(qobuz_client):
    import qobuz_dl.cli

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')

        title = (
            "==============================================\n"
            "          QOBUZ-DL CONTROL CENTER           \n"
            "==============================================\n\n"
            "Use ARROW KEYS to navigate and ENTER to select:"
        )

        choices = [
            "📥  [FUN] Interactive Mode (Browse Qobuz & Download)",
            "🔗  [DL] Download from URL",
            "🎲  [LUCKY] I'm Feeling Lucky (Instant Download by Search)",
            "🔄  [SYNC] Sync Local Playlist with Qobuz",
            "🧠  [AI] Smart Mix (Generate .m3u Playlist)",
            "📜  [LYRICS] Retroactively Inject Lyrics to Local Files",
            "📡  [RADAR] Scan MusicButler RSS for New Releases",
            "⚙️   Settings / Configuration Wizard",
            "❌  Exit"
        ]

        try:
            # pick is safe and perfectly integrated with Python's basic terminal
            option, index = pick(choices, title, indicator="=>", default_index=0)
        except KeyboardInterrupt:
            break

        if index == 8: # Exit
            print(f"\n{GREEN}Exiting Control Center. Goodbye!{OFF}")
            break

        elif index == 0: # FUN / Interactive
            try:
                # Force interactive limit from config if available, else 20
                qobuz_client.interactive_limit = getattr(qobuz_client.settings, 'default_limit', 20)
                await qobuz_client.interactive()
            except Exception as e:
                print(f"\n{RED}[!] Interactive Mode error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 1: # DL / URL
            print(f"\n{CYAN}--- Download from URL ---{OFF}")
            url = input(f"{BOLD}🔗 Paste the Qobuz URL:{OFF} ").strip()
            if url:
                try:
                    await qobuz_client.download_list_of_urls([url])
                except Exception as e:
                    print(f"\n{RED}[!] Download error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 2: # LUCKY
            print(f"\n{CYAN}--- I'm Feeling Lucky ---{OFF}")
            print("Download the first result instantly without navigating.")
            query = input(f"{BOLD}🔎 Enter Artist, Album or Track name:{OFF} ").strip()
            if query:
                print("\nTypes: 1) Album  2) Track  3) Artist  4) Playlist")
                type_choice = input(f"Select type (1-4) [default: 1]: ").strip()
                type_map = {"1": "album", "2": "track", "3": "artist", "4": "playlist"}
                qobuz_client.lucky_type = type_map.get(type_choice, "album")
                qobuz_client.lucky_limit = 1
                try:
                    await qobuz_client.lucky_mode(query)
                except Exception as e:
                    print(f"\n{RED}[!] Lucky Mode error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 3: # SYNC
            print(f"\n{CYAN}--- Sync Local Playlist ---{OFF}")
            url = input(f"{BOLD}🔗 Paste the Qobuz Playlist URL to sync:{OFF} ").strip()
            if url:
                from qobuz_dl.sync_playlist import sync_playlist
                try:
                    print(f"\n{CYAN}[*] Starting Sync Process...{OFF}")
                    sync_playlist(qobuz_client, url, qobuz_client.directory, auto_confirm=False)
                except Exception as e:
                    print(f"\n{RED}[!] Sync error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 4: # AI
            print(f"\n{CYAN}--- AI Smart Mix ---{OFF}")
            concept = input(f"{BOLD}🧠 Enter the concept (e.g., 'Relaxing rock'):{OFF} ").strip()
            if concept:
                limit_str = input(f"{BOLD}🔢 Max tracks (default: 30):{OFF} ").strip()
                try:
                    limit = int(limit_str) if limit_str else 30
                except ValueError:
                    limit = 30

                from qobuz_dl.ai_mixer import generate_smart_mix
                try:
                    await generate_smart_mix(qobuz_client.directory, concept, limit, qobuz_client.settings)
                except Exception as e:
                    print(f"\n{RED}[!] AI Mix error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 5: # LYRICS
            print(f"\n{CYAN}--- Retroactive Lyrics Injection ---{OFF}")
            folder = input(f"{BOLD}📁 Enter the local directory to scan (or press Enter for default '{qobuz_client.directory}'):{OFF} ").strip()
            if not folder:
                folder = qobuz_client.directory

            print("Force overwrite existing lyrics?")
            print(" 1) No (Skip files that already have lyrics)")
            print(" 2) Yes (Re-translate and overwrite everything)")
            overwrite = input("Choice (1 or 2) [default: 1]: ").strip() == "2"

            from qobuz_dl.retro_tagger import inject_lyrics_retroactively
            try:
                await inject_lyrics_retroactively(
                    target_dir=folder,
                    genius_token=getattr(qobuz_client.settings, 'genius_token', None),
                    translate=True,
                    target_lang=getattr(qobuz_client.settings, 'target_lang', 'pt'),
                    save_lrc=getattr(qobuz_client.settings, 'lrc_files', True),
                    overwrite=overwrite
                )
            except Exception as e:
                print(f"\n{RED}[!] Lyrics error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 6: # RADAR
            print(f"\n{CYAN}--- MusicButler RSS Radar ---{OFF}")
            from qobuz_dl.radar import run_radar
            try:
                run_radar()
            except Exception as e:
                print(f"\n{RED}[!] Radar error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif index == 7: # SETTINGS
            print(f"\n{CYAN}[*] Launching Configuration Wizard...{OFF}")
            try:
                qobuz_dl.cli._reset_config(qobuz_dl.cli.CONFIG_FILE)
            except SystemExit:
                pass # Prevent sys.exit() from completely killing the script if user finishes config
            input(f"\n{YELLOW}Configuration updated! Restart the panel for changes to take effect. Press ENTER to return...{OFF}")
