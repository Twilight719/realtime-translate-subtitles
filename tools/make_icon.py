# -*- coding: utf-8 -*-
"""生成应用图标：assets/icon.png（256px）与 assets/icon.ico（多尺寸）。

设计：圆角方形渐变底（应用主题蓝 #4f8cff → 紫），白色对话气泡，气泡内「文A」字样。
在 1024 大画布上绘制后缩到目标尺寸，保证小尺寸清晰。
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)

S = 1024          # 主画布
C1 = (79, 140, 255)    # #4f8cff 主题蓝
C2 = (122, 90, 248)    # #7a5af8 紫


def rounded_mask(size, box, radius, ss=4):
    """ supersample 的圆角矩形抗锯齿 mask """
    w = box[2] - box[0]
    h = box[3] - box[1]
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=radius * ss, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def make_master():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # ---- 渐变底（对角线方向） ----
    x = np.linspace(0, 1, S)
    y = np.linspace(0, 1, S)
    t = (x[None, :] + y[:, None]) / 2  # (S,S) 0..1
    grad = np.zeros((S, S, 4), dtype=np.uint8)
    for i in range(3):
        grad[..., i] = (np.array(C1[i]) * (1 - t) + np.array(C2[i]) * t).astype(np.uint8)
    grad[..., 3] = 255
    bg = Image.fromarray(grad, "RGBA")

    # 顶部高光，增加质感（高斯模糊柔化边缘）
    from PIL import ImageFilter
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    hd.ellipse([-S * 0.35, -S * 0.55, S * 0.9, S * 0.45], fill=(255, 255, 255, 34))
    hl = hl.filter(ImageFilter.GaussianBlur(60))
    bg = Image.alpha_composite(bg, hl)

    # 圆角方形底板（四周留边，Windows 图标惯例）
    pad = 72
    mask = rounded_mask(S, (pad, pad, S - pad, S - pad), radius=200)
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    base.paste(bg.crop((pad, pad, S - pad, S - pad)), (pad, pad), mask)

    d = ImageDraw.Draw(base)

    # ---- 白色对话气泡 ----
    bx0, by0, bx1, by1 = 208, 218, 816, 692
    br = 118
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=br, fill=(255, 255, 255, 255))
    # 气泡尾巴（左下）
    d.polygon([(bx0 + 92, by1 - 24), (bx0 + 60, by1 + 128), (bx0 + 250, by1 - 6)],
              fill=(255, 255, 255, 255))

    # ---- 「文A」字样 ----
    font_path = r"C:\Windows\Fonts\msyhbd.ttc"
    ink = (47, 96, 222, 255)  # 比底色略深的蓝，落在白底上更清晰
    f_zy = ImageFont.truetype(font_path, 336)
    f_a = ImageFont.truetype(font_path, 268)

    cx = (bx0 + bx1) // 2
    cy = (by0 + by1) // 2 - 18
    # 量「文」与「A」宽度，整体居中
    w_z = d.textlength("文", font=f_zy)
    w_a = d.textlength("A", font=f_a)
    gap = 26
    total = w_z + gap + w_a
    x0 = cx - total / 2
    d.text((x0, cy), "文", font=f_zy, fill=ink, anchor="lm")
    d.text((x0 + w_z + gap, cy + 44), "A", font=f_a, fill=ink, anchor="lm")

    return base


def main():
    master = make_master()
    master.save(os.path.join(ASSETS, "icon_1024.png"))

    icon256 = master.resize((256, 256), Image.LANCZOS)
    icon256.save(os.path.join(ASSETS, "icon.png"))

    ico = master.resize((256, 256), Image.LANCZOS)
    ico.save(
        os.path.join(ASSETS, "icon.ico"),
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
               (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("done:", ASSETS)


if __name__ == "__main__":
    main()
