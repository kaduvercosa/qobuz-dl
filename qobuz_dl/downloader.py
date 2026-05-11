        if not abort_event.is_set():
                            file.write(_decrypt_qobuz_segment(seg_data, raw_key, segment_uuid))

        if abort_event.is_set(): return
        if not is_parallel:
            safe_print(f" {G}  > Assembling the final FLAC file...{O}")
            
        remux = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", tmp_fname, "-c:a", "copy", "-f", "flac", fname], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if remux.returncode != 0:
            raise ConnectionError(f"FFmpeg remux failed for {fname}")
        
        safe_print(f"{G}  L Completed: {track_name}{O}")

    finally:
        if os.path.isfile(tmp_fname):
            try: os.remove(tmp_fname)
            except OSError: pass


def _get_qobuz_segment_uuid(segment_data):
    pos = 0
    while pos + 24 <= len(segment_data):
        size = int.from_bytes(segment_data[pos : pos + 4], "big")
        if size <= 0 or pos + size > len(segment_data): break

        if bytes(segment_data[pos + 4 : pos + 8]) == b"uuid":
            return bytes(segment_data[pos + 8 : pos + 24])
        pos += size
    return None


def _decrypt_qobuz_segment(segment_data, raw_key, segment_uuid):
    if segment_uuid is None: return bytes(segment_data)

    buf = bytearray(segment_data)
    pos = 0
    while pos + 8 <= len(buf):
        size = int.from_bytes(buf[pos : pos + 4], "big")
        if size <= 0 or pos + size > len(buf): break

        if bytes(buf[pos + 4 : pos + 8]) == b"uuid" and bytes(buf[pos + 8 : pos + 24]) == segment_uuid:
            pointer = pos + 28
            data_end = pos + int.from_bytes(buf[pointer : pointer + 4], "big")
            pointer += 4
            counter_len = buf[pointer]
            pointer += 1
            frame_count = int.from_bytes(buf[pointer : pointer + 3], "big")
            pointer += 3

            for _ in range(frame_count):
                frame_len = int.from_bytes(buf[pointer : pointer + 4], "big")
                pointer += 6
                flags = int.from_bytes(buf[pointer : pointer + 2], "big")
                pointer += 2
                frame_start, data_end = data_end, data_end + frame_len

                if flags:
                    counter = bytes(buf[pointer : pointer + counter_len]) + (b"\x00" * (16 - counter_len))
                    decryptor = Cipher(algorithms.AES(raw_key), modes.CTR(counter)).decryptor()
                    buf[frame_start:data_end] = decryptor.update(bytes(buf[frame_start:data_end])) + decryptor.finalize()
                pointer += counter_len
        pos += size
    return bytes(buf)

def _download_goodies(album_meta, dirn):
    if abort_event.is_set(): return
    try:
        for goody in album_meta.get("goodies", []):
            if abort_event.is_set(): break
            if not goody.get("url"): continue
            goody_name = sanitize_filename(clean_filename(f'{album_meta.get("title")} ({goody.get("id")}).pdf'))
            _get_extra(goody.get("url"), dirn, extra=goody_name)
    except Exception as e:
        logger.error(f"{RED}Error downloading goodies: {e}", exc_info=True)


def _clean_embed_art(dirn, settings=None):
    embed_file = os.path.join(dirn, EMB_COVER_NAME)
    if os.path.exists(embed_file):
        try:
            time.sleep(0.5) 
            os.remove(embed_file)
        except OSError:
            pass