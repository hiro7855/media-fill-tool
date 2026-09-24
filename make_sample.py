# -*- coding: utf-8 -*-
"""Generate fake, desensitized boarding-pass-like screenshots for pipeline testing.
Chinese is rendered with Microsoft YaHei so the vision model can read it.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "输入" / "测试活动" / "张三"
OUT.mkdir(parents=True, exist_ok=True)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def draw_ticket(fname, lines, title):
    img = Image.new("RGB", (720, 460), "white")
    d = ImageDraw.Draw(img)
    f_title = load_font(34)
    f_big = load_font(28)
    f = load_font(24)
    f_small = load_font(20)

    d.rectangle([0, 0, 720, 70], fill="#1a5fb4")
    d.text((24, 18), title, font=f_title, fill="white")

    y = 100
    for kind, text in lines:
        fnt = {"big": f_big, "n": f, "s": f_small}[kind]
        color = "#c01c28" if kind == "big" else "black"
        d.text((30, y), text, font=fnt, fill=color)
        y += fnt.size + 16

    out = OUT / fname
    img.save(out)
    print(f"[OK] wrote {out}")


draw_ticket(
    "机票1.png",
    [
        ("s", "乘机人:张三          订单号:BX20260925001"),
        ("big", "MU5137   经济舱"),
        ("n", "2026-09-25 (周五)"),
        ("n", "上海虹桥 T2  08:30  -->  北京首都 T3  11:05"),
        ("s", "登机口 A12    座位 32K"),
    ],
    "电子行程单 / 去程",
)

draw_ticket(
    "机票2.png",
    [
        ("s", "乘机人:张三          订单号:BX20260927002"),
        ("big", "CA1858   经济舱"),
        ("n", "2026-09-27 (周日)"),
        ("n", "北京首都 T3  19:40  -->  上海虹桥 T2  22:10"),
        ("s", "登机口 C08    座位 15A"),
    ],
    "电子行程单 / 返程",
)

print("done")
