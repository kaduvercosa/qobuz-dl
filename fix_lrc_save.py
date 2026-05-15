import re

with open("qobuz_dl/lyrics_engine.py", "r") as f:
    code = f.read()

# _save_lrc_file receives `synced_lyrics`. If `final_lyrics` is already containing translations (from _process_translation), `_save_lrc_file` will just save it. Wait, `fetch_and_inject` does pass `final_lyrics`:
# final_lyrics = await self._process_translation(synced_lyrics, is_synced=True)
# self._inject_metadata(file_path, final_lyrics)
# if save_lrc:
#     self._save_lrc_file(file_path, final_lyrics)
