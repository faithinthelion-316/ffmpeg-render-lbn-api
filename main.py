from pydantic import BaseModel

import os
import uuid
import shutil
import subprocess
import base64
import re
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

app = FastAPI()

BASE_DIR = "/tmp/ffmpeg_render"
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
VIDEO_DIR = os.path.join(BASE_DIR, "video")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
IMAGE_DIR = os.path.join(BASE_DIR, "images")

MUSIC_FILE = "/app/music/background.mp3"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

APP_FONTS_DIR = "/app/fonts"
APP_FONT_FILE = os.path.join(APP_FONTS_DIR, "BebasNeue-Regular.ttf")
RUNTIME_FONT_FILE = os.path.join(FONTS_DIR, "BebasNeue-Regular.ttf")

if os.path.exists(APP_FONT_FILE) and not os.path.exists(RUNTIME_FONT_FILE):
    shutil.copy(APP_FONT_FILE, RUNTIME_FONT_FILE)

app.mount("/video", StaticFiles(directory=VIDEO_DIR), name="video")

# Mismo color para número y palabra activa
ASS_WHITE = r"\c&HFFFFFF&"
ASS_GOLD = r"\c&H5AC1E6&"   # equivalente ASS/BGR de 0xE6C15A


def escape_ffmpeg_path(path: str) -> str:
    return (
        path.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def get_audio_duration(audio_path: str) -> float:
    probes = [
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
    ]

    for cmd in probes:
        result = subprocess.run(cmd, capture_output=True, text=True)
        raw = (result.stdout or "").strip()
        if raw:
            for line in raw.splitlines():
                try:
                    value = float(line.strip())
                    if value > 0.2:
                        return value
                except Exception:
                    pass

    return 8.0


def download_image(image_url: str, path: str) -> str:
    urllib.request.urlretrieve(image_url, path)
    return path


def build_background(image_paths: list, output_path: str, total_duration: float, job_id: str) -> None:
    """
    Genera video de fondo con efecto Ken Burns suave por imagen
    y concatena todos los segmentos.
    """
    n = len(image_paths)
    if n == 0:
        raise RuntimeError("No image paths received")

    fps = 24
    clip_duration = total_duration / n

    inputs = []
    for img_path in image_paths:
        inputs.extend(["-loop", "1", "-t", f"{clip_duration:.3f}", "-i", img_path])

    filter_parts = []
    concat_inputs = ""

    for i in range(n):
        frames = max(1, int(round(clip_duration * fps)))

        filter_parts.append(
            f"[{i}:v]"
            f"scale=800:1422:force_original_aspect_ratio=increase,"
            f"zoompan="
            f"z='min(zoom+0.0007,1.08)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s=720x1280:"
            f"fps={fps},"
            f"setsar=1,"
            f"format=yuv420p,"
            f"trim=duration={clip_duration:.3f},"
            f"setpts=PTS-STARTPTS"
            f"[v{i}]"
        )
        concat_inputs += f"[v{i}]"

    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[outv]")
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path
    ]

    print(f"[{job_id}] build_background cmd: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[{job_id}] build_background stderr: {result.stderr}", flush=True)
        raise RuntimeError(f"build_background failed: {result.stderr}")

    if not os.path.exists(output_path):
        raise RuntimeError("output background not created")

    probe_result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", output_path
        ],
        capture_output=True, text=True
    )
    bg_duration = probe_result.stdout.strip()
    print(f"[{job_id}] Background video duration: {bg_duration}s (expected: {total_duration:.3f}s)", flush=True)
    print(f"[{job_id}] Images: {n}, clip_duration: {clip_duration:.3f}s each", flush=True)


