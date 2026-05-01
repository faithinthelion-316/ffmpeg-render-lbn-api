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

END_TAIL_DURATION = 2.8

HOOK_CARD_START = 0.12
HOOK_CARD_END = 2.20

HOOK_WORD_1_START = 0.12
HOOK_WORD_2_START = 0.30
HOOK_WORD_3_START = 0.55

REFERENCE_START_TIME = 6.0

CTA_CARD_DURATION = 2.4

TRUTH_PUNCH_DURATION = 1.35

AI_VIDEO_READABILITY_FILTER = "colorchannelmixer=rr=0.78:gg=0.78:bb=0.78"

FPS = 24
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280

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
    "HUIR",
    "HUÍA",
    "HUIA",
    "TORMENTA",
}


def normalize_token(value: str) -> str:
    text = str(value or "").upper()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^A-ZÑ]+", "", text)
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
        .replace(",", "\\,")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
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

    if len(words) == 3:
        return " ".join(words[:2]), words[2]

    top = " ".join(words[:-1])
    gold = words[-1]
    return top, gold


def build_hook_impact_lines(text: str) -> list[str]:
    words = clean_display_text(text, max_words=5).split()

    if not words:
        return ["NO", "SIGAS", "IGUAL"]

    if len(words) <= 3:
        return words

    first_line = " ".join(words[:-2])
    second_line = words[-2]
    third_line = words[-1]

    return [first_line, second_line, third_line]


def adjust_font_size_for_text(text: str, base_size: int, min_size: int = 72) -> int:
    plain = str(text or "").replace("\\,", ",")
    char_count = len(plain)

    if char_count <= 8:
        scale = 1.00
    elif char_count <= 10:
        scale = 0.92
    elif char_count <= 12:
        scale = 0.82
    elif char_count <= 15:
        scale = 0.72
    else:
        scale = 0.62

    return max(min_size, int(round(base_size * scale)))


def extract_quoted_cta(call_to_action: str, hook: str = "", guion: str = "") -> str:
    text = str(call_to_action or "")
    context = f"{call_to_action} {hook} {guion}".lower()

    match = re.search(r"[“\"]([^”\"]{2,80})[”\"]", text)
    if match:
        phrase = clean_display_text(match.group(1), max_words=4)
        if phrase:
            return phrase

    if "control" in context or "controlar" in context or "soltar" in context:
        return "RENUNCIO AL CONTROL"

    if "obedec" in context:
        return "QUIERO OBEDECER"

    if "tarsis" in context or "huir" in context or "huía" in context or "huia" in context or "regresar" in context or "volver" in context:
        return "HAZME VOLVER"

    if "examin" in context or "calma" in context or "paz" in context:
        return "DIOS, EXAMÍNAME"

    if "sana" in context or "herida" in context or "dolor" in context:
        return "SANA MI CORAZÓN"

    if "guía" in context or "guia" in context or "dirección" in context or "direccion" in context:
        return "SEÑOR, GUÍAME"

    if "miedo" in context or "temor" in context:
        return "NO TENGO MIEDO"

    return "DIOS, EXAMÍNAME"


