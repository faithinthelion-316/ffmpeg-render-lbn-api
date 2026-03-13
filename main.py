from pydantic import BaseModel

import os
import uuid
import shutil
import subprocess
import base64
import re

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

app = FastAPI()

BASE_DIR = "/tmp/ffmpeg_render"
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
VIDEO_DIR = os.path.join(BASE_DIR, "video")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)

APP_FONTS_DIR = "/app/fonts"
APP_FONT_FILE = os.path.join(APP_FONTS_DIR, "BebasNeue-Regular.ttf")
RUNTIME_FONT_FILE = os.path.join(FONTS_DIR, "BebasNeue-Regular.ttf")

if os.path.exists(APP_FONT_FILE) and not os.path.exists(RUNTIME_FONT_FILE):
    shutil.copy(APP_FONT_FILE, RUNTIME_FONT_FILE)

app.mount("/video", StaticFiles(directory=VIDEO_DIR), name="video")


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


def build_title_only_filter(numero_regla: str) -> str:
    if not os.path.exists(RUNTIME_FONT_FILE):
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró la fuente en {RUNTIME_FONT_FILE}"
        )

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    return ",".join([
        (
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='REGLA INVISIBLE':"
            f"fontsize=57:"
            f"fontcolor=white:"
            f"borderw=2:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y=h*0.20"
        ),
        (
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='#{numero_regla}':"
            f"fontsize=57:"
            f"fontcolor=red:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y=h*0.25"
        )
    ])


def seconds_to_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_ass_text(text: str) -> str:
    return text.replace("{", r"\{").replace("}", r"\}")


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


def split_text_two_lines(text: str, max_line_chars: int = 26) -> str:
    words = text.split()
    if len(words) <= 1:
        return text

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
        line1 = " ".join(words[:midpoint])
        line2 = " ".join(words[midpoint:])
        return f"{line1}\\N{line2}"

    line1 = " ".join(words[:best_split_index])
    line2 = " ".join(words[best_split_index:])
    return f"{line1}\\N{line2}"


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

            if len(raw_text) > 26:
                cue_text = split_text_two_lines(raw_text.upper(), max_line_chars=26)
            else:
                cue_text = raw_text.upper()

            cues.append({
                "text": cue_text,
                "start": start_value,
                "end": end_value,
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


def write_ass_subtitles(subtitles_path: str, cues: list):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Bebas Neue,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,5,50,50,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(subtitles_path, "w", encoding="utf-8") as f:
        f.write(header)
        for cue in cues:
            start = seconds_to_ass_time(cue["start"])
            end = seconds_to_ass_time(cue["end"])
            text = escape_ass_text(cue["text"])
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


@app.get("/")
def health():
    return {
        "status": "running",
        "font_exists": os.path.exists(RUNTIME_FONT_FILE),
        "font_path": RUNTIME_FONT_FILE
    }


class RenderRequest(BaseModel):
    numero_regla: str
    guion: str
    subtitles_mode: str = "dynamic"
    audio_base64: str
    normalized_alignment: dict


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

    audio_duration = round(get_audio_duration(normalized_audio_path), 3)

    adjusted_alignment = speed_up_alignment(data.normalized_alignment, speed_factor)
    words = build_words_from_alignment(adjusted_alignment)
    cues = group_words_into_cues(words, max_words=8, max_chars=52)
    write_ass_subtitles(subtitles_path, cues)

    title_filter = build_title_only_filter(data.numero_regla)
    safe_subtitles_path = escape_ffmpeg_path(subtitles_path)
    safe_fonts_dir = escape_ffmpeg_path(FONTS_DIR)
    video_filter = f"{title_filter},subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'"
    render_mode = "title_plus_dynamic_subtitles"

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
                "video_path": video_path,
                "subtitles_path": subtitles_path,
                "audio_path": normalized_audio_path,
                "render_mode": render_mode,
                "cues_count": len(cues),
            }
        )

    if not os.path.exists(video_path):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "El video no se generó",
                "video_path": video_path,
                "subtitles_path": subtitles_path,
                "audio_path": normalized_audio_path,
                "render_mode": render_mode,
            }
        )

    return {
        "ok": True,
        "video_url": f"/video/{job_id}.mp4",
        "video_url_full": f"https://ffmpeg-render-api-production-1143.up.railway.app/video/{job_id}.mp4",
        "audio_duration": audio_duration,
        "subtitles_mode_received": data.subtitles_mode,
        "render_mode": render_mode,
        "cues_count": len(cues),
        "speed_factor": speed_factor
    }