def build_title_only_filter(numero_regla: str) -> str:
    if not os.path.exists(RUNTIME_FONT_FILE):
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró la fuente en {RUNTIME_FONT_FILE}"
        )

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    filters = [
        (
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='VERDAD':"
            f"fontsize=54:"
            f"fontcolor=white:"
            f"borderw=2:"
            f"bordercolor=black:"
            f"shadowx=1:"
            f"shadowy=1:"
            f"x=(w-text_w)/2:"
            f"y=h*0.20"
        ),
        (
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='#{numero_regla}':"
            f"fontsize=90:"
            f"fontcolor=0xE6C15A:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"shadowx=2:"
            f"shadowy=2:"
            f"x=(w-text_w)/2:"
            f"y=h*0.25"
        ),
    ]

    return ",".join(filters)


def seconds_to_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_ass_text(text: str) -> str:
    return (
        str(text)
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def speed_up_alignment(alignment: dict, speed: float) -> dict:
    return {
        "characters": alignment.get("characters", []),
        "character_start_times_seconds": [
            float(x) / speed for x in alignment.get("character_start_times_seconds", [])
        ],
        "character_end_times_seconds": [
            float(x) / speed for x in alignment.get("character_end_times_seconds", [])
        ],
    }


def build_words_from_alignment(alignment: dict) -> list:
    characters = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not characters or not starts or not ends:
        return []

    words = []
    current_chars = []
    current_start = None
    current_end = None

    for ch, st, en in zip(characters, starts, ends):
        try:
            st = float(st)
            en = float(en)
        except Exception:
            continue

        if str(ch).isspace():
            if current_chars:
                word = "".join(current_chars).strip()
                if word:
                    words.append({
                        "word": word,
                        "start": float(current_start),
                        "end": float(current_end),
                    })
                current_chars = []
                current_start = None
                current_end = None
            continue

        if current_start is None:
            current_start = st

        current_chars.append(str(ch))
        current_end = en

    if current_chars:
        word = "".join(current_chars).strip()
        if word:
            words.append({
                "word": word,
                "start": float(current_start),
                "end": float(current_end),
            })

    return words


def split_word_items_two_lines(word_items: list, max_line_chars: int = 26) -> list:
    if not word_items:
        return []

    words = [str(item["word"]) for item in word_items]
    if len(words) <= 1:
        return [word_items]

    best_split_index = None
    best_score = None

    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])

        if len(line1) > max_line_chars or len(line2) > max_line_chars:
            continue

        score = abs(len(line1) - len(line2))
        if best_score is None or score < best_score:
            best_score = score
            best_split_index = i

    if best_split_index is None:
        midpoint = len(words) // 2
        return [word_items[:midpoint], word_items[midpoint:]]

    return [word_items[:best_split_index], word_items[best_split_index:]]


def group_words_into_cues(words: list, max_words: int = 8, max_chars: int = 52) -> list:
    cues = []
    bucket = []

    def flush_bucket():
        nonlocal bucket
        if not bucket:
            return

        raw_text = " ".join(str(item["word"]) for item in bucket).strip()
        if raw_text:
            start_value = float(bucket[0]["start"])
            end_value = float(bucket[-1]["end"])

            cues.append({
                "text": raw_text.upper(),
                "start": start_value,
                "end": end_value,
                "words": [
                    {
                        "word": str(item["word"]).upper(),
                        "start": float(item["start"]),
                        "end": float(item["end"]),
                    }
                    for item in bucket
                ],
            })

        bucket = []

    for item in words:
        candidate_words = bucket + [item]
        candidate_text = " ".join(str(x["word"]) for x in candidate_words)

        punctuation_break = bool(re.search(r"[.!?,;:]$", str(item["word"])))
        too_many_words = len(candidate_words) > max_words
        too_many_chars = len(candidate_text) > max_chars

        if bucket and (too_many_words or too_many_chars):
            flush_bucket()

        bucket.append(item)

        if punctuation_break:
            flush_bucket()

    flush_bucket()

    for cue in cues:
        cue["start"] = float(cue["start"])
        cue["end"] = float(cue["end"])

        if cue["end"] - cue["start"] < 0.45:
            cue["end"] = cue["start"] + 0.45

    return cues