def extract_truth_punch_text(guion: str) -> str:
    text = str(guion or "").strip().lower()

    if "control" in text or "controlar" in text or "mandaba" in text or "ruta" in text:
        return "ERA MIEDO"

    if "tarsis" in text or "huía" in text or "huia" in text or "huir" in text or "puerto" in text:
        return "HUÍA DE DIOS"

    if "tormenta" in text or "viento" in text or "mar" in text or "nave" in text:
        return "DIOS LO DETUVO"

    if "calma" in text or "paz" in text or "alivio" in text or "descanso" in text:
        return "NO ERA PAZ"

    if "verdad" in text or "confrontar" in text or "enfrentar" in text:
        return "LA VERDAD DUELE"

    if "miedo" in text or "temor" in text:
        return "ERA MIEDO"

    if "obedec" in text:
        return "TOCABA OBEDECER"

    if "culpa" in text or "escond" in text:
        return "DIOS LO VIO"

    if "dolor" in text or "herida" in text:
        return "AÚN DOLÍA"

    if "perdón" in text or "perdon" in text:
        return "GRACIA INMERECIDA"

    if "orgullo" in text or "soberbia" in text:
        return "ORGULLO ROTO"

    return "DIOS LO VIO"


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
    if clip_count <= 0:
        return []

    if clip_count == 1:
        return [max(0.5, total_duration)]

    if clip_count == 5:
        base = [3.8, 5.2, 7.2, 9.2]
    else:
        base = [total_duration / clip_count] * max(0, clip_count - 1)

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
    patterns = [
        ("(iw-ow)/2+16*sin(t*0.35)", "(ih-oh)/2-10*cos(t*0.25)"),
        ("(iw-ow)/2-18*sin(t*0.32)", "(ih-oh)/2+12*sin(t*0.25)"),
        ("(iw-ow)/2+14*sin(t*0.30)", "(ih-oh)/2+12*cos(t*0.24)"),
        ("(iw-ow)/2-16*cos(t*0.28)", "(ih-oh)/2-12*sin(t*0.24)"),
        ("(iw-ow)/2+10*sin(t*0.25)", "(ih-oh)/2+10*cos(t*0.22)"),
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

    scale_width = 820
    scale_height = 1458

    scene_durations = compute_scene_durations(total_duration, n)

    print(
        f"[{job_id}] clean_scene_durations="
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

        contrast = "eq=contrast=1.04:saturation=1.02"
        if i == 0:
            contrast = "eq=contrast=1.08:saturation=1.04"

        chain = (
            f"[{i}:v]"
            f"scale={scale_width}:{scale_height}:force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:x='{crop_x}':y='{crop_y}',"
            f"{contrast},"
            f"setsar=1,"
            f"fps={FPS},"
            f"trim=duration={trim_duration:.2f},"
            f"setpts=PTS-STARTPTS"
        )

        if freeze_duration > 0.1:
            chain += f",tpad=stop_mode=clone:stop_duration={freeze_duration:.2f}"

        chain += f",format=yuv420p[v{i}]"

        filter_parts.append(chain)

        print(
            f"[{job_id}] scene_{i + 1}: real={real_clip_duration:.2f}s, "
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
        "-crf", "24",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
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

    clip_duration = total_duration / n

    inputs = []
    for img_path in image_paths:
        inputs.extend(["-i", img_path])

    filter_parts = []

    for i in range(n):
        frames = max(1, int(round(clip_duration * FPS)))

        filter_parts.append(
            f"[{i}:v]"
            f"scale=800:1422:force_original_aspect_ratio=increase,"
            f"crop=800:1422,"
            f"setsar=1,"
            f"zoompan="
            f"z='1+0.11*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:"
            f"fps={FPS},"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=bicubic,"
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
        "-t", f"{total_duration:.2f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "27",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
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
        f"enable='gte(t\,{start_time:.2f})'"
    )


def add_pop_drawtext(
    filters: list,
    safe_font_path: str,
    text: str,
    final_size: int,
    fontcolor: str,
    center_y: int,
    start_time: float,
    end_time: float,
    borderw: int = 6,
    shadow: int = 3,
    overshoot_scale: float = 1.10,
    start_scale: float = 0.82,
):
    if not text:
        return

    phase1_end = min(end_time, start_time + 0.06)
    phase2_end = min(end_time, start_time + 0.14)

    phases = [
        (start_time, phase1_end, max(1, int(round(final_size * start_scale)))),
        (phase1_end, phase2_end, max(1, int(round(final_size * overshoot_scale)))),
        (phase2_end, end_time, final_size),
    ]

    for phase_start, phase_end, size in phases:
        if phase_end <= phase_start:
            continue

        enable = f"between(t\,{phase_start:.2f}\,{phase_end:.2f})"

        filters.append(
            f"drawtext="
            f"fontfile='{safe_font_path}':"
            f"text='{text}':"
            f"fontsize={size}:"
            f"fontcolor={fontcolor}:"
            f"borderw={borderw}:"
            f"bordercolor=black:"
            f"shadowx={shadow}:"
            f"shadowy={shadow}:"
            f"x=(w-text_w)/2:"
            f"y={center_y}-text_h/2:"
            f"enable='{enable}'"
        )


def build_hook_card_filters(hook_visual_text: str) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    lines = build_hook_impact_lines(hook_visual_text)
    safe_lines = [escape_drawtext_value(x) for x in lines if x and x.strip()]

    if not safe_lines:
        safe_lines = ["NO", "SIGAS", "IGUAL"]

    safe_lines = safe_lines[:3]

    enable_flash = f"between(t\,0.00\,{HOOK_CARD_START:.2f})"
    enable_card = f"between(t\,{HOOK_CARD_START:.2f}\,{HOOK_CARD_END:.2f})"

    filters = [
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.90:t=fill:enable='{enable_flash}'",
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.40:t=fill:enable='{enable_card}'",
        f"drawbox=x=24:y=285:w=672:h=610:color=black@0.68:t=fill:enable='{enable_card}'",
        f"drawbox=x=24:y=285:w=672:h=610:color=0xDFAF37@0.25:t=6:enable='{enable_card}'",
    ]

    if len(safe_lines) == 1:
        word = safe_lines[0]
        size = adjust_font_size_for_text(word, 210, min_size=120)
        add_pop_drawtext(
            filters=filters,
            safe_font_path=safe_font_path,
            text=word,
            final_size=size,
            fontcolor="0xFFD36A",
            center_y=585,
            start_time=HOOK_WORD_3_START,
            end_time=HOOK_CARD_END,
            borderw=9,
            shadow=4,
            overshoot_scale=1.12,
            start_scale=0.78,
        )
        return filters

    if len(safe_lines) == 2:
        first = safe_lines[0]
        second = safe_lines[1]

        first_size = adjust_font_size_for_text(first, 132, min_size=88)
        second_size = adjust_font_size_for_text(second, 204, min_size=126)

        add_pop_drawtext(
            filters=filters,
            safe_font_path=safe_font_path,
            text=first,
            final_size=first_size,
            fontcolor="white",
            center_y=470,
            start_time=HOOK_WORD_2_START,
            end_time=HOOK_CARD_END,
            borderw=6,
            shadow=3,
            overshoot_scale=1.08,
            start_scale=0.80,
        )

        add_pop_drawtext(
            filters=filters,
            safe_font_path=safe_font_path,
            text=second,
            final_size=second_size,
            fontcolor="0xFFD36A",
            center_y=660,
            start_time=HOOK_WORD_3_START,
            end_time=HOOK_CARD_END,
            borderw=9,
            shadow=4,
            overshoot_scale=1.12,
            start_scale=0.78,
        )

        return filters

    first = safe_lines[0]
    second = safe_lines[1]
    third = safe_lines[2]

    first_size = adjust_font_size_for_text(first, 92, min_size=70)
    second_size = adjust_font_size_for_text(second, 136, min_size=88)
    third_size = adjust_font_size_for_text(third, 196, min_size=120)

    add_pop_drawtext(
        filters=filters,
        safe_font_path=safe_font_path,
        text=first,
        final_size=first_size,
        fontcolor="white",
        center_y=395,
        start_time=HOOK_WORD_1_START,
        end_time=HOOK_CARD_END,
        borderw=5,
        shadow=2,
        overshoot_scale=1.06,
        start_scale=0.82,
    )

    add_pop_drawtext(
        filters=filters,
        safe_font_path=safe_font_path,
        text=second,
        final_size=second_size,
        fontcolor="white",
        center_y=535,
        start_time=HOOK_WORD_2_START,
        end_time=HOOK_CARD_END,
        borderw=7,
        shadow=3,
        overshoot_scale=1.08,
        start_scale=0.80,
    )

    add_pop_drawtext(
        filters=filters,
        safe_font_path=safe_font_path,
        text=third,
        final_size=third_size,
        fontcolor="0xFFD36A",
        center_y=715,
        start_time=HOOK_WORD_3_START,
        end_time=HOOK_CARD_END,
        borderw=9,
        shadow=4,
        overshoot_scale=1.12,
        start_scale=0.78,
    )

    return filters


def build_truth_punch_filters(guion: str, voice_duration: float) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    if voice_duration < 18:
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)
    punch_text = escape_drawtext_value(extract_truth_punch_text(guion))

    start_time = min(max(voice_duration * 0.48, 11.5), max(12.0, voice_duration - 8.0))
    end_time = min(voice_duration - 3.0, start_time + TRUTH_PUNCH_DURATION)

    if end_time <= start_time:
        return []

    enable = f"between(t\,{start_time:.2f}\,{end_time:.2f})"

    return [
        f"drawbox=x=100:y=500:w=520:h=150:color=black@0.58:t=fill:enable='{enable}'",
        f"drawbox=x=100:y=500:w=520:h=150:color=0xDFAF37@0.22:t=5:enable='{enable}'",
        f"drawtext="
        f"fontfile='{safe_font_path}':"
        f"text='{punch_text}':"
        f"fontsize=68:"
        f"fontcolor=0xE6C15A:"
        f"borderw=5:"
        f"bordercolor=black:"
        f"shadowx=2:"
        f"shadowy=2:"
        f"x=(w-text_w)/2:"
        f"y=545:"
        f"enable='{enable}'"
    ]


def build_cta_card_filters(
    call_to_action: str,
    hook: str,
    guion: str,
    cta_start_time: float,
    final_duration: float
) -> list:
    if not os.path.exists(RUNTIME_FONT_FILE):
        return []

    if final_duration < 8:
        return []

    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    phrase = extract_quoted_cta(call_to_action, hook=hook, guion=guion)
    safe_phrase = escape_drawtext_value(phrase)

    start_time = cta_start_time
    end_time = min(final_duration - 0.10, cta_start_time + CTA_CARD_DURATION)

    if end_time <= start_time + 0.4:
        return []

    enable = f"between(t\,{start_time:.2f}\,{end_time:.2f})"

    return [
        f"drawbox=x=40:y=420:w=640:h=300:color=black@0.64:t=fill:enable='{enable}'",
        f"drawbox=x=40:y=420:w=640:h=300:color=0xDFAF37@0.24:t=5:enable='{enable}'",
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


def validate_cta_for_render(call_to_action: str) -> None:
    text = str(call_to_action or "").strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "call_to_action llegó vacío. No se puede renderizar sin CTA final.",
                "expected_format": "Comenta “frase corta” si ...",
            }
        )

    if not text.startswith("Comenta "):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "call_to_action no empieza con 'Comenta '. No se puede garantizar la tarjeta CTA.",
                "call_to_action": text,
                "expected_format": "Comenta “frase corta” si ...",
            }
        )

    if not re.search(r"[“\"]([^”\"]{2,80})[”\"]", text):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "call_to_action no trae frase entre comillas. No se puede extraer texto para la tarjeta CTA.",
                "call_to_action": text,
                "expected_format": "Comenta “frase corta” si ...",
            }
        )


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

            if cue_start < HOOK_CARD_END:
                continue

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
        "hook_word_1_start": HOOK_WORD_1_START,
        "hook_word_2_start": HOOK_WORD_2_START,
        "hook_word_3_start": HOOK_WORD_3_START,
        "hook_card_mode": "staggered_vertical_pop_impact",
        "reference_start_time": REFERENCE_START_TIME,
        "cta_card_duration": CTA_CARD_DURATION,
        "truth_punch_duration": TRUTH_PUNCH_DURATION,
        "music_required": True,
        "cta_card_required": True,
        "voice_starts_at": "0.00s",
        "sfx_enabled": False,
        "render_style": "clean_5_scene_cinematic",
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

    validate_cta_for_render(data.call_to_action)

    job_id = str(uuid.uuid4())

    input_audio_path = os.path.join(AUDIO_DIR, f"{job_id}.mp3")
    voice_audio_path = os.path.join(AUDIO_DIR, f"{job_id}_voice.mp3")
    final_audio_path = os.path.join(AUDIO_DIR, f"{job_id}_final.mp3")
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
        voice_audio_path
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

    voice_duration = round(get_audio_duration(voice_audio_path), 3)
    final_duration = round(voice_duration + END_TAIL_DURATION, 3)
    cta_start_time = round(voice_duration + 0.05, 3)

    if not os.path.exists(MUSIC_FILE):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "MUSIC_FILE no existe. El render no debe producir cola final en silencio.",
                "music_path": MUSIC_FILE,
            }
        )

    mix_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-stream_loop", "-1",
        "-i", MUSIC_FILE,
        "-i", voice_audio_path,
        "-filter_complex",
        (
            f"[0:a]volume=0.24,"
            f"atrim=0:{final_duration:.2f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={max(0.0, final_duration - 0.8):.2f}:d=0.8[bg];"
            f"[1:a]volume=1.4,"
            f"apad=pad_dur={END_TAIL_DURATION},"
            f"atrim=0:{final_duration:.2f},"
            f"asetpts=PTS-STARTPTS[voice];"
            f"[bg][voice]amix=inputs=2:duration=longest:dropout_transition=0,"
            f"atrim=0:{final_duration:.2f}[aout]"
        ),
        "-map", "[aout]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        final_audio_path
    ]

    mix_result = subprocess.run(mix_cmd, capture_output=True, text=True)

    if mix_result.returncode != 0 or not os.path.exists(final_audio_path):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Error mezclando audio final",
                "returncode": mix_result.returncode,
                "stdout": mix_result.stdout,
                "stderr": mix_result.stderr,
            }
        )

    final_audio_duration = round(get_audio_duration(final_audio_path), 3)

    if final_audio_duration < final_duration - 0.25:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "El audio final quedó más corto que el video. Se cancela para evitar cola en silencio.",
                "voice_duration": voice_duration,
                "final_duration": final_duration,
                "final_audio_duration": final_audio_duration,
                "music_used": os.path.exists(MUSIC_FILE),
            }
        )

    print(
        f"[{job_id}] voice_duration={voice_duration:.2f}s, "
        f"final_duration={final_duration:.2f}s, "
        f"final_audio_duration={final_audio_duration:.2f}s, "
        f"cta_start_time={cta_start_time:.2f}s",
        flush=True
    )

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
    cta_phrase = extract_quoted_cta(data.call_to_action, hook=data.hook, guion=data.guion)
    cta_card_filters = build_cta_card_filters(
        data.call_to_action,
        hook=data.hook,
        guion=data.guion,
        cta_start_time=cta_start_time,
        final_duration=final_duration
    )

    if not cta_card_filters:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "CTA card no fue generada. Se cancela render para evitar final vacío.",
                "call_to_action": data.call_to_action,
                "cta_phrase": cta_phrase,
                "cta_start_time": cta_start_time,
                "final_duration": final_duration,
                "font_exists": os.path.exists(RUNTIME_FONT_FILE),
            }
        )

    def compose_video_filter(prefix_filter: str = "") -> str:
        parts = []

        if prefix_filter:
            parts.append(prefix_filter)

        if reference_filter:
            parts.append(reference_filter)

        parts.append(f"subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'")

        parts.extend(build_hook_card_filters(hook_text))
        parts.extend(build_truth_punch_filters(data.guion, voice_duration))
        parts.extend(cta_card_filters)

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
            build_background_from_videos(clip_paths, bg_video_path, final_duration, job_id)

            overlay_filter = AI_VIDEO_READABILITY_FILTER
            video_filter = compose_video_filter(overlay_filter)
            render_mode = f"ai_video_clean_{len(clip_paths)}"
            media_count = len(clip_paths)

            ffmpeg_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", bg_video_path,
                "-i", final_audio_path,
                "-vf", video_filter,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", f"{final_duration:.2f}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "26",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
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
            build_background_from_images(image_paths, bg_video_path, final_duration, job_id)

            overlay_filter = "colorchannelmixer=rr=0.68:gg=0.68:bb=0.68"
            video_filter = compose_video_filter(overlay_filter)
            render_mode = f"static_image_clean_{len(image_paths)}"
            media_count = len(image_paths)

            ffmpeg_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", bg_video_path,
                "-i", final_audio_path,
                "-vf", video_filter,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", f"{final_duration:.2f}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
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
            "-i", f"color=c=black:s=720x1280:r=24:d={final_duration}",
            "-i", final_audio_path,
            "-vf", video_filter,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", f"{final_duration:.2f}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
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
        "audio_duration": final_audio_duration,
        "final_duration": final_duration,
        "end_tail_duration": END_TAIL_DURATION,
        "cta_start_time": cta_start_time,
        "subtitles_mode_received": data.subtitles_mode,
        "render_mode": render_mode,
        "cues_count": len(cues),
        "speed_factor": speed_factor,
        "music_used": True,
        "media_count": media_count,
        "referencia_biblica_used": bool(data.referencia_biblica and data.referencia_biblica.strip()),
        "hook_received": bool(data.hook and data.hook.strip()),
        "hook_visual_text_received": bool(data.hook_visual_text and data.hook_visual_text.strip()),
        "call_to_action_received": bool(data.call_to_action and data.call_to_action.strip()),
        "cta_visual_phrase": cta_phrase,
        "truth_punch_text": extract_truth_punch_text(data.guion),
        "truth_punch_duration": TRUTH_PUNCH_DURATION,
        "hook_card_mode": "staggered_vertical_pop_impact",
        "hook_word_1_start": HOOK_WORD_1_START,
        "hook_word_2_start": HOOK_WORD_2_START,
        "hook_word_3_start": HOOK_WORD_3_START,
        "voice_starts_at": "0.00s",
        "sfx_enabled": False,
        "music_required": True,
        "cta_card_required": True,
        "render_style": "clean_5_scene_cinematic",
    }
