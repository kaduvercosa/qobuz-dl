import logging
import asyncio
import os
import shutil
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters.command import Command
from aiogram.fsm.storage.memory import MemoryStorage

logger = logging.getLogger(__name__)

async def run_telegram_bot(qobuz_client):
    settings = qobuz_client.settings
    bot_token = getattr(settings, 'telegram_bot_token', None)
    admin_id = getattr(settings, 'telegram_chat_id', None)

    if not bot_token:
        print("\n[!] Telegram Bot Token not configured.")
        print("Please configure it in config.ini or run the wizard again (qobuz-dl -r).")
        return

    print("\n[*] Starting Telegram Bot Server...")
    print(f"[*] Only accepting commands from Chat ID: {admin_id if admin_id else 'ANYONE'}")

    bot = Bot(token=bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    async def is_admin(message: types.Message) -> bool:
        if admin_id:
            return str(message.chat.id) == str(admin_id)
        return True

    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        if not await is_admin(message): return
        welcome_text = (
            "🎵 *Qobuz-DL Bot Server is Online!*\n\n"
            "Here are your commands:\n"
            "🔍 `/search [query]` - Interactive Qobuz Search\n"
            "❤️ `/favorites` - Browse your Favorite Artists/Albums\n"
            "🔗 `/dl [url]` - Download an Album/Track/Playlist\n"
            "🎲 `/lucky [query]` - I'm Feeling Lucky (Instant Search & Download)\n"
            "🧠 `/mix [concept]` - Generate AI Smart Mix\n"
            "📡 `/radar` - Trigger Autonomous Watcher Daemon\n"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ My Favorites", callback_data="fav_menu")],
            [InlineKeyboardButton(text="📡 Run Radar Daemon", callback_data="cmd_radar")]
        ])

        await message.reply(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

    @dp.callback_query(F.data == "cmd_radar")
    async def cb_radar(callback: CallbackQuery):
        await callback.message.answer("📡 Running Autonomous Watcher Daemon...")
        from qobuz_dl.daemon import scan_new_releases
        try:
            await scan_new_releases(qobuz_client, test_mode=False)
            await callback.message.answer("✅ Radar Scan Complete! Check your n8n/Make webhooks.")
        except Exception as e:
            await callback.message.answer(f"❌ Radar Error: {e}")
        await callback.answer()

    @dp.callback_query(F.data == "fav_menu")
    async def cb_fav_menu(callback: CallbackQuery):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💿 Favorite Albums", callback_data="fav_albums")],
            [InlineKeyboardButton(text="🎵 Favorite Tracks", callback_data="fav_tracks")],
            [InlineKeyboardButton(text="👤 Favorite Artists", callback_data="fav_artists")],
            [InlineKeyboardButton(text="📝 Favorite Playlists", callback_data="fav_playlists")]
        ])
        await callback.message.edit_text("Select a category to browse:", reply_markup=keyboard)
        await callback.answer()

    @dp.callback_query(F.data == "fav_artists")
    async def cb_fav_artists(callback: CallbackQuery):
        await callback.message.edit_text("⏳ Fetching favorite artists from Qobuz...")
        try:
            favs = await qobuz_client.client.get_favorites(fav_type="artists", limit=10)
            items = favs.get("favorites", {}).get("artists", {}).get("items", []) or favs.get("artists", {}).get("items", [])

            if not items:
                await callback.message.edit_text("No favorite artists found.")
                return

            buttons = []
            for artist in items:
                artist_name = artist.get("name", "Unknown")
                artist_id = artist.get("id")
                buttons.append([InlineKeyboardButton(text=f"👤 {artist_name}", callback_data=f"art_{artist_id}")])

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Select an Artist to view their discography:", reply_markup=keyboard)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching favorites: {e}")
        await callback.answer()

    @dp.callback_query(F.data == "fav_tracks")
    async def cb_fav_tracks(callback: CallbackQuery):
        await callback.message.edit_text("⏳ Fetching favorite tracks from Qobuz...")
        try:
            favs = await qobuz_client.client.get_favorites(fav_type="tracks", limit=10)
            items = favs.get("favorites", {}).get("tracks", {}).get("items", []) or favs.get("tracks", {}).get("items", [])

            if not items:
                await callback.message.edit_text("No favorite tracks found.")
                return

            buttons = []
            for track in items:
                title = track.get("title", "Unknown")
                artist = track.get("performer", {}).get("name", "Unknown")
                track_id = track.get("id")
                buttons.append([InlineKeyboardButton(text=f"🎵 {artist} - {title}", callback_data=f"dl_track_{track_id}")])

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Select a Favorite Track to Download:", reply_markup=keyboard)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching favorites: {e}")
        await callback.answer()

    @dp.callback_query(F.data == "fav_playlists")
    async def cb_fav_playlists(callback: CallbackQuery):
        await callback.message.edit_text("⏳ Fetching favorite playlists from Qobuz...")
        try:
            favs = await qobuz_client.client.get_user_playlists(limit=10)
            items = favs.get("playlists", {}).get("items", [])

            if not items:
                await callback.message.edit_text("No playlists found.")
                return

            buttons = []
            for plist in items:
                title = plist.get("name", "Unknown")
                p_id = plist.get("id")
                buttons.append([InlineKeyboardButton(text=f"📝 {title}", callback_data=f"dl_playlist_{p_id}")])

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Select a Playlist to Download:", reply_markup=keyboard)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching playlists: {e}")
        await callback.answer()

    @dp.callback_query(F.data == "fav_albums")
    async def cb_fav_albums(callback: CallbackQuery):
        await callback.message.edit_text("⏳ Fetching favorite albums from Qobuz...")
        try:
            favs = await qobuz_client.client.get_favorites(fav_type="albums", limit=10)
            items = favs.get("favorites", {}).get("albums", {}).get("items", []) or favs.get("albums", {}).get("items", [])

            if not items:
                await callback.message.edit_text("No favorite albums found.")
                return

            buttons = []
            for album in items:
                title = album.get("title", "Unknown")
                artist = album.get("artist", {}).get("name", "Unknown")
                alb_id = album.get("id")
                buttons.append([InlineKeyboardButton(text=f"💿 {artist} - {title}", callback_data=f"dl_album_{alb_id}")])

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Select a Favorite Album to Download:", reply_markup=keyboard)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching favorites: {e}")
        await callback.answer()

    @dp.callback_query(F.data.startswith("art_"))
    async def cb_artist_discography(callback: CallbackQuery):
        artist_id = callback.data.split("_")[1]
        await callback.message.edit_text("⏳ Fetching artist discography...")
        try:
            meta = await qobuz_client.client.api_call("artist/get", artist_id=artist_id, limit=10)
            albums = meta.get("albums", {}).get("items", []) or meta.get("releases", {}).get("items", [])

            if not albums:
                await callback.message.edit_text("No releases found for this artist.")
                return

            buttons = []
            for alb in albums:
                title = alb.get("title", "Unknown")
                alb_id = alb.get("id")
                # Using ⬇️ icon to represent download action
                buttons.append([InlineKeyboardButton(text=f"⬇️ {title}", callback_data=f"dl_album_{alb_id}")])

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_artists")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback.message.edit_text("Select an album to Download:", reply_markup=keyboard)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching discography: {e}")
        await callback.answer()

    @dp.message(Command("search"))
    async def cmd_search(message: types.Message):
        if not await is_admin(message): return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/search Daft Punk`", parse_mode="Markdown")
            return

        query = args[1]
        await message.reply(f"🔍 Searching Qobuz for: `{query}`...", parse_mode="Markdown")
        try:
            results = await qobuz_client.client.search(query, type="albums", limit=5)
            albums = results.get("albums", {}).get("items", [])

            if not albums:
                await message.reply("No albums found for that query.")
                return

            buttons = []
            for alb in albums:
                title = alb.get("title", "Unknown")
                artist = alb.get("artist", {}).get("name", "Unknown")
                alb_id = alb.get("id")
                buttons.append([InlineKeyboardButton(text=f"⬇️ {artist} - {title}", callback_data=f"dl_album_{alb_id}")])

            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.reply("Select an album to Download:", reply_markup=keyboard)
        except Exception as e:
            await message.reply(f"❌ Search Error: {e}")


    # Global lock to prevent concurrent downloads messing with local directories/cache
    dl_lock = asyncio.Lock()

    async def upload_folder_to_telegram(message, folder_path):
        import mutagen
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3

        found_audio = []
        for root, dirs, files in os.walk(folder_path):
            for file in sorted(files):
                if file.lower().endswith(('.flac', '.mp3')):
                    found_audio.append(os.path.join(root, file))

        if not found_audio:
            await message.reply("Download completed, but no audio files found to upload.")
            return

        await message.reply(f"🚀 Uploading {len(found_audio)} tracks to Telegram...")

        for audio_file in found_audio:
            ext = os.path.splitext(audio_file)[1].lower()
            title = os.path.basename(audio_file)
            artist = "Unknown"

            try:
                if ext == '.flac':
                    audio = FLAC(audio_file)
                    if audio.get('TITLE'): title = audio.get('TITLE')[0]
                    if audio.get('ARTIST'): artist = audio.get('ARTIST')[0]
                elif ext == '.mp3':
                    audio = ID3(audio_file)
                    if audio.get('TIT2'): title = audio.get('TIT2').text[0]
                    if audio.get('TPE1'): artist = audio.get('TPE1').text[0]
            except Exception:
                pass

            input_file = FSInputFile(audio_file)
            try:
                await message.answer_audio(
                    audio=input_file,
                    title=title,
                    performer=artist
                )
            except Exception as e:
                await message.reply(f"⚠️ Failed to upload {title}. Reason: {e}\n(Tip: Telegram bots have a 50MB limit for files).")

        await message.reply("✅ Uploads completed!")

    @dp.callback_query(F.data.startswith("dl_"))
    async def cb_download_prompt(callback: CallbackQuery):
        parts = callback.data.split("_", 2)
        item_type = parts[1]
        item_id = parts[2]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💾 Save to Local Server Only", callback_data=f"execdl_local_{item_type}_{item_id}")],
            [InlineKeyboardButton(text="📤 Upload to this Chat", callback_data=f"execdl_chat_{item_type}_{item_id}")],
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="fav_menu")]
        ])
        await callback.message.edit_text(f"How would you like to process this {item_type} download?", reply_markup=keyboard)
        await callback.answer()

    @dp.callback_query(F.data.startswith("execdl_"))
    async def cb_execute_download(callback: CallbackQuery):
        parts = callback.data.split("_", 3)
        mode = parts[1] # 'local' or 'chat'
        item_type = parts[2] # 'album', 'track', 'playlist'
        item_id = parts[3]

        await callback.message.edit_text(f"⏳ Downloading {item_type.capitalize()} ID {item_id}...\nPlease wait.")

        url = f"https://open.qobuz.com/{item_type}/{item_id}"
        original_dir = qobuz_client.directory
        target_dir = original_dir

        if mode == "chat":
            target_dir = os.path.join(original_dir, "telegram_temp")
            os.makedirs(target_dir, exist_ok=True)
            qobuz_client.directory = target_dir

        async with dl_lock:
            try:
                await qobuz_client.download_list_of_urls([url])
                if mode == "chat":
                    await upload_folder_to_telegram(callback.message, target_dir)
                else:
                    await callback.message.answer(f"✅ Download successfully saved to your server at:\n`{original_dir}`", parse_mode="Markdown")
            except Exception as e:
                await callback.message.answer(f"❌ Download Error: {e}")
            finally:
                qobuz_client.directory = original_dir
                if mode == "chat" and os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
        await callback.answer()

    @dp.message(Command("lucky"))
    async def cmd_lucky(message: types.Message):
        if not await is_admin(message): return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/lucky Daft Punk Discovery`", parse_mode="Markdown")
            return

        query = args[1]
        await message.reply(f"🔍 Searching and downloading first result directly to local server for: `{query}`...", parse_mode="Markdown")

        async with dl_lock:
            try:
                qobuz_client.lucky_type = "album"
                qobuz_client.lucky_limit = 1
                await qobuz_client.lucky_mode(query)
                await message.reply(f"✅ Download successfully saved to your server at:\n`{qobuz_client.directory}`", parse_mode="Markdown")
            except Exception as e:
                await message.reply(f"❌ Error: {e}")

    @dp.message(Command("dl"))
    async def cmd_dl(message: types.Message):
        if not await is_admin(message): return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/dl https://open.qobuz.com/album/12345`", parse_mode="Markdown")
            return

        url = args[1].strip()

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💾 Save to Local Server Only", callback_data=f"cmddl_local")],
            [InlineKeyboardButton(text="📤 Upload to this Chat", callback_data=f"cmddl_chat")]
        ])

        # Store the URL in the message state to avoid hitting the 64-byte callback_data limit of Telegram
        await message.reply(f"How would you like to process this URL download?\n\nURL: `{url}`", reply_markup=keyboard, parse_mode="Markdown")

    @dp.callback_query(F.data.startswith("cmddl_"))
    async def cb_cmd_dl_execute(callback: CallbackQuery):
        mode = callback.data.split("_")[1]

        # Extract the URL from the message text we saved earlier
        msg_text = callback.message.text
        try:
            url = msg_text.split("URL: ")[1].strip()
        except IndexError:
            await callback.message.edit_text("❌ Error: Could not extract URL from message.")
            await callback.answer()
            return

        await callback.message.edit_text(f"📥 Processing download request...")

        original_dir = qobuz_client.directory
        target_dir = original_dir

        if mode == "chat":
            target_dir = os.path.join(original_dir, "telegram_temp")
            os.makedirs(target_dir, exist_ok=True)
            qobuz_client.directory = target_dir

        async with dl_lock:
            try:
                await qobuz_client.download_list_of_urls([url])
                if mode == "chat":
                    await upload_folder_to_telegram(callback.message, target_dir)
                else:
                    await callback.message.answer(f"✅ Download successfully saved to your server at:\n`{original_dir}`", parse_mode="Markdown")
            except Exception as e:
                await callback.message.answer(f"❌ Error: {e}")
            finally:
                qobuz_client.directory = original_dir
                if mode == "chat" and os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
        await callback.answer()

    @dp.message(Command("mix"))
    async def cmd_mix(message: types.Message):
        if not await is_admin(message): return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/mix Relaxing Rock`", parse_mode="Markdown")
            return

        concept = args[1].strip()
        await message.reply(f"🧠 AI is building a mix for: `{concept}`...", parse_mode="Markdown")

        from qobuz_dl.ai_mixer import generate_smart_mix
        try:
            await generate_smart_mix(qobuz_client.directory, concept, 30, qobuz_client.settings)
            await message.reply("✅ Smart Mix created successfully! Look in your downloads folder.")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")

    try:
        print("[+] Bot is polling for commands... Press CTRL+C to stop.")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