def build_line_groups(word_items: list, max_line_chars: int = 26) -> list:
    split_lines = split_word_items_two_lines(word_items, max_line_chars=max_line_chars)
    groups = []
    flat_index = 0

    for line_items in split_lines:
        group = []
        for item in line_items:
            group.append({
                "index": flat_index,
                "word": str(item["word"]).upper(),
                "start": float(item["start"]),
                "end": float(item["end"]),
            })
            flat_index += 1
        groups.append(group)

    return groups


def build_ass_dialogue_text(groups: list, active_index: int | None = None) -> str:
    line_texts = []

    for line in groups:
        parts = []
        for item in line:
            word_text = escape_ass_text(item["word"])
            if active_index is not None and item["index"] == active_index:
                parts.append(r"{" + ASS_GOLD + r"}" + word_text + r"{" + ASS_WHITE + r"}")
            else:
                parts.append(word_text)
        line_texts.append(" ".join(parts))

    return r"{\an2\bord3\shad0\fscx100\fscy100\fsp0" + ASS_WHITE + r"}" + r"\N".join(line_texts)


def write_ass_subtitles(subtitles_path: str, cues: list):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Bebas Neue,90,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,2,50,50,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(subtitles_path, "w", encoding="utf-8") as f:
        f.write(header)

        for cue in cues:
            groups = build_line_groups(cue.get("words", []), max_line_chars=26)
            if not groups:
                continue

            flat_words = [item for line in groups for item in line]
            if not flat_words:
                continue

            segments = []
            cue_start = float(cue["start"])
            cue_end = float(cue["end"])
            cursor = cue_start
            eps = 0.01

            for item in flat_words:
                word_start = max(cue_start, float(item["start"]))
                word_end = min(cue_end, float(item["end"]))

                if word_start > cursor + eps:
                    segments.append({
                        "start": cursor,
                        "end": word_start,
                        "active_index": None,
                    })

                if word_end > word_start + eps:
                    segments.append({
                        "start": word_start,
                        "end": word_end,
                        "active_index": item["index"],
                    })

                cursor = max(cursor, word_end)

            if cue_end > cursor + eps:
                segments.append({
                    "start": cursor,
                    "end": cue_end,
                    "active_index": None,
                })

            merged_segments = []
            for seg in segments:
                if seg["end"] <= seg["start"] + eps:
                    continue

                if (
                    merged_segments
                    and merged_segments[-1]["active_index"] == seg["active_index"]
                    and abs(merged_segments[-1]["end"] - seg["start"]) <= eps
                ):
                    merged_segments[-1]["end"] = seg["end"]
                else:
                    merged_segments.append(seg)

            for seg in merged_segments:
                start = seconds_to_ass_time(seg["start"])
                end = seconds_to_ass_time(seg["end"])
                text = build_ass_dialogue_text(groups, active_index=seg["active_index"])
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


@app.get("/")
def health():
    return {
        "status": "running",
        "font_exists": os.path.exists(RUNTIME_FONT_FILE),
        "font_path": RUNTIME_FONT_FILE,
        "music_exists": os.path.exists(MUSIC_FILE),
        "music_path": MUSIC_FILE
    }


class RenderRequest(BaseModel):
    numero_regla: str
    hook: str = ""
    guion: str
    subtitles_mode: str = "dynamic"
    audio_base64: str
    normalized_alignment: dict
    image_url: str = ""
    image_url_2: str = ""
    image_url_3: str = ""


