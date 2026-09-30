"""Субтитры по словам: faster-whisper -> .ass (подсветка текущего слова) -> вжечь в видео.

    venv/bin/python subs.py видео.mp4 выход.mp4 [--model large-v3-turbo]

Модель без NVIDIA: large-v3-turbo, int8 на CPU. Нужен доступ к huggingface.co
при первом запуске (модель скачивается в tools/hf).
"""
import argparse
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "hf"))

from faster_whisper import WhisperModel  # noqa: E402

WORDS_PER_LINE = 3


def ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words, w, h):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,DejaVu Sans,{h // 22},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,{h // 320},0,2,60,60,{h // 4},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), WORDS_PER_LINE):
        group = words[i:i + WORDS_PER_LINE]
        for j, cur in enumerate(group):
            end = group[j + 1].start if j + 1 < len(group) else cur.end
            text = " ".join(
                (r"{\c&H4AB0E8&}" + x.word.strip() + r"{\c&HFFFFFF&}") if k == j else x.word.strip()
                for k, x in enumerate(group))
            lines.append(f"Dialogue: 0,{ts(cur.start)},{ts(end)},Word,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--model", default="large-v3-turbo")
    a = ap.parse_args()

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", a.src],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])

    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(a.src, language="ru", word_timestamps=True, vad_filter=True)
    words = [wd for seg in segments for wd in seg.words]
    print(" ".join(f"{x.word.strip()}[{x.start:.2f}-{x.end:.2f}]" for x in words))

    ass = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
    ass.write(build_ass(words, w, h))
    ass.close()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-vf", f"ass={ass.name}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "copy", a.dst], check=True)
    print(f"слов {len(words)} -> {a.dst}")


if __name__ == "__main__":
    main()
