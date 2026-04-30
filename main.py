from pydantic import BaseModel

import os
import uuid
import shutil
import subprocess
import base64
import re
import unicodedata
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

app = FastAPI()

BASE_DIR = "/tmp/ffmpeg_render"
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
VIDEO_DIR = os.path.join(BASE_DIR, "video")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
IMAGE_DIR = os.path.join(BASE_DIR, "images")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")

MUSIC_FILE = "/app/music/background.mp3"

# Safe zone final con música.
END_TAIL_DURATION = 1.5

# Hook visual como shock card.
HOOK_CARD_START = 0.12
HOOK_CARD_END = 2.20

# Referencia bíblica más tarde y discreta.
REFERENCE_START_TIME = 6.0

# CTA visual final.
CTA_CARD_DURATION = 3.0

# Truth punch a mitad del video.
TRUTH_PUNCH_DURATION = 0.85

# Filtro leve para legibilidad del video AI.
AI_VIDEO_READABILITY_FILTER = "colorchannelmixer=rr=0.78:gg=0.78:bb=0.78"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

APP_FONTS_DIR = "/app/fonts"
APP_FONT_FILE = os.path.join(APP_FONTS_DIR, "BebasNeue-Regular.ttf")
RUNTIME_FONT_FILE = os.path.join(FONTS_DIR, "BebasNeue-Regular.ttf")

if os.path.exists(APP_FONT_FILE) and not os.path.exists(RUNTIME_FONT_FILE):
    shutil.copy(APP_FONT_FILE, RUNTIME_FONT_FILE)

app.mount("/video", StaticFiles(directory=VIDEO_DIR), name="video")

ASS_WHITE = r"\c&HFFFFFF&"
ASS_GOLD = r"\c&H5AC1E6&"

IMPACT_WORDS = {
    "DIOS",
    "NO",
    "VERDAD",
    "PAZ",
    "CULPA",
    "MIEDO",
    "PECADO",
    "CONTROL",
    "DOLOR",
    "HERIDA",
    "SOMBRA",
    "ALMA",
    "OBEDECER",
    "OBEDIENCIA",
    "ARREPENTIMIENTO",
    "GRACIA",
    "PERDON",
    "PERDÓN",
    "SANAR",
    "SANA",
    "SANÓ",
    "SANO",
    "ROTO",
    "ROTA",
    "ESCONDIDO",
    "ESCONDES",
    "EXAMÍNAME",
    "EXAMINAME",
    "VUELVE",
    "VOLVER",
}


def normalize_token(value: str) -> str:
    text = str(value or "").upper()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^A-ZÑÁÉÍÓÚÜ]+", "", text)
    return text


def escape_ffmpeg_path(path: str) -> str:
    return (
        path.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def escape_drawtext_value(value: str) -> str:
    if not value:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def clean_display_text(value: str, max_words: int = 5) -> str:
    text = str(value or "").strip()
    text = text.replace("“", "").replace("”", "").replace('"', "")
    text = re.sub(r"\s+", " ", text)
    text = text.upper()

    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]

    return " ".join(words).strip()


def split_headline(text: str) -> tuple[str, str]:
    words = clean_display_text(text, max_words=5).split()

    if not words:
        return "NO SIGAS", "IGUAL"

    if len(words) == 1:
        return "", words[0]

    if len(words) == 2:
        return words[0], words[1]

    # Última palabra = palabra de choque en dorado.
    top = " ".join(words[:-1])
    gold = words[-1]
    return top, gold


def extract_quoted_cta(call_to_action: str) -> str:
    text = str(call_to_action or "")

    match = re.search(r"[“\"]([^”\"]{2,80})[”\"]", text)
    if match:
        phrase = clean_display_text(match.group(1), max_words=4)
        if phrase:
            return phrase

    lowered = text.lower()

    if "examin" in lowered or "calma" in lowered or "paz" in lowered:
        return "EXAMÍNAME, DIOS"

    if "control" in lowered or "soltar" in lowered:
        return "RENUNCIO AL CONTROL"

    if "obedec" in lowered:
        return "QUIERO OBEDECER"

    if "volver" in lowered or "regresar" in lowered or "huir" in lowered:
        return "HAZME VOLVER"

    if "sana" in lowered or "herida" in lowered or "dolor" in lowered:
        return "SANA MI CORAZÓN"

    if "guía" in lowered or "guia" in lowered or "dirección" in lowered or "direccion" in lowered:
        return "SEÑOR, GUÍAME"

    return "DIOS, EXAMÍNAME"