@app.post("/render")
async def render_video(data: RenderRequest):
    if not os.path.exists(RUNTIME_FONT_FILE):
        raise HTTPException(
            status_code=500,
            detail=f"La fuente no existe en runtime: {RUNTIME_FONT_FILE}"
        )

    job_id = str(uuid.uuid4())

    input_audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
    normalized_audio_path = os.path.join(AUDIO_DIR, f"{job_id}_normalized.mp3")
    mixed_audio_path = os.path.join(AUDIO_DIR, f"{job_id}_mixed.mp3")
    subtitles_path = os.path.join(BASE_DIR, f"{job_id}.ass")
    video_path = os.path.join(VIDEO_DIR, f"{job_id}.mp4")

    try:
        audio_bytes = base64.b64decode(data.audio_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="audio_base64 inválido")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio_base64 llegó vacío")

    with open(input_audio_path, "wb") as f:
        f.write(audio_bytes)

    speed_factor = 1.3

    normalize_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", input_audio_path,
        "-vn",
        "-filter:a", f"atempo={speed_factor}",
        "-acodec", "libmp3lame",
        "-ar", "44100",
        "-ac", "2",
        "-b:a", "192k",
        normalized_audio_path
    ]

    normalize_result = subprocess.run(normalize_cmd, capture_output=True, text=True)

    if normalize_result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Error normalizando audio",
                "returncode": normalize_result.returncode,
                "stdout": normalize_result.stdout,
                "stderr": normalize_result.stderr,
            }
        )

    if os.path.exists(MUSIC_FILE):
        mix_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-stream_loop", "-1",
            "-i", MUSIC_FILE,
            "-i", normalized_audio_path,
            "-filter_complex",
            "[0:a]volume=0.20[bg];[1:a]volume=1.4[voice];[bg][voice]amix=inputs=2:duration=shortest:dropout_transition=2",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            mixed_audio_path
        ]

        mix_result = subprocess.run(mix_cmd, capture_output=True, text=True)

        if mix_result.returncode == 0 and os.path.exists(mixed_audio_path):
            normalized_audio_path = mixed_audio_path

    audio_duration = round(get_audio_duration(normalized_audio_path), 3)

    adjusted_alignment = speed_up_alignment(data.normalized_alignment, speed_factor)
    words = build_words_from_alignment(adjusted_alignment)
    cues = group_words_into_cues(words, max_words=8, max_chars=52)
    write_ass_subtitles(subtitles_path, cues)

    title_filter = build_title_only_filter(data.numero_regla)
    safe_subtitles_path = escape_ffmpeg_path(subtitles_path)
    safe_fonts_dir = escape_ffmpeg_path(FONTS_DIR)

    image_urls = []
    for url in [data.image_url, data.image_url_2, data.image_url_3]:
        if url and url.strip():
            image_urls.append(url.strip())

    use_images = len(image_urls) > 0
    render_mode = "black_background"
    images_used = 0

    if use_images:
        try:
            image_paths = []
            for i, url in enumerate(image_urls):
                img_path = os.path.join(IMAGE_DIR, f"{job_id}_img{i}.jpg")
                download_image(url, img_path)
                image_paths.append(img_path)

            bg_video_path = os.path.join(IMAGE_DIR, f"{job_id}_bg.mp4")
            build_background(image_paths, bg_video_path, audio_duration, job_id)

            overlay_filter = "colorchannelmixer=rr=0.80:gg=0.80:bb=0.80"
            video_filter = f"{overlay_filter},{title_filter},subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'"
            render_mode = f"multi_image_{len(image_paths)}"
            images_used = len(image_paths)

            ffmpeg_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", bg_video_path,
                "-i", normalized_audio_path,
                "-vf", video_filter,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest",
                video_path
            ]

        except Exception as e:
            use_images = False
            render_mode = f"fallback_{str(e)[:100]}"

    if not use_images:
        video_filter = f"{title_filter},subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'"

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=720x1280:r=24:d={audio_duration}",
            "-i", normalized_audio_path,
            "-vf", video_filter,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            video_path
        ]

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Error renderizando video",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "render_mode": render_mode,
            }
        )

    if not os.path.exists(video_path):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "El video no se generó",
                "render_mode": render_mode,
            }
        )

    return {
        "ok": True,
        "video_url": f"/video/{job_id}.mp4",
        "video_url_full": f"{os.environ.get('BASE_URL', 'https://ffmpeg-render-api-production-1143.up.railway.app')}/video/{job_id}.mp4",
        "audio_duration": audio_duration,
        "subtitles_mode_received": data.subtitles_mode,
        "render_mode": render_mode,
        "cues_count": len(cues),
        "speed_factor": speed_factor,
        "music_used": os.path.exists(MUSIC_FILE),
        "images_used": images_used
    }
