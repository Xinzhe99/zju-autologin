"""生成 UI/托盘所需的图片资源（依赖 Pillow，仅开发期运行一次）。

产物（resources/ 下）：
  zju_logo.png       门户原始横版校徽（白色，透明底）
  zju_logo_blue.png  蓝色横版校徽（浅色背景用）
  zju_seal_blue.png  方形图标：蓝色圆角底 + 白色校徽印章（托盘/窗口图标用）
  zju.ico            多尺寸 Windows 图标
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.normpath(os.path.join(HERE, "..", "resources"))
ZJU_BLUE = (14, 65, 146, 255)  # 浙大蓝

os.makedirs(RES, exist_ok=True)
src = Image.open(os.path.join(RES, "zju_logo.png")).convert("RGBA")

# ---- 1. 蓝色横版：保留 alpha 形状，填充浙大蓝 ----
alpha = src.getchannel("A")
blue = Image.new("RGBA", src.size, ZJU_BLUE)
blue.putalpha(alpha)
# 裁掉透明边
bbox = blue.getbbox()
blue_tight = blue.crop(bbox)
blue_tight.save(os.path.join(RES, "zju_logo_blue.png"))

# ---- 2. 找出左侧圆形印章的列范围（alpha 投影上的第一段连续区域）----
proj = [min(255, px * 8) for px in (alpha.crop((x, 0, x + 1, src.height)).
        getbbox() and ((alpha.crop((x, 0, x + 1, src.height)).getbbox()[1] is not None)) * 255 or 0
        for x in range(src.width))]
# 简化：直接找第一段有内容的连续列区间，允许 12px 空隙
cols = [x for x in range(src.width) if alpha.crop((x, 0, x + 1, src.height)).getbbox()]
seal_end = cols[0]
for x in cols:
    if x - seal_end > 12:
        break
    seal_end = x
seal = src.crop((max(0, cols[0] - 2), 0, seal_end + 2, src.height))
sb = seal.getbbox()
seal = seal.crop(sb)
print("seal size:", seal.size)

# ---- 3. 方形图标：蓝色圆角底 + 白色印章 ----
SIZE = 256
icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base = Image.new("RGBA", (SIZE, SIZE), ZJU_BLUE)
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=56, fill=255)
icon.paste(base, (0, 0), mask)

seal_white = seal.copy()  # 印章本来就是白色
target = int(SIZE * 0.72)
ratio = target / max(seal_white.size)
seal_scaled = seal_white.resize((int(seal_white.width * ratio), int(seal_white.height * ratio)), Image.LANCZOS)
pos = ((SIZE - seal_scaled.width) // 2, (SIZE - seal_scaled.height) // 2)
icon.alpha_composite(seal_scaled, pos)
icon.save(os.path.join(RES, "zju_seal_blue.png"))

# ---- 4. 多尺寸 ico ----
icon.save(
    os.path.join(RES, "zju.ico"),
    sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)],
)
print("assets generated in", RES)