def extract_truth_punch_text(guion: str) -> str:
    text = str(guion or "").strip()
    if not text:
        return "LA VERDAD DUELE"

    raw_sentences = re.split(r"(?<=[.!?])\s+", text)
    candidates = []

    triggers = [
        "pero",
        "peor",
        "no había",
        "no habia",
        "no siempre",
        "no sanan",
        "solo tapan",
        "seguía",
        "seguia",
        "sombra",
        "verdad",
        "obediencia",
        "arrepentimiento",
        "costumbre",
        "calma",
        "opresión",
        "opresion",
    ]

    for sentence in raw_sentences:
        clean = sentence.strip()
        if not clean:
            continue

        low = clean.lower()
        if any(t in low for t in triggers):
            words = clean_display_text(clean, max_words=5)
            if 2 <= len(words.split()) <= 5:
                candidates.append(words)

    if candidates:
        return candidates[min(len(candidates) // 2, len(candidates) - 1)]

    # Fallback: frase corta de mitad del guion.
    words = clean_display_text(text, max_words=5)
    return words or "LA VERDAD DUELE"


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


def download_file(url: str, path: str) -> str:
    urllib.request.urlretrieve(url, path)
    return path


def compute_scene_durations(total_duration: float, clip_count: int) -> list:
    """
    Ritmo más agresivo para Shorts:
    escena 1 corta, cambio visual temprano, cierre con CTA.
    """
    if clip_count <= 0:
        return []

    if clip_count == 1:
        return [max(0.5, total_duration)]

    # Para 5 clips: 0-3.5, 3.5-8.5, 8.5-15.5, 15.5-25.5, resto.
    base = [3.5, 5.0, 7.0, 10.0]

    durations = []
    remaining = max(0.5, total_duration)

    for i in range(clip_count):
        clips_left_after = clip_count - i - 1

        if i == clip_count - 1:
            durations.append(max(0.5, remaining))
            break

        desired = base[i] if i < len(base) else total_duration / clip_count
        max_allowed = max(0.5, remaining - (0.5 * clips_left_after))
        duration = min(desired, max_allowed)
        duration = max(0.5, duration)

        durations.append(duration)
        remaining -= duration

    return durations


def scene_crop_expression(scene_index: int) -> tuple[str, str]:
    """
    Movimiento artificial leve por escena sin filtros pesados.
    Trabaja sobre un frame escalado más grande que 720x1280.
    """
    patterns = [
        ("(iw-ow)/2+18*sin(t*0.8)", "(ih-oh)/2-10*cos(t*0.5)"),
        ("(iw-ow)/2-22*sin(t*0.55)", "(ih-oh)/2+12*sin(t*0.45)"),
        ("(iw-ow)/2+16*sin(t*0.45)", "(ih-oh)/2+16*cos(t*0.40)"),
        ("(iw-ow)/2-18*cos(t*0.50)", "(ih-oh)/2-14*sin(t*0.50)"),
        ("(iw-ow)/2+12*sin(t*0.35)", "(ih-oh)/2+10*cos(t*0.35)"),
    ]
    return patterns[scene_index % len(patterns)]


def build_background_from_videos(
    clip_paths: list,
    output_path: str,
    total_duration: float,
    job_id: str
) -> None:
    n = len(clip_paths)
    if n == 0:
        raise RuntimeError("No clip paths received")

    width = 720
    height = 1280
    fps = 24

    # Escalado mayor para permitir drift/punch sin bordes negros.
    scale_width = 820
    scale_height = 1458

    scene_durations = compute_scene_durations(total_duration, n)

    print(
        f"[{job_id}] scene_durations="
        f"{[round(x, 2) for x in scene_durations]}, "
        f"target_duration={total_duration:.2f}s",
        flush=True,
    )

    inputs = []
    for clip_path in clip_paths:
        inputs.extend(["-i", clip_path])

    filter_parts = []

    for i, clip_path in enumerate(clip_paths):
        target_scene_duration = max(0.5, float(scene_durations[i]))
        real_clip_duration = max(0.5, float(get_audio_duration(clip_path)))

        trim_duration = min(real_clip_duration, target_scene_duration)
        freeze_duration = max(0.0, target_scene_duration - real_clip_duration)

        crop_x, crop_y = scene_crop_expression(i)

        chain = (
            f"[{i}:v]"
            f"scale={scale_width}:{scale_height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='{crop_x}':y='{crop_y}',"
            f"setsar=1,"
            f"fps={fps},"
            f"trim=duration={trim_duration:.2f},"
            f"setpts=PTS-STARTPTS"
        )

        if freeze_duration > 0.1:
            chain += f",tpad=stop_mode=clone:stop_duration={freeze_duration:.2f}"

        chain += f",format=yuv420p[v{i}]"

        filter_parts.append(chain)

        print(
            f"[{job_id}] clip_{i + 1}: real={real_clip_duration:.2f}s, "
            f"target={target_scene_duration:.2f}s, "
            f"trim={trim_duration:.2f}s, "
            f"freeze={freeze_duration:.2f}s",
            flush=True,
        )

    concat_inputs = "".join(f"[v{i}]" for i in range(n))
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
        "-t", f"{total_duration:.2f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-movflags", "+faststart",
        output_path
    ]

    print(f"[{job_id}] build_background_from_videos cmd: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[{job_id}] build_background_from_videos stderr: {result.stderr}", flush=True)
        raise RuntimeError(f"build_background_from_videos failed: {result.stderr}")

    if not os.path.exists(output_path):
        raise RuntimeError("output background not created")


def build_background_from_images(
    image_paths: list,
    output_path: str,
    total_duration: float,
    job_id: str
) -> None:
    n = len(image_paths)
    if n == 0:
        raise RuntimeError("No image paths received")

    fps = 24
    width = 720
    height = 1280
    zp_width = 1080
    zp_height = 1920
    clip_duration = total_duration / n

    inputs = []
    for img_path in image_paths:
        inputs.extend(["-i", img_path])

    filter_parts = []

    for i in range(n):
        frames = max(1, int(round(clip_duration * fps)))

        filter_parts.append(
            f"[{i}:v]"
            f"scale=800:1422:force_original_aspect_ratio=increase,"
            f"crop=800:1422,"
            f"setsar=1,"
            f"zoompan="
            f"z='1+0.13*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={zp_width}x{zp_height}:"
            f"fps={fps},"
            f"scale={width}:{height}:flags=bicubic,"
            f"setpts=PTS-STARTPTS,"
            f"format=yuv420p"
            f"[v{i}]"
        )

    concat_inputs = "".join(f"[v{i}]" for i in range(n))
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

    print(f"[{job_id}] build_background_from_images cmd: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[{job_id}] build_background_from_images stderr: {result.stderr}", flush=True)
        raise RuntimeError(f"build_background_from_images failed: {result.stderr}")

    if not os.path.exists(output_path):
        raise RuntimeError("output background not created")


def build_reference_filter(referencia_biblica: str, start_time: float = REFERENCE_START_TIME) -> str:
    if not referencia_biblica or not referencia_biblica.strip():
        return ""

    if not os.path.exists(RUNTIME_FONT_FILE):
        return ""

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)
    safe_text = escape_drawtext_value(referencia_biblica.strip())

    if not safe_text:
        return ""

    return (
        f"drawtext="
        f"fontfile='{safe_font_path}':"
        f"text='{safe_text}':"
        f"fontsize=28:"
        f"fontcolor=0xA8A8A8:"
        f"borderw=1:"
        f"bordercolor=black:"
        f"shadowx=1:"
        f"shadowy=1:"
        f"x=(w-text_w)/2:"
        f"y=h*0.845:"
        f"enable='gte(t\\,{start_time:.2f})'"
    )


