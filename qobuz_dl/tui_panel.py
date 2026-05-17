import os
import sys
import asyncio
import questionary
from prompt_toolkit.styles import Style

from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN

custom_style = Style([
    ('qmark', 'fg:#00FF00 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#00FFFF bold'),
    ('pointer', 'fg:#00FF00 bold'),
    ('highlighted', 'fg:#00FF00 bold'),
    ('selected', 'fg:#00FF00'),
    ('separator', 'fg:#555555'),
    ('instruction', 'fg:#888888'),
    ('text', ''),
])

async def run_tui_panel(qobuz_client):
    import qobuz_dl.cli

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')

        print(f"\n{CYAN}=============================================={OFF}")
        print(f"{CYAN}          QOBUZ-DL CONTROL CENTER           {OFF}")
        print(f"{CYAN}=============================================={OFF}\n")

        choices = [
            "1. 📥 Download Music (Album/Track/Playlist)",
            "2. 🔄 Sync Local Playlist with Qobuz",
            "3. 🧠 AI Smart Mix (Generate .m3u Playlist)",
            "4. ⚙️  Settings / Configuration Wizard",
            "5. ❌ Exit"
        ]

        answer = await questionary.select(
            "Select an action:",
            choices=choices,
            style=custom_style
        ).ask_async()

        if not answer or answer.startswith("5"):
            print(f"\n{GREEN}Exiting Control Center. Goodbye!{OFF}")
            break

        elif answer.startswith("1"):
            url = await questionary.text("🔗 Paste the Qobuz URL:", style=custom_style).ask_async()
            if url:
                try:
                    await qobuz_client.download_list_of_urls([url.strip()])
                except Exception as e:
                    print(f"\n{RED}[!] Download error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif answer.startswith("2"):
            url = await questionary.text("🔗 Paste the Qobuz Playlist URL to sync:", style=custom_style).ask_async()
            if url:
                from qobuz_dl.sync_playlist import sync_playlist
                try:
                    print(f"\n{CYAN}[*] Starting Sync Process...{OFF}")
                    sync_playlist(qobuz_client, url.strip(), qobuz_client.directory, auto_confirm=False)
                except Exception as e:
                    print(f"\n{RED}[!] Sync error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif answer.startswith("3"):
            concept = await questionary.text("🧠 Enter the concept (e.g., 'Relaxing rock'):", style=custom_style).ask_async()
            if concept:
                limit_str = await questionary.text("🔢 Max tracks (default: 30):", default="30", style=custom_style).ask_async()
                try:
                    limit = int(limit_str)
                except ValueError:
                    limit = 30

                from qobuz_dl.ai_mixer import generate_smart_mix
                try:
                    await generate_smart_mix(qobuz_client.directory, concept.strip(), limit, qobuz_client.settings)
                except Exception as e:
                    print(f"\n{RED}[!] AI Mix error: {e}{OFF}")
            input(f"\n{YELLOW}Press ENTER to return to the menu...{OFF}")

        elif answer.startswith("4"):
            print(f"\n{CYAN}[*] Launching Configuration Wizard...{OFF}")
            try:
                qobuz_dl.cli._reset_config(qobuz_dl.cli.CONFIG_FILE)
            except SystemExit:
                pass # Prevent sys.exit() from completely killing the script if user finishes config
            input(f"\n{YELLOW}Configuration updated! Restart the panel for changes to take effect. Press ENTER to return...{OFF}")
