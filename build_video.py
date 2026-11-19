#!/usr/bin/env python3
"""Assemble memodesk-demo.mp4 from the Playwright recording.

Structure: 3.5s title card + recorded demo (with bottom step captions
taken from steps.json, shifted by the title length) + 3.5s end card.
Total is well under the 5-minute submission limit. No narration, no
faked footage: the middle section is the unedited browser recording.
"""
import glob
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 1280, 800
TITLE_LEN = 3.5
END_LEN = 3.5


def card(path, lines, accent):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), (15, 23, 42))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 8], fill=accent)
    d.rectangle([0, H - 8, W, H], fill=accent)
    y = 240
    for text, size, color in lines:
        f = ImageFont.truetype(FONT, size)
        bb = d.textbbox((0, 0), text, font=f)
        d.text(((W - (bb[2] - bb[0])) // 2, y), text, font=f, fill=color)
        y += (bb[3] - bb[1]) + 28
    img.save(path)


def main():
    webm = sorted(glob.glob(os.path.join(HERE, "video", "*.webm")))[-1]
    steps = json.load(open(os.path.join(HERE, "steps.json")))["steps"][1:]  # skip intro: title card says it
    # title card
    card(os.path.join(HERE, "video", "title.png"), [
        ("MemoDesk", 72, (56, 189, 248)),
        ("Support-ticket triage with Meko shared memory", 30, (226, 232, 240)),
        ("ContextCon hackathon  •  Theme: Support agents (+ auditability)", 24, (148, 163, 184)),
        ("Real local Meko MCP — no cloud account, no mocks, no LLM", 24, (148, 163, 184)),
    ], (56, 189, 248))
    # end card
    card(os.path.join(HERE, "video", "end.png"), [
        ("Verified live", 56, (74, 222, 128)),
        ("32 / 32 automated checks pass (test_memodesk.py)", 28, (226, 232, 240)),
        ("Meko MCP: 40 tools  •  cross-session recall proven", 24, (148, 163, 184)),
        ("Run it: meko start  +  python3 memodesk.py  →  127.0.0.1:8899", 24, (148, 163, 184)),
    ], (74, 222, 128))

    # caption text files (drawtext textfile= avoids shell-escaping pain)
    # Non-overlapping caption windows: each caption runs from its step
    # until the next step starts (max 3s); too-brief ones are dropped.
    starts = [TITLE_LEN + s["t"] for s in steps]
    filters = []
    for i, s in enumerate(steps):
        start = starts[i]
        end = min(start + 3.0,
                  starts[i + 1] if i + 1 < len(starts) else start + 3.0)
        if end - start < 1.0:
            continue
        txt = os.path.join(HERE, "video", f"cap{i}.txt")
        open(txt, "w").write(s["label"])
        filters.append(
            f"drawbox=y=ih-64:color=black@0.65:width=iw:height=64:t=fill:enable='between(t,{start:.1f},{end:.1f})',"
            f"drawtext=textfile='{txt}':fontfile={FONT}:fontsize=24:fontcolor=white:"
            f"x=24:y=h-46:enable='between(t,{start:.1f},{end:.1f})'")

    vf = ",".join(filters)
    out = os.path.join(HERE, "memodesk-demo.mp4")
    cmd = ["ffmpeg", "-y",
           "-loop", "1", "-t", str(TITLE_LEN), "-i", os.path.join(HERE, "video", "title.png"),
           "-i", webm,
           "-loop", "1", "-t", str(END_LEN), "-i", os.path.join(HERE, "video", "end.png"),
           "-filter_complex",
           f"[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];[v]{vf}[out]",
           "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", "30", out]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration,size", "-of", "json", out],
                           capture_output=True, text=True, check=True)
    print(probe.stdout)


if __name__ == "__main__":
    main()
