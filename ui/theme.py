"""亮白电商工作台主题"""

from pathlib import Path

import gradio as gr

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CSS_FILE = ASSETS_DIR / "theme.css"


def load_css() -> str:
    """读取自定义样式；文件缺失时返回空串，保证页面仍可启动"""
    try:
        return CSS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_theme() -> gr.themes.Base:
    """白底蓝主色，接近千牛 / 商家后台的视觉习惯"""
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.blue,
        secondary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.slate,
        radius_size=gr.themes.sizes.radius_lg,
        font=[
            "Inter",
            "HarmonyOS Sans SC",
            "Microsoft YaHei",
            "PingFang SC",
            "system-ui",
            "sans-serif",
        ],
    )
