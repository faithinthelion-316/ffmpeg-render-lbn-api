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


def get_audio_duration(audio_path: str) -> float:
    probes = [
        [
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        [
            "ffprobe","-v","error",
            "-show_entries","stream=duration",
            "-of","default=noprint_wrappers=1:nokey=1",
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
                except:
                    pass

    return 8.0


def download_image(image_url: str, path: str) -> str:
    urllib.request.urlretrieve(image_url, path)
    return path


def build_background(image_paths: list, output_path: str, total_duration: float, job_id: str) -> None:
    n = len(image_paths)
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

    cmd = [
        "ffmpeg","-hide_banner","-loglevel","warning","-y",
        *inputs,
        "-filter_complex",";".join(filter_parts),
        "-map","[outv]",
        "-c:v","libx264",
        "-preset","ultrafast",
        "-crf","28",
        "-pix_fmt","yuv420p",
        "-movflags","+faststart",
        output_path
    ]

    subprocess.run(cmd, capture_output=True, text=True)


def build_title_only_filter(numero_regla: str) -> str:
    safe_font_path = escape_ffmpeg_path(RUNTIME_FONT_FILE)

    return ",".join([
        f"drawtext=fontfile='{safe_font_path}':text='VERDAD':fontsize=54:fontcolor=white:borderw=2:bordercolor=black:shadowx=1:shadowy=1:x=(w-text_w)/2:y=h*0.20",
        f"drawtext=fontfile='{safe_font_path}':text='#{numero_regla}':fontsize=90:fontcolor=0xE6C15A:borderw=4:bordercolor=black:shadowx=2:shadowy=2:x=(w-text_w)/2:y=h*0.28"
    ])


def seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def escape_ass_text(text: str) -> str:
    return str(text).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def speed_up_alignment(alignment: dict, speed: float) -> dict:
    return {
        "characters": alignment.get("characters", []),
        "character_start_times_seconds": [float(x)/speed for x in alignment.get("character_start_times_seconds", [])],
        "character_end_times_seconds": [float(x)/speed for x in alignment.get("character_end_times_seconds", [])],
    }


def build_words_from_alignment(alignment: dict) -> list:
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    words, buffer = [], []
    start = None

    for ch, st, en in zip(chars, starts, ends):
        if str(ch).isspace():
            if buffer:
                words.append({"word":"".join(buffer),"start":start,"end":en})
                buffer, start = [], None
            continue

        if start is None:
            start = st
        buffer.append(ch)

    if buffer:
        words.append({"word":"".join(buffer),"start":start,"end":ends[-1]})

    return words


def group_words_into_cues(words: list) -> list:
    cues = []
    bucket = []

    for w in words:
        bucket.append(w)
        if len(bucket) >= 8 or re.search(r"[.!?,;:]$", w["word"]):
            cues.append(bucket)
            bucket = []

    if bucket:
        cues.append(bucket)

    return [
        {
            "text":" ".join(x["word"] for x in c).upper(),
            "start":c[0]["start"],
            "end":c[-1]["end"],
            "words":[{"word":x["word"].upper(),"start":x["start"],"end":x["end"]} for x in c]
        } for c in cues
    ]


def build_ass_dialogue_text(words, active=None):
    line = []
    for i,w in enumerate(words):
        t = escape_ass_text(w["word"])
        if active == i:
            line.append(f"{{{ASS_GOLD}}}{t}{{{ASS_WHITE}}}")
        else:
            line.append(t)
    return r"{\an2\bord3}" + " ".join(line)


def write_ass_subtitles(path, cues):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Default,Bebas Neue,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,1,3,0,2,50,50,120

[Events]
Format: Layer, Start, End, Style, Text
"""

    with open(path,"w") as f:
        f.write(header)

        for cue in cues:
            for i,w in enumerate(cue["words"]):
                f.write(
                    f"Dialogue: 0,{seconds_to_ass_time(w['start'])},{seconds_to_ass_time(w['end'])},Default,,{build_ass_dialogue_text(cue['words'],i)}\n"
                )
