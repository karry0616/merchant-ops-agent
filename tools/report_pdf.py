"""3C 技术尽调报告 PDF 导出（ReportLab + 中文字体）"""

from __future__ import annotations

import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "reports"
)

FONT_NAME = "CNReport"
_font_ready = False


def _ensure_font() -> str:
    """注册中文字体：优先系统雅黑，失败退回 ReportLab 内置 CID 字体"""
    global _font_ready
    if _font_ready:
        return FONT_NAME

    candidates = [
        (r"C:\Windows\Fonts\msyh.ttc", 0),
        (r"C:\Windows\Fonts\msyhbd.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ]
    for path, index in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, path, subfontIndex=index))
            _font_ready = True
            return FONT_NAME
        except Exception:  # noqa: BLE001
            continue

    # 兜底：内置宋体 CID 字体，无需外部字体文件
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _font_ready = True
    return "STSong-Light"


def _styles(font: str) -> dict:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "title": ParagraphStyle(
            "T", parent=base, fontName=font, fontSize=20, leading=28,
            textColor=colors.HexColor("#0F172A"), spaceAfter=6,
        ),
        "sub": ParagraphStyle(
            "S", parent=base, fontName=font, fontSize=9.5, leading=15,
            textColor=colors.HexColor("#64748B"), spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base, fontName=font, fontSize=13, leading=19,
            textColor=colors.HexColor("#0F172A"), spaceBefore=14, spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "B", parent=base, fontName=font, fontSize=10, leading=17,
            textColor=colors.HexColor("#334155"), alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "C", parent=base, fontName=font, fontSize=9, leading=14,
            textColor=colors.HexColor("#1E293B"),
        ),
        "cell_head": ParagraphStyle(
            "CH", parent=base, fontName=font, fontSize=9, leading=14,
            textColor=colors.HexColor("#475569"),
        ),
    }


def _table(data: list[list], widths: list[float], styles: dict) -> Table:
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F8FD")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
                ("FONTNAME", (0, 0), (-1, -1), _ensure_font()),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3EDF7")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3EDF7")),
            ]
        )
    )
    return table


def build_tech_pdf(payload: dict) -> str:
    """生成 3C 技术尽调 PDF，返回文件路径"""
    font = _ensure_font()
    styles = _styles(font)
    products = payload.get("products", [])
    axes = payload.get("axes", [])
    sources = payload.get("sources", [])
    compare = payload.get("mode") == "compare" and len(products) > 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now()
    title = "3C 产品技术尽调报告"
    filename = f"3C技术尽调_{stamp:%Y%m%d_%H%M%S}.pdf"
    path = os.path.join(OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="商家智能运营工作台",
    )

    story = [
        Paragraph(title, styles["title"]),
        Paragraph(
            f"生成时间：{stamp:%Y-%m-%d %H:%M}　|　分析对象："
            + "、".join(p.get("name", "-") for p in products)
            + "　|　分析方式："
            + ("双竞品对比" if compare else "单产品分析"),
            styles["sub"],
        ),
    ]

    # ── 产品概览 ──
    story.append(Paragraph("一、产品技术概览", styles["h2"]))
    head = [Paragraph("项目", styles["cell_head"])] + [
        Paragraph(p.get("name", "-"), styles["cell_head"]) for p in products
    ]
    rows = [
        head,
        ["通信协议"] + [p.get("protocol", "未识别") for p in products],
        ["芯片方案"] + [p.get("chip", "未识别") for p in products],
        ["技术壁垒"] + [f"{p.get('barrier', '未识别')}" for p in products],
    ]
    cell_rows = [rows[0]] + [
        [Paragraph(str(r[0]), styles["cell"]), *[Paragraph(str(v), styles["cell"]) for v in r[1:]]]
        for r in rows[1:]
    ]
    widths = [30 * mm] + [(170 * mm - 30 * mm) / max(len(products), 1)] * max(len(products), 1)
    story.append(_table(cell_rows, widths, styles))

    # ── 五维评分 ──
    if axes and products:
        story.append(Paragraph("二、五维技术评分（0-5 分）", styles["h2"]))
        score_head = [Paragraph("维度", styles["cell_head"])] + [
            Paragraph(p.get("name", "-"), styles["cell_head"]) for p in products
        ]
        if compare:
            score_head.append(Paragraph("差值（A-B）", styles["cell_head"]))
        score_rows = [score_head]
        for axis in axes:
            values = []
            for p in products:
                try:
                    values.append(float(p.get("scores", {}).get(axis, 3)))
                except (TypeError, ValueError):
                    values.append(3.0)
            row = [Paragraph(axis, styles["cell"])] + [
                Paragraph(f"{v:.1f}", styles["cell"]) for v in values
            ]
            if compare:
                diff = values[0] - values[1]
                row.append(Paragraph(f"{diff:+.1f}", styles["cell"]))
            score_rows.append(row)
        score_widths = [32 * mm] + [(170 * mm - 32 * mm) / (len(products) + (1 if compare else 0))] * (
            len(products) + (1 if compare else 0)
        )
        story.append(_table(score_rows, score_widths, styles))

    # ── 分析依据 ──
    if any(p.get("basis") for p in products):
        story.append(Paragraph("三、判断依据", styles["h2"]))
        for p in products:
            basis = p.get("basis") or {}
            if not basis:
                continue
            story.append(Paragraph(f"<b>{p.get('name', '-')}</b>", styles["body"]))
            for key, label in (
                ("protocol", "协议"),
                ("chip", "芯片"),
                ("barrier", "壁垒"),
                ("scores", "评分"),
            ):
                if basis.get(key):
                    story.append(Paragraph(f"· {label}：{basis[key]}", styles["body"]))
            story.append(Spacer(1, 5))

    # ── 结论 ──
    if payload.get("verdict"):
        story.append(Paragraph("四、选品结论", styles["h2"]))
        story.append(Paragraph(payload["verdict"], styles["body"]))

    # ── 引用来源 ──
    if sources:
        story.append(Paragraph("五、引用来源", styles["h2"]))
        for index, src in enumerate(sources, 1):
            story.append(
                Paragraph(
                    f"[{index}] {src.get('title', '')}　"
                    f"<font color='#8296AD'>{src.get('meta', '')}</font>",
                    styles["body"],
                )
            )
            story.append(Paragraph(src.get("snippet", ""), styles["body"]))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("五、引用来源", styles["h2"]))
        story.append(
            Paragraph(
                "本次分析未匹配到本地知识库条目，结论仅基于模型对产品名称的判断。"
                "如需可溯源结论，请在页面选择品类后重试。",
                styles["body"],
            )
        )

    story.append(Spacer(1, 14))
    story.append(
        KeepTogether(
            Paragraph(
                "声明：本报告由大模型基于产品名称与本地知识库生成，属于辅助判断，"
                "不构成对参数、认证与合规性的保证。采购与定价决策请以实物检测报告、"
                "供应商资质与平台规则为准。",
                styles["sub"],
            )
        )
    )

    doc.build(story)
    return path