def build_hook_card_filters(hook_visual_text: str) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)
    top_line, gold_line = split_headline(hook_visual_text)

    top_line = escape_drawtext_value(top_line)
    gold_line = escape_drawtext_value(gold_line)

    enable_hook = f"between(t\\,{HOOK_CARD_START:.2f}\\,{HOOK_CARD_END:.2f})"
    enable_flash = f"between(t\\,0.00\\,{HOOK_CARD_START:.2f})"

    filters = [
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.85:t=fill:enable='{enable_flash}'",
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.28:t=fill:enable='{enable_hook}'",
        f"drawbox=x=45:y=390:w=630:h=320:color=black@0.52:t=fill:enable='{enable_hook}'",
        f"drawbox=x=45:y=390:w=630:h=320:color=0xDFAF37@0.18:t=5:enable='{enable_hook}'",
    ]

    if top_line:
        filters.append(
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='{top_line}':"
            f"fontsize=86:"
            f"fontcolor=white:"
            f"borderw=5:"
            f"bordercolor=black:"
            f"shadowx=2:"
            f"shadowy=2:"
            f"x=(w-text_w)/2:"
            f"y=455:"
            f"enable='{enable_hook}'"
        )

        filters.append(
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='{gold_line}':"
            f"fontsize=118:"
            f"fontcolor=0xE6C15A:"
            f"borderw=6:"
            f"bordercolor=black:"
            f"shadowx=3:"
            f"shadowy=3:"
            f"x=(w-text_w)/2:"
            f"y=555:"
            f"enable='{enable_hook}'"
        )
    else:
        filters.append(
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='{gold_line}':"
            f"fontsize=132:"
            f"fontcolor=0xE6C15A:"
            f"borderw=7:"
            f"bordercolor=black:"
            f"shadowx=3:"
            f"shadowy=3:"
            f"x=(w-text_w)/2:"
            f"y=510:"
            f"enable='{enable_hook}'"
        )

    return filters


