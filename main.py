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
CLIPS_DIR = os.path.join(BASE_DIR, "clips")

MUSIC_FILE = "/app/music/background.mp3"

# Segundos extra al final del video con música de fondo, sin voz.
END_TAIL_DURATION = 1.5

# Retención inicial: estilo especial solo para el hook inicial.
HOOK_CUE_MAX_START = 2.2

# La referencia bíblica aparece después del hook para no competir visualmente.
REFERENCE_START_TIME = 5.0

# Oscurecimiento suave para mejorar legibilidad sin apagar demasiado los clips AI.
AI_VIDEO_READABILITY_FILTER = "colorchannelmixer=rr=0.82:gg=0.82:bb=0.82"

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
    """Escapa caracteres especiales para el campo text= de drawtext."""
    if not value:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
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


def download_file(url: str, path: str) -> str:
    """Descarga cualquier archivo desde URL."""
    urllib.request.urlretrieve(url, path)
    return path


def compute_scene_durations(total_duration: float, clip_count: int) -> list:
    """
    Distribuye la duración visual para respetar la progresión narrativa:
    escena 1 corta e intensa, escenas medias progresivas, escena final con cierre.
    """
    if clip_count <= 0:
        return []

    if clip_count == 1:
        return [max(0.5, total_duration)]

    base = [5.0, 7.0, 8.0, 9.0]

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


def build_background_from_videos(
    clip_paths: list,
    output_path: str,
    total_duration: float,
    job_id: str
) -> None:
    """
    Optimización para Shorts:
    - Recorta cada clip según duración narrativa.
    - Scene 1 queda corta e intensa para apoyar el hook.
    - Si un clip dura menos que su segmento, congela su último frame.
    - Mantiene 720x1280, 24fps y preset ultrafast para no romper timeout.
    """
    n = len(clip_paths)
    if n == 0:
        raise RuntimeError("No clip paths received")

    width = 720
    height = 1280
    fps = 24

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

        chain = (
            f"[{i}:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
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
    """
    Versión legacy: aplica Ken Burns a imágenes estáticas.
    Se mantiene por compatibilidad y como fallback.
    """
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
            f"z='1+0.10*on/{frames}':"
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
    """
    Construye el drawtext de la referencia bíblica.
    Aparece pequeña, en gris claro, debajo del área de subtítulos.
    Para retención inicial, se oculta durante los primeros segundos.
    """
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
        f"fontsize=36:"
        f"fontcolor=0xB8B8B8:"
        f"borderw=2:"
        f"bordercolor=black:"
        f"shadowx=1:"
        f"shadowy=1:"
        f"x=(w-text_w)/2:"
        f"y=h*0.82:"
        f"enable='gte(t\\,{start_time:.2f})'"
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


def build_ass_dialogue_text(
    groups: list,
    active_index: int | None = None,
    is_hook: bool = False
) -> str:
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

    if is_hook:
        prefix = r"{\an2\fs92\bord4\shad0\fscx100\fscy100\fsp1" + ASS_WHITE + r"}"
    else:
        prefix = r"{\an2\fs72\bord3\shad0\fscx100\fscy100\fsp0" + ASS_WHITE + r"}"

    return prefix + r"\N".join(line_texts)


def write_ass_subtitles(subtitles_path: str, cues: list):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Bebas Neue,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,2,90,90,280,1
Style: Hook,Bebas Neue,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(subtitles_path, "w", encoding="utf-8") as f:
        f.write(header)

        for cue in cues:
            cue_start = float(cue["start"])
            cue_end = float(cue["end"])
            is_hook_cue = cue_start < HOOK_CUE_MAX_START

            groups = build_line_groups(
                cue.get("words", []),
                max_line_chars=14 if is_hook_cue else 20
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

            style_name = "Hook" if is_hook_cue else "Default"

            for seg in merged_segments:
                start = seconds_to_ass_time(seg["start"])
                end = seconds_to_ass_time(seg["end"])
                text = build_ass_dialogue_text(
                    groups,
                    active_index=seg["active_index"],
                    is_hook=is_hook_cue
                )
                f.write(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}\n")


@app.get("/")
def health():
    return {
        "status": "running",
        "font_exists": os.path.exists(RUNTIME_FONT_FILE),
        "font_path": RUNTIME_FONT_FILE,
        "music_exists": os.path.exists(MUSIC_FILE),
        "music_path": MUSIC_FILE,
        "end_tail_duration": END_TAIL_DURATION,
        "hook_cue_max_start": HOOK_CUE_MAX_START,
        "reference_start_time": REFERENCE_START_TIME,
    }


class RenderRequest(BaseModel):
    numero_regla: str = ""
    hook: str = ""
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

    adjusted_alignment = speed_up_alignment(data.normalized_alignment, speed_factor)
    words = build_words_from_alignment(adjusted_alignment)
    cues = group_words_into_cues(words, max_words=6, max_chars=40)
    write_ass_subtitles(subtitles_path, cues)

    safe_subtitles_path = escape_ffmpeg_path(subtitles_path)
    safe_fonts_dir = escape_ffmpeg_path(FONTS_DIR)

    reference_filter = build_reference_filter(
        data.referencia_biblica,
        start_time=REFERENCE_START_TIME
    )

    def compose_video_filter(prefix_filter: str = "") -> str:
        """
        Une los filtros en este orden:
        legibilidad / overlay -> referencia bíblica -> subtítulos.
        """
        parts = []
        if prefix_filter:
            parts.append(prefix_filter)
        if reference_filter:
            parts.append(reference_filter)
        parts.append(f"subtitles='{safe_subtitles_path}':fontsdir='{safe_fonts_dir}'")
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

            overlay_filter = "colorchannelmixer=rr=0.70:gg=0.70:bb=0.70"
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
        "hook_received": bool(data.hook and data.hook.strip())
    }
