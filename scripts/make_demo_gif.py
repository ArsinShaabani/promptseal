"""Generate the PromptSeal hero demo GIF (assets/demo.gif) with Pillow only.

Run from the repo root:  .venv/Scripts/python scripts/make_demo_gif.py
Requires: pip install pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = r"C:\Windows\Fonts\consola.ttf"
FONT_SIZE = 15
LINE_H = 19
PAD = 26
COLS = 88

FONT = ImageFont.truetype(FONT_PATH, FONT_SIZE)
CHAR_W = FONT.getbbox("M")[2] - FONT.getbbox("M")[0]
WIDTH = PAD * 2 + COLS * CHAR_W
TITLE_H = 34
MAX_LINES = 24
HEIGHT = TITLE_H + PAD + MAX_LINES * LINE_H + PAD

BG = (13, 17, 23)
TITLE_BG = (22, 27, 34)
FG = (201, 209, 217)
DIM = (110, 118, 129)
CYAN = (88, 166, 255)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
BORDER = (48, 54, 61)

PROMPT = "$ "

SEAL_OUT = [
    ("   pass rate: 100% (2/2) · failed 0 · errors 0 · latency 24ms · cost $0.0000", DIM),
    ("", FG),
    ("┏━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓", DIM),
    ("┃ Case          ┃ Status ┃ Latency ┃ Checks          ┃", FG),
    ("┡━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩", DIM),
    ("│ echo-greeting │  PASS  │   12ms  │ ✔ contains      │", GREEN),
    ("│               │        │         │ ✔ max_latency_s │", GREEN),
    ("│ echo-content  │  PASS  │   12ms  │ ✔ contains      │", GREEN),
    ("└───────────────┴────────┴─────────┴─────────────────┘", DIM),
    ("", FG),
    ("All cases passed. You're sealed.", GREEN),
    ("   baseline sealed: 20260929-120001-mock-echo", DIM),
]

RUN_OUT = [
    ("   pass rate: 87% (13/15) · failed 2 · errors 0 · latency 9.2s · cost $0.0041", DIM),
    ("│ pii-guard      │  FAIL  │  812ms │ ✘ llm_judge (revealed address)│", RED),
    ("│ order-status   │  PASS  │  640ms │ ✔ json_valid ✔ max_latency_s  │", GREEN),
    ("│ refund-tone    │  FAIL  │  733ms │ ✘ llm_judge (cold, abrupt)    │", RED),
    ("", FG),
    ("Some cases failed — check the details above.", RED),
]

DIFF_OUT = [
    ("🦭 Diff  baseline mock:echo  →  candidate openai:gpt-4o", FG),
    ("   pass rate: 100% → 87%", DIM),
    ("┃ Case        ┃ Baseline ┃ Candidate ┃ Note       ┃", FG),
    ("│ pii-guard   │   pass   │    fail   │ regression │", RED),
    ("│ refund-tone │   pass   │    fail   │ regression │", RED),
    ("│ order-status│   fail   │   pass    │ improvement│", GREEN),
    ("", FG),
    ("Verdict: REGRESSION — 2 case(s) got worse.", RED),
    ("", FG),
    ("Fix the prompt, or re-seal if this behavior is intended.", DIM),
]

END_CARD = [
    ("", FG),
    ("  PromptSeal — regression testing for prompts, agents & models", FG),
    ("  github.com/ArsinShaabani/promptseal", CYAN),
    ("", FG),
    ("  seal it before you ship it", GREEN),
]


def build_timeline():
    """Return a list of frames; each frame is a list of (text, color) lines."""
    frames = []

    def typing(cmd):
        for i in range(3, len(cmd) + 1, 3):
            frames.append([(PROMPT + cmd[:i], CYAN)])
        frames.append([(PROMPT + cmd, CYAN)])

    def reveal(lines, per_frame=3, pause_last=6):
        for i in range(0, len(lines), per_frame):
            frames.append(lines[: i + per_frame])
        for _ in range(pause_last):
            frames.append(list(lines))

    typing("promptseal seal")
    reveal(SEAL_OUT)

    frames.append([(PROMPT + "promptseal run -p openai:gpt-4o", CYAN)])
    reveal(RUN_OUT)

    typing("promptseal diff")
    reveal(DIFF_OUT)

    reveal(END_CARD, per_frame=2, pause_last=10)
    return frames


def render(lines):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, TITLE_H], fill=TITLE_BG)
    draw.line([0, TITLE_H, WIDTH, TITLE_H], fill=BORDER, width=1)
    for i, cx in enumerate((18, 40, 62)):
        draw.ellipse([cx, 12, cx + 10, 22], fill=[(255, 95, 86), (255, 189, 46), (39, 201, 63)][i])
    draw.text((WIDTH // 2 - 150, 8), "promptseal — zsh", fill=DIM, font=FONT)

    y = TITLE_H + PAD
    shown = lines[-(MAX_LINES - 1):]
    if any(l[0].startswith(PROMPT) for l in shown):
        shown = shown + [((PROMPT if shown[-1][0] == "" or not shown[-1][0].startswith(PROMPT) else ""), CYAN)]
        draw_cursor = True
    else:
        draw_cursor = False
    for text, color in shown:
        draw.text((PAD, y), text, fill=color, font=FONT)
        y += LINE_H
    if draw_cursor:
        draw.rectangle([PAD + CHAR_W * len(shown[-1][0]), y, PAD + CHAR_W * (len(shown[-1][0]) + 1), y + LINE_H - 4], fill=FG)
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BORDER, width=1)
    return img


def main():
    frames = build_timeline()
    images = [render(f) for f in frames]
    out = Path(__file__).resolve().parents[1] / "assets" / "demo.gif"
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=120,
        loop=0,
        optimize=True,
    )
    print(f"GIF written: {out} ({out.stat().st_size / 1024:.0f} KB, {len(images)} frames)")


if __name__ == "__main__":
    main()