def build_truth_punch_filters(guion: str, audio_duration: float) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    if audio_duration < 18:
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)
    punch_text = escape_drawtext_value(extract_truth_punch_text(guion))

    start_time = min(max(audio_duration * 0.48, 11.5), max(12.0, audio_duration - 8.0))
    end_time = min(audio_duration - 3.5, start_time + TRUTH_PUNCH_DURATION)

    if end_time <= start_time:
        return []

    enable = f"between(t\\,{start_time:.2f}\\,{end_time:.2f})"

    return [
        f"drawbox=x=70:y=475:w=580:h=180:color=black@0.55:t=fill:enable='{enable}'",
        f"drawbox=x=70:y=475:w=580:h=180:color=0xDFAF37@0.20:t=4:enable='{enable}'",
        f"drawtext="
        f"fontfile='{safe_font_path}':"
        f"text='{punch_text}':"
        f"fontsize=78:"
        f"fontcolor=0xE6C15A:"
        f"borderw=5:"
        f"bordercolor=black:"
        f"shadowx=2:"
        f"shadowy=2:"
        f"x=(w-text_w)/2:"
        f"y=530:"
        f"enable='{enable}'"
    ]


def build_cta_card_filters(call_to_action: str, audio_duration: float) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    if audio_duration < 8:
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    phrase = extract_quoted_cta(call_to_action)
    safe_phrase = escape_drawtext_value(phrase)

    start_time = max(HOOK_CARD_END + 1.0, audio_duration - CTA_CARD_DURATION)
    end_time = max(start_time + 0.5, audio_duration - 0.20)

    enable = f"between(t\\,{start_time:.2f}\\,{end_time:.2f})"

    return [
        f"drawbox=x=40:y=420:w=640:h=300:color=black@0.62:t=fill:enable='{enable}'",
        f"drawbox=x=40:y=420:w=640:h=300:color=0xDFAF37@0.22:t=5:enable='{enable}'",
        f"drawtext="
        f"fontfile='{safe_font_path}':"
        f"text='COMENTA':"
        f"fontsize=68:"
        f"fontcolor=white:"
        f"borderw=4:"
        f"bordercolor=black:"
        f"shadowx=2:"
        f"shadowy=2:"
        f"x=(w-text_w)/2:"
        f"y=470:"
        f"enable='{enable}'",
        f"drawtext="
        f"fontfile='{safe_font_path}':"
        f"text='“{safe_phrase}”':"
        f"fontsize=84:"
        f"fontcolor=0xE6C15A:"
        f"borderw=5:"
        f"bordercolor=black:"
        f"shadowx=2:"
        f"shadowy=2:"
        f"x=(w-text_w)/2:"
        f"y=565:"
        f"enable='{enable}'"
    ]


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


def split_word_items_two_lines(word_items: list, max_line_chars: int = 18) -> list:
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


def group_words_into_cues(words: list, max_words: int = 4, max_chars: int = 26) -> list:
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

        if cue["end"] - cue["start"] < 0.35:
            cue["end"] = cue["start"] + 0.35

    return cues


def build_line_groups(word_items: list, max_line_chars: int = 16) -> list:
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


def should_highlight_word(word: str) -> bool:
    normalized = normalize_token(word)
    if not normalized:
        return False

    normalized_impact = {normalize_token(x) for x in IMPACT_WORDS}
    return normalized in normalized_impact


