import asyncio
from qobuz_dl.lyrics_engine import LyricsEngine

async def main():
    engine = LyricsEngine(translate=True, target_lang='pt')
    lyrics = "[00:12.00]Hello, how are you?\n[00:15.00]I am fine, thank you."

    res = await engine._process_translation(lyrics, is_synced=True)
    print("Result:")
    print(res)

asyncio.run(main())
