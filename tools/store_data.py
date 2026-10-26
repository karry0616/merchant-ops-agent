"""平台经营数据导入 — 解析生意参谋 / 京东商智导出的 CSV、XLSX，产出 KPI 看板

只做确定性的数字统计，不调用大模型；运营解读交给 analyst agent。
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import pandas as pd

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "store_data"
)

COLUMN_ALIASES = {
    "date": ["日期", "统计日期", "时间", "日期时间", "date", "day"],
    "product": ["商品", "商品名称", "宝贝", "宝贝名称", "商品标题", "标题", "product", "title", "sku"],
    "sales": ["销量", "件数", "销售件数", "支付件数", "销量件", "sales", "qty", "数量"],
    "gmv": ["销售额", "支付金额", "成交额", "成交金额", "销售额元", "gmv", "amount", "金额"],
    "visitors": ["访客", "访客数", "浏览量", "访客人数", "uv", "visitors"],
    "orders": ["订单", "订单数", "支付订单数", "子订单", "订单量", "orders"],
    "refunds": ["退款", "退款订单", "退款订单数", "退款金额", "退款单数", "refunds"],
}


def _norm(text: str) -> str:
    return re.sub(r"[\s()（）:：\-_/]", "", str(text)).lower()


def _match_columns(df: pd.DataFrame) -> dict[str, str]:
    """把用户表头映射到标准字段"""
    mapping: dict[str, str] = {}
    normalized = {_norm(c): c for c in df.columns}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if key in normalized and normalized[key] not in mapping.values():
                mapping[field] = normalized[key]
                break
    # 兜底：包含匹配
    for field, aliases in COLUMN_ALIASES.items():
        if field in mapping:
            continue
        for col in df.columns:
            if col in mapping.values():
                continue
            name = _norm(col)
            if any(_norm(a) in name or name in _norm(a) for a in aliases):
                mapping[field] = col
                break
    return mapping


def read_table(path: str) -> pd.DataFrame:
    """读取 CSV / XLSX，自动尝试常见编码"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return pd.read_excel(path, engine="openpyxl")
    if ext == ".xls":
        try:
            return pd.read_excel(path)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("旧版 .xls 需要另存为 .xlsx 后再上传") from exc

    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 编码无法识别，请另存为 UTF-8 后重试")


def _to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[,，¥￥元\s]", "", regex=True)
        .replace({"": "0", "nan": "0", "None": "0", "-": "0"})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def analyze(path: str) -> dict:
    """解析文件并计算 KPI、趋势与商品排行"""
    df = read_table(path)
    if df.empty:
        raise ValueError("文件里没有数据行")

    cols = _match_columns(df)
    if "gmv" not in cols and "sales" not in cols:
        raise ValueError(
            "至少需要一列销售额或销量。可识别的表头示例：日期、商品名称、销量、销售额、访客数、订单数、退款"
        )

    missing = [k for k in ("date", "product", "visitors", "orders", "refunds") if k not in cols]

    numeric_cols = [c for c in ("sales", "gmv", "visitors", "orders", "refunds") if c in cols]
    for field in numeric_cols:
        df[cols[field]] = _to_number(df[cols[field]])

    def total(field: str) -> float:
        return float(df[cols[field]].sum()) if field in cols else 0.0

    gmv = total("gmv")
    sales = total("sales")
    visitors = total("visitors")
    orders = total("orders")
    refunds = total("refunds")

    # 没有订单列时用销量近似，保证转化率等指标可算
    order_base = orders or sales
    aov = gmv / order_base if order_base else 0.0
    conversion = (order_base / visitors * 100) if visitors else 0.0
    refund_rate = (refunds / order_base * 100) if order_base and refunds else 0.0

    trend = []
    if "date" in cols:
        series = df.copy()
        series[cols["date"]] = pd.to_datetime(series[cols["date"]], errors="coerce")
        series = series.dropna(subset=[cols["date"]])
        if not series.empty:
            value_col = cols.get("gmv") or cols.get("sales")
            grouped = series.groupby(series[cols["date"]].dt.strftime("%m-%d"))[value_col].sum()
            trend = [(str(k), float(v)) for k, v in grouped.tail(14).items()]

    top = []
    if "product" in cols:
        value_col = cols.get("gmv") or cols.get("sales")
        grouped = df.groupby(cols["product"])[value_col].sum().sort_values(ascending=False).head(5)
        total_value = float(grouped.sum()) or 1.0
        top = [
            {"name": str(name), "value": float(value), "share": float(value) / total_value * 100}
            for name, value in grouped.items()
        ]

    return {
        "rows": int(len(df)),
        "columns": cols,
        "missing": missing,
        "metrics": {
            "gmv": gmv,
            "sales": sales,
            "orders": orders,
            "visitors": visitors,
            "aov": aov,
            "conversion": conversion,
            "refund_rate": refund_rate,
            "days": len(trend) or (1 if "date" not in cols else 0),
        },
        "trend": trend,
        "top": top,
    }


def _fmt_money(value: float) -> str:
    if value >= 10000:
        return f"¥{value / 10000:.2f} 万"
    return f"¥{value:,.0f}"