def build_ass_dialogue_text(groups: list, active_index: int | None = None) -> str:
    line_texts = []

    for line in groups:
        parts = []
        for item in line:
            word_text = escape_ass_text(item["word"])
            is_active = active_index is not None and item["index"] == active_index
            is_impact = should_highlight_word(item["word"])

            if is_active or is_impact:
                parts.append(r"{" + ASS_GOLD + r"}" + word_text + r"{" + ASS_WHITE + r"}")
            else:
                parts.append(word_text)

        line_texts.append(" ".join(parts))

    prefix = r"{\an2\fs76\bord4\shad0\fscx100\fscy100\fsp0" + ASS_WHITE + r"}"
    return prefix + r"\N".join(line_texts)


def write_ass_subtitles(
    subtitles_path: str,
    cues: list,
    cta_start_time: float | None = None
):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Bebas Neue,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,80,80,285,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(subtitles_path, "w", encoding="utf-8") as f:
        f.write(header)

        for cue in cues:
            cue_start = float(cue["start"])
            cue_end = float(cue["end"])

            # Durante el shock card, no mostrar subtítulo normal.
            if cue_start < HOOK_CARD_END:
                continue

            # Durante el comment card final, no competir con caption normal.
            if cta_start_time is not None and cue_start >= cta_start_time:
                continue

            groups = build_line_groups(
                cue.get("words", []),
                max_line_chars=14
            )

            if not groups:
                continue

            flat_words = [item for line in groups for item in line]
            if not flat_words:
                continue

            segments = []
            cursor = cue_start
            eps = 0.01

            for item in flat_words:
                word_start = max(cue_start, float(item["start"]))
                word_end = min(cue_end, float(item["end"]))

                if cta_start_time is not None and word_start >= cta_start_time:
                    continue

                if cta_start_time is not None:
                    word_end = min(word_end, cta_start_time)

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

            if cta_start_time is not None:
                cue_end = min(cue_end, cta_start_time)

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
                text = build_ass_dialogue_text(
                    groups,
                    active_index=seg["active_index"],
                )
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


@app.get("/")
def health():
    return {
        "status": "running",
        "font_exists": os.path.exists(RUNTIME_FONT_FILE),
        "font_path": RUNTIME_FONT_FILE,
        "music_exists": os.path.exists(MUSIC_FILE),
        "music_path": MUSIC_FILE,
        "end_tail_duration": END_TAIL_DURATION,
        "hook_card_start": HOOK_CARD_START,
        "hook_card_end": HOOK_CARD_END,
        "reference_start_time": REFERENCE_START_TIME,
        "cta_card_duration": CTA_CARD_DURATION,
    }


