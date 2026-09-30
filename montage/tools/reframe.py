"""Горизонтальное видео -> 1080x1920 с кадрированием по лицу.

    venv/bin/python reframe.py вход.mp4 выход.mp4

Лицо ищется каскадом Хаара раз в 3 кадра, центр кадрирования сглаживается,
чтобы камера не дёргалась. Лица нет — окно остаётся там, где было (в начале — центр).
Звук переносится из исходника через ffmpeg.
"""
import subprocess
import sys
import tempfile

import cv2

OUT_W, OUT_H = 1080, 1920
DETECT_EVERY = 3
SMOOTH = 0.15  # доля сдвига к новой цели за кадр


def main(src, dst):
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    crop_w = min(w, int(h * OUT_W / OUT_H))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (OUT_W, OUT_H))
    cx = target = w / 2
    frames = found = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frames % DETECT_EVERY == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(h // 10, h // 10))
            if len(faces):
                x, _, fw, _ = max(faces, key=lambda f: f[2] * f[3])
                target = x + fw / 2
                found += 1
        cx += (target - cx) * SMOOTH
        left = int(min(max(cx - crop_w / 2, 0), w - crop_w))
        writer.write(cv2.resize(frame[:, left:left + crop_w], (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4))
        frames += 1
    cap.release()
    writer.release()

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", "-shortest", dst],
                   check=True)
    checks = (frames + DETECT_EVERY - 1) // DETECT_EVERY
    print(f"кадров {frames}, лицо найдено в {found} из {checks} проверок -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
