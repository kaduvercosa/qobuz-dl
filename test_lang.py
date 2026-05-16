import asyncio
from qobuz_dl.lyrics_engine import LyricsEngine

async def run():
    engine = LyricsEngine(translate=True, target_lang='pt')
    lyrics = "[00:10.00] This is a test\n[00:12.00] Testing the deep-translator\n[00:14.00] I hope it works"
    res = await engine._process_translation(lyrics, is_synced=True)
    print("Traduzido:\n", res)

asyncio.run(run())