class RenderRequest(BaseModel):
    numero_regla: str = ""
    hook: str = ""
    hook_visual_text: str = ""
    call_to_action: str = ""
    guion: str
    subtitles_mode: str = "dynamic"
    audio_base64: str
    normalized_alignment: dict

    referencia_biblica: str = ""

    video_url: str = ""
    video_url_2: str = ""
    video_url_3: str = ""
    video_url_4: str = ""
    video_url_5: str = ""

    image_url: str = ""
    image_url_2: str = ""
    image_url_3: str = ""
    image_url_4: str = ""
    image_url_5: str = ""


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

    voice_duration = round(get_audio_duration(normalized_audio_path), 3)
    target_duration = voice_duration + END_TAIL_DURATION

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
            (
                f"[0:a]volume=0.20[bg];"
                f"[1:a]apad=pad_dur={END_TAIL_DURATION},volume=1.4[voice];"
                f"[bg][voice]amix=inputs=2:duration=shortest:dropout_transition=2"
            ),
            "-t", f"{target_duration:.2f}",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            mixed_audio_path
        ]

        mix_result = subprocess.run(mix_cmd, capture_output=True, text=True)

        if mix_result.returncode == 0 and os.path.exists(mixed_audio_path):
            normalized_audio_path = mixed_audio_path
            print(
                f"[{job_id}] mixed voice+music with {END_TAIL_DURATION}s tail",
                flush=True
            )
        else:
            print(
                f"[{job_id}] mix failed: {mix_result.stderr}",
                flush=True
            )

    audio_duration = round(get_audio_duration(normalized_audio_path), 3)

    print(
        f"[{job_id}] voice_duration={voice_duration:.2f}s, "
        f"final_audio_duration={audio_duration:.2f}s",
        flush=True
    )

    cta_start_time = max(HOOK_CARD_END + 1.0, audio_duration - CTA_CARD_DURATION)

    adjusted_alignment = speed_up_alignment(data.normalized_alignment, speed_factor)
    words = build_words_from_alignment(adjusted_alignment)
    cues = group_words_into_cues(words, max_words=4, max_chars=26)
    write_ass_subtitles(subtitles_path, cues, cta_start_time=cta_start_time)

    safe_subtitles_path = escape_ffmpeg_path(subtitles_path)
    safe_fonts_dir = escape_ffmpeg_path(FONTS_DIR)

    reference_filter = build_reference_filter(
        data.referencia_biblica,
        start_time=REFERENCE_START_TIME
    )

    hook_text = data.hook_visual_text or data.hook or "NO SIGAS IGUAL"

    def compose_video_filter(prefix_filter: str = "") -> str:
        parts = []

        if prefix_filter:
            parts.append(prefix_filter)

        if reference_filter:
            parts.append(reference_filter)

        parts.append(f"subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'")

        # Overlays después de subtítulos para que el hook/truth/CTA sean dominantes.
        parts.extend(build_hook_card_filters(hook_text))
        parts.extend(build_truth_punch_filters(data.guion, audio_duration))
        parts.extend(build_cta_card_filters(data.call_to_action, audio_duration))

        return ",".join(parts)

    video_urls = []
    for url in [
        data.video_url,
        data.video_url_2,
        data.video_url_3,
        data.video_url_4,
        data.video_url_5,
    ]:
        if url and url.strip():
            video_urls.append(url.strip())

    image_urls = []
    for url in [
        data.image_url,
        data.image_url_2,
        data.image_url_3,
        data.image_url_4,
        data.image_url_5,
    ]:
        if url and url.strip():
            image_urls.append(url.strip())

    use_videos = len(video_urls) > 0
    use_images = (not use_videos) and len(image_urls) > 0
    render_mode = "black_background"
    media_count = 0

    if use_videos:
        try:
            clip_paths = []
            for i, url in enumerate(video_urls):
                clip_path = os.path.join(CLIPS_DIR, f"{job_id}_clip{i}.mp4")
                download_file(url, clip_path)
                clip_paths.append(clip_path)

            bg_video_path = os.path.join(CLIPS_DIR, f"{job_id}_bg.mp4")
            build_background_from_videos(clip_paths, bg_video_path, audio_duration, job_id)

            overlay_filter = AI_VIDEO_READABILITY_FILTER
            video_filter = compose_video_filter(overlay_filter)
            render_mode = f"ai_video_{len(clip_paths)}"
            media_count = len(clip_paths)

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
                "-crf", "26",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest",
                video_path
            ]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"build_background_from_videos fallo: {str(e)}"
            )

    elif use_images:
        try:
            image_paths = []
            for i, url in enumerate(image_urls):
                img_path = os.path.join(IMAGE_DIR, f"{job_id}_img{i}.jpg")
                download_file(url, img_path)
                image_paths.append(img_path)

            bg_video_path = os.path.join(IMAGE_DIR, f"{job_id}_bg.mp4")
            build_background_from_images(image_paths, bg_video_path, audio_duration, job_id)

            overlay_filter = "colorchannelmixer=rr=0.68:gg=0.68:bb=0.68"
            video_filter = compose_video_filter(overlay_filter)
            render_mode = f"static_image_{len(image_paths)}"
            media_count = len(image_paths)

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
            raise HTTPException(
                status_code=500,
                detail=f"build_background_from_images fallo: {str(e)}"
            )

    else:
        video_filter = compose_video_filter()

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

    base_url = os.environ.get(
        "BASE_URL",
        "https://ffmpeg-render-api-productionlbn.up.railway.app"
    )

    return {
        "ok": True,
        "video_url": f"/video/{job_id}.mp4",
        "video_url_full": f"{base_url}/video/{job_id}.mp4",
        "voice_duration": voice_duration,
        "audio_duration": audio_duration,
        "end_tail_duration": END_TAIL_DURATION,
        "subtitles_mode_received": data.subtitles_mode,
        "render_mode": render_mode,
        "cues_count": len(cues),
        "speed_factor": speed_factor,
        "music_used": os.path.exists(MUSIC_FILE),
        "media_count": media_count,
        "referencia_biblica_used": bool(data.referencia_biblica and data.referencia_biblica.strip()),
        "hook_received": bool(data.hook and data.hook.strip()),
        "hook_visual_text_received": bool(data.hook_visual_text and data.hook_visual_text.strip()),
        "call_to_action_received": bool(data.call_to_action and data.call_to_action.strip()),
        "cta_visual_phrase": extract_quoted_cta(data.call_to_action),
    }