def _trend_svg(trend: list[tuple[str, float]], color: str = "#2563eb") -> str:
    if len(trend) < 2:
        return ""
    w, h = 640, 210
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 28
    values = [v for _, v in trend]
    vmax = max(values) or 1
    step = (w - pad_l - pad_r) / (len(trend) - 1)
    pts = []
    for i, value in enumerate(values):
        x = pad_l + i * step
        y = pad_t + (h - pad_t - pad_b) * (1 - value / vmax)
        pts.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad_l},{h - pad_b} {polyline} {pts[-1][0]:.1f},{h - pad_b}"
    labels = []
    for i, (label, _) in enumerate(trend):
        if i % max(1, len(trend) // 6) == 0 or i == len(trend) - 1:
            labels.append(
                f'<text x="{pts[i][0]:.1f}" y="{h - 8}" text-anchor="middle" '
                f'font-size="10.5" fill="#8296ad">{label}</text>'
            )
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{color}"/>' for x, y in pts)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="销售额趋势">'
        f'<polygon points="{area}" fill="{color}" fill-opacity="0.10"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>{dots}{"".join(labels)}</svg>'
    )


def render_html(result: dict, source_name: str = "") -> str:
    m, trend, top = result["metrics"], result["trend"], result["top"]
    cards = [
        ("销售额", _fmt_money(m["gmv"]), "文件内累计"),
        ("销量", f"{m['sales']:,.0f} 件", "件数口径"),
        ("订单数", f"{m['orders']:,.0f}", "缺失时按销量估算" if not m["orders"] else "支付订单"),
        ("客单价", f"¥{m['aov']:,.1f}", "销售额 / 订单"),
        ("转化率", f"{m['conversion']:.1f}%", "健康线 ≥3%"),
        ("退款率", f"{m['refund_rate']:.1f}%", "越低越好"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-k">{k}</div>'
        f'<div class="kpi-v">{v}</div><div class="kpi-d">{d}</div></div>'
        for k, v, d in cards
    )

    chart = _trend_svg(trend)
    trend_block = (
        f'<div class="viz-card"><div class="viz-title">销售额趋势'
        f'<small>最近 {len(trend)} 个数据点</small></div>{chart}</div>'
        if chart
        else '<div class="viz-card"><div class="viz-title">销售额趋势</div>'
        '<div class="empty-hint">文件中没有日期列，无法绘制趋势。加上「日期」列即可。</div></div>'
    )

    rows_html = ""
    for i, item in enumerate(top):
        value = item["value"]
        shown = _fmt_money(value) if m["gmv"] else f"{value:,.0f} 件"
        rows_html += (
            f"<tr><td>{i + 1}</td><td>{item['name'][:40]}</td>"
            f"<td>{shown}</td><td>{item['share']:.1f}%</td></tr>"
        )
    top_block = (
        f'<div class="viz-card"><div class="viz-title">商品表现 TOP{len(top)}</div>'
        f'<table class="cmp"><thead><tr><th>#</th><th>商品</th>'
        f'<th>{"销售额" if m["gmv"] else "销量"}</th><th>占比</th></tr></thead>'
        f"<tbody>{rows_html}</tbody></table></div>"
        if top
        else ""
    )

    note = ""
    if result["missing"]:
        cn = {"date": "日期", "product": "商品名称", "visitors": "访客数", "orders": "订单数", "refunds": "退款"}
        note = (
            '<div class="foot">缺少列：'
            + "、".join(cn.get(k, k) for k in result["missing"])
            + f'；已导入 {result["rows"]} 行，缺失指标按 0 处理。</div>'
        )

    return (
        f'<div class="viz-title">数据概览<small>{source_name}</small></div>'
        f'<div class="kpi-grid">{kpi_html}</div>'
        f'<div class="viz" style="margin-top:14px">{trend_block}{top_block}</div>{note}'
    )


def build_llm_payload(result: dict, extra_cost: float = 0, extra_price: float = 0) -> str:
    """把结构化结果压成一段中文文本，喂给 analyst agent"""
    m = result["metrics"]
    lines = [
        f"店铺平台数据（共 {result['rows']} 行）：",
        f"- 销售额 {m['gmv']:.2f} 元，销量 {m['sales']:.0f} 件，订单 {m['orders']:.0f} 单",
        f"- 访客 {m['visitors']:.0f}，转化率 {m['conversion']:.2f}%，客单价 {m['aov']:.2f} 元",
        f"- 退款 {m['refund_rate']:.2f}%",
    ]
    if result["top"]:
        items = "；".join(f"{t['name'][:20]} 占 {t['share']:.1f}%" for t in result["top"][:5])
        lines.append(f"- 商品集中度：{items}")
    if result["trend"]:
        first, last = result["trend"][0], result["trend"][-1]
        lines.append(f"- 趋势：{first[0]} 到 {last[0]}，由 {first[1]:.0f} 变为 {last[1]:.0f}")
    if extra_cost and extra_price:
        lines.append(f"- 单品成本 {extra_cost:.2f} 元，售价 {extra_price:.2f} 元")
    return "\n".join(lines)


def export_csv(path: str) -> str:
    """导出规范化后的数据，方便二次加工"""
    df = read_table(path)
    cols = _match_columns(df)
    keep = {v: k for k, v in cols.items()}
    out = df[list(keep)].rename(columns=keep)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    target = os.path.join(OUTPUT_DIR, f"规范化数据_{datetime.now():%Y%m%d_%H%M%S}.csv")
    out.to_csv(target, index=False, encoding="utf-8-sig")
    return target


def write_template() -> str:
    """下载用的空白数据模板"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    target = os.path.join(OUTPUT_DIR, "平台数据模板.csv")
    if not os.path.exists(target):
        pd.DataFrame(
            columns=["日期", "商品名称", "销量", "销售额", "访客数", "订单数", "退款订单"]
        ).to_csv(target, index=False, encoding="utf-8-sig")
    return target
