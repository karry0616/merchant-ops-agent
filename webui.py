"""商家智能 Agent — Gradio Web 界面（知识库管理 + 系统监控 + 用户登录）"""

import sys
import os
import re
import time
import logging
import uuid
import hashlib
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import csv
import io
import math
import gradio as gr
from llm import check_llm, check_ollama, list_models
from ui.theme import build_theme, load_css
from orchestrator import MerchantOrchestrator
from knowledge.data_manager import (
    get_all_faqs, add_faq, delete_faq,
    get_price_library, add_price_subcategory, delete_price_subcategory,
    get_suppliers, add_supplier, delete_supplier_product,
    get_all_templates, get_all_categories,
    get_all_conversation_records,
    add_conversation_record_entry,
    delete_conversation_record_entry,
)
from monitor import get_stats, get_recent_calls, get_daily_stats
from config import LOG_LEVEL, LOG_FORMAT, RATE_LIMIT_ENABLED, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, LLM_PROVIDER, WEB_PORT, ADMIN_USER, ADMIN_PASS
import html as html_lib
import tools.store_data as store_data
from tools.main_image import generate_main_image
from tools.report_pdf import build_tech_pdf

logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 延迟初始化：避免模块导入时就失败
_orch: MerchantOrchestrator | None = None

def _get_orch() -> MerchantOrchestrator:
    global _orch
    if _orch is None:
        _orch = MerchantOrchestrator()
    return _orch

_rate_limit_store: dict[str, list[float]] = {}

USERS_DB = os.path.join(os.path.dirname(__file__), "users.db")


def _hash_password(password: str, salt: str = None) -> str:
    """Salted SHA256: 返回 salt:hexdigest 格式"""
    if salt is None:
        salt = os.urandom(16).hex()
    return f"{salt}:{hashlib.sha256((salt + password).encode('utf-8')).hexdigest()}"


def _verify_password(password: str, stored: str) -> bool:
    """验证密码，兼容旧版无盐哈希"""
    if ":" not in stored:
        # 旧版无盐哈希 — 升级为加盐
        return stored == hashlib.sha256(password.encode("utf-8")).hexdigest()
    salt, pwd_hash = stored.split(":", 1)
    return pwd_hash == hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def _init_users():
    """Initialize users table — ONLY create default admin if no users exist"""
    import sqlite3
    conn = sqlite3.connect(USERS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_USER,)).fetchone()
        if existing is None:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                         (ADMIN_USER, _hash_password(ADMIN_PASS)))
            conn.commit()
            logger.info(f"Created default admin user '{ADMIN_USER}'")
    except sqlite3.Error as e:
        logger.warning(f"初始化用户表失败: {e}")
    conn.close()


def check_login(username: str, password: str) -> bool:
    """Gradio auth callback with salted password verification"""
    import sqlite3
    try:
        conn = sqlite3.connect(USERS_DB)
        row = conn.execute("SELECT password FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if row is None:
            return False
        return _verify_password(password, row[0])
    except Exception:
        return False

def _check_rate_limit(ip: str) -> bool:
    if not RATE_LIMIT_ENABLED:
        return True
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if t > cutoff]
    if len(_rate_limit_store[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[ip].append(now)
    return True

def _check_llm():
    provider = LLM_PROVIDER
    if provider == "deepseek":
        ok, msg = check_llm()
        if not ok:
            return False, f"❌ DeepSeek 不可用 — {msg}"
        return True, ""
    else:
        if not check_ollama():
            return False, "❌ Ollama 未运行！请先执行 ollama serve"
        return True, ""

def check_env():
    ok, msg = check_llm()
    models = list_models() if ok else []
    return ok, models, msg

def _get_session_id(request: gr.Request) -> str:
    """基于用户名+时间戳生成 session"""
    username = getattr(request, "username", "anonymous") or "anonymous"
    return f"{username}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"

def _web_chat_session(request: gr.Request) -> str:
    """同一浏览器标签页内保持同一 session，实现真实多轮对话"""
    key = getattr(request, "session_hash", None) or getattr(request, "username", "anonymous") or "anonymous"
    return f"webchat_{key}"

def agent_chat(message, history, request: gr.Request):
    ok, err = _check_llm()
    if not ok:
        yield err
        return
    if not message.strip():
        yield "请输入你的问题"
        return
    if not _check_rate_limit("webui_chat"):
        yield "⚠️ 请求过于频繁，请稍后再试"
        return

    session_id = _web_chat_session(request)

    try:
        logger.info(f"Chat session={session_id[:20]}: {message[:60]}")
        yield "🤔 正在分析你的问题..."
        response = _get_orch().smart_chat(message, session_id=session_id)
        yield response
    except Exception as e:
        logger.error(f"chat 异常: {e}", exc_info=True)
        yield f"❌ 处理出错: {e}"

def run_selector(product, category, budget, audience, request: gr.Request):
    yield "⏳ 正在调用模型并查询淘宝实时搜索词…（约 30-60 秒，请勿关闭页面）", None
    ok, err = _check_llm()
    if not ok:
        yield err, None
        return
    if not (product and str(product).strip()) and not (category and str(category).strip()):
        yield "请填写产品名称或选择品类方向", None
        return
    query = str(product).strip() if product and str(product).strip() else ""
    cat = str(category).strip() if category and str(category).strip() else ""
    if query and cat:
        query = f"{query}（品类：{cat}）"
    elif not query:
        query = cat
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"sel_{username}_{uuid.uuid4().hex[:6]}"
    try:
        result = _get_orch().run_agent("selector", query, session_id=session_id, budget=budget, target_audience=audience)
        report = result.get("report", "生成失败")
        recs = result.get("recommendations", [])
        rec_text = "📊 数据来源：淘宝搜索下拉词（真实用户搜索需求）\n\n"
        for r in recs:
            price = r.get("avg_price", 0)
            cost = r.get("cost", 0)
            margin = round((price - cost) / price * 100, 1) if price > 0 else 0
            rec_text += f"• {r.get('name', '')} — ¥{price} | 成本¥{cost} | 毛利率{margin}%\n"
        yield report, rec_text if rec_text else None
    except Exception as e:
        logger.error(f"selector 异常: {e}", exc_info=True)
        yield f"❌ 处理出错: {e}", None

def run_lister(name, category, features, price, cost, request: gr.Request):
    yield "⏳ 正在生成上架素材…（约 20-40 秒，请勿关闭页面）"
    if not name.strip():
        yield "请输入商品名称"
        return
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"list_{username}_{uuid.uuid4().hex[:6]}"
    try:
        info = {"name": name, "category": category, "features": features, "target_price": price, "cost": cost}
        result = _get_orch().run_agent("lister", info, session_id=session_id)
        content = result.get("listing_content", "生成失败")
        saved = result.get("saved_to", "")
        if saved:
            content += f"\n\n---\n📁 已保存到: `{saved}`"
        yield content
    except Exception as e:
        yield f"❌ 处理出错: {e}"

def run_sourcing(name, category, target_price, expected_sales, budget, request: gr.Request):
    yield "⏳ 正在分析一手货源…（约 20-40 秒，请勿关闭页面）"
    if not name.strip() and not category.strip():
        yield "请输入商品名称或品类"
        return
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"src_{username}_{uuid.uuid4().hex[:6]}"
    try:
        info = {"name": name, "category": category, "target_price": target_price, "expected_sales": expected_sales, "budget": budget}
        result = _get_orch().run_agent("sourcing", info, session_id=session_id)
        yield result.get("report", "生成失败")
    except Exception as e:
        yield f"❌ 处理出错: {e}"

def run_service(query, product_context, request: gr.Request):
    yield "⏳ 正在检索话术库并生成回复…（约 30-90 秒，请勿关闭页面）"
    if not query.strip():
        yield "请输入顾客问题"
        return
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"svc_{username}_{uuid.uuid4().hex[:6]}"
    try:
        result = _get_orch().run_agent("service", query, session_id=session_id, product_context=product_context)
        yield result.get("answer", "生成失败")
    except Exception as e:
        yield f"❌ 处理出错: {e}"

def run_analyst(data, cost, price, volume, request: gr.Request):
    yield "⏳ 正在分析经营数据…（约 20-40 秒，请勿关闭页面）", None
    if not data.strip():
        yield "请输入经营数据", None
        return
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"an_{username}_{uuid.uuid4().hex[:6]}"
    try:
        pricing_data = {}
        if cost: pricing_data["cost"] = cost
        if price: pricing_data["price"] = price
        if volume: pricing_data["volume"] = volume
        result = _get_orch().run_agent("analyst", data if not pricing_data else {**pricing_data, "data": data}, session_id=session_id)
        report = result.get("report", "生成失败")
        pricing = result.get("pricing_advice")
        pt = ""
        if pricing:
            pa = pricing.get("profit_analysis", {})
            pt = f"利润: ¥{pa.get('profit', 0)} | 利润率: {pa.get('margin', 0)}%"
            ps = pricing.get("price_suggestion", {})
            pt += f"\n建议售价: ¥{ps.get('competitive_price', 0)} (常规) / ¥{ps.get('premium_price', 0)} (溢价)"
        yield report, pt if pt else None
    except Exception as e:
        yield f"❌ 处理出错: {e}", None

def run_tech_analysis(product_name, request: gr.Request):
    """3C 产品技术分析"""
    ok, err = _check_llm()
    if not ok:
        return err, "", "", ""
    if not product_name.strip():
        return "请输入产品名称", "", "", ""
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"tech_{username}_{uuid.uuid4().hex[:6]}"
    try:
        result = _get_orch().run_agent("tech_analyst", product_name, session_id=session_id)
        protocol = result.get("protocol", "未识别")
        chip = result.get("chip", "未识别")
        barrier = result.get("barrier", "未识别")
        report = result.get("report", "")

        # 构建展示内容
        barrier_display = barrier
        if barrier == "高":
            barrier_display = "🔴 高"
        elif barrier == "中":
            barrier_display = "🟡 中"
        elif barrier == "低":
            barrier_display = "🟢 低"

        summary = f"""### 📊 技术分析结果

| 项目 | 结果 |
|------|------|
| **通信协议** | {protocol} |
| **芯片方案** | {chip} |
| **技术壁垒** | {barrier_display} |

---

**产品**: {product_name}
"""
        return summary, protocol, chip, barrier_display
    except Exception as e:
        logger.error(f"tech_analyst 异常: {e}", exc_info=True)
        return f"❌ 处理出错: {e}", "", "", ""


def run_workflow(category, budget, audience, request: gr.Request):
    ok, err = _check_llm()
    if not ok:
        yield err
        return
    if not category.strip():
        yield "请输入品类方向"
        return
    username = getattr(request, "username", "anonymous") or "anonymous"
    session_id = f"wf_{username}_{uuid.uuid4().hex[:8]}"

    step_names = {
        "selector": "选品分析",
        "lister": "上架素材",
        "service": "客服话术",
        "analyst": "运营分析",
    }
    step_order = list(step_names)
    renderers = {
        "selector": lambda r: f"## 📋 选品分析\n{r.get('report', 'N/A')}\n\n",
        "lister": lambda r: f"## 📝 上架素材\n{r.get('listing_content', r.get('report', 'N/A'))}\n\n",
        "service": lambda r: f"## 💬 客服应答\n{r.get('answer', r.get('report', 'N/A'))}\n\n",
        "analyst": lambda r: f"## 📊 运营建议\n{r.get('report', 'N/A')}\n\n",
    }

    output = f"# 🛒 完整工作流报告：{category}\n\n⏳ **步骤 1/4：选品分析中...**\n"
    yield output
    try:
        for step, payload in _get_orch().iter_workflow(
            category, budget=budget, target_audience=audience, session_id=session_id
        ):
            if step == "summary":
                break
            if payload.get("error"):
                output += f"## ❌ {step_names[step]}失败\n{payload['error']}\n\n"
            else:
                output += renderers[step](payload)
            idx = step_order.index(step)
            hint = ""
            if idx < len(step_order) - 1:
                nxt = step_order[idx + 1]
                hint = f"⏳ **步骤 {idx + 2}/4：{step_names[nxt]}中...**\n"
            yield output + hint
        output += "---\n✅ **全部完成！**"
        yield output
    except Exception as e:
        logger.error(f"工作流异常: {e}", exc_info=True)
        yield f"❌ 工作流出错: {e}"

def parse_csv(file):
    if file is None:
        return None, "请上传 CSV 文件"
    try:
        with open(file, "r", encoding="utf-8-sig") as f:
            content = f.read()
        reader = csv.DictReader(io.StringIO(content))
        products = []
        for row in reader:
            # 兼容 Excel 导出：BOM / 表头空格 / 多余列
            row = {
                (k or "").strip().lstrip("\ufeff"): (v.strip() if isinstance(v, str) else (v or ""))
                for k, v in row.items()
                if k is not None
            }
            name = row.get("名称", "") or row.get("name", "") or ""
            cat = row.get("品类", "") or row.get("category", "") or ""
            feat = row.get("卖点", "") or row.get("features", "") or ""
            price = row.get("售价", "") or row.get("price", "") or ""
            cost = row.get("成本", "") or row.get("cost", "") or ""
            if name:
                products.append({"name": name, "category": cat, "features": feat, "target_price": price, "cost": cost})
        if not products:
            return None, "CSV 未找到有效数据。需要列：名称,品类,卖点,售价,成本"
        return products, f"成功解析 {len(products)} 个商品"
    except Exception as e:
        return None, f"解析失败: {e}"

def run_batch_listing(file):
    ok, err = _check_llm()
    if not ok:
        yield f"❌ {err}", None
        return
    products, msg = parse_csv(file)
    if not products:
        yield msg, None
        return

    output = ""
    all_results = []
    total = len(products)
    yield f"📦 共解析 {total} 个商品\n\n", None

    for i, product in enumerate(products, 1):
        name = product.get("name", f"商品{i}")
        yield f"⏳ ({i}/{total}) {name} 生成中...\n", all_results
        try:
            result = _get_orch().run_agent("lister", product)
            item = {"index": i, "name": name, "content": result.get("listing_content", "生成失败")}
            all_results.append(item)
            output += f"---\n### ✅ {i}. {name}\n{item['content']}\n\n"
            yield output, all_results
        except Exception as e:
            all_results.append({"index": i, "name": name, "content": f"❌ 失败: {e}"})
            output += f"---\n### ❌ {i}. {name}\n失败: {e}\n\n"
            yield output, all_results

    output += "---\n✅ 全部完成"
    yield output, all_results

def export_batch_csv(results):
    if not results:
        return None
    import tempfile
    out = io.StringIO()
    out.write("商品名称,标题方案1,标题方案2,标题方案3,核心卖点\n")
    for r in results:
        name = r.get("name", "")
        lines = r.get("content", "").split("\n")
        titles = [l for l in lines if re.match(r'^方案\d+[：:]', l.strip())]
        t1 = titles[0].split("：")[-1].strip() if len(titles) > 0 else ""
        t2 = titles[1].split("：")[-1].strip() if len(titles) > 1 else ""
        t3 = titles[2].split("：")[-1].strip() if len(titles) > 2 else ""
        out.write(f"{name},{t1},{t2},{t3},\n")
    # 用 delete=True，Gradio 会在下载完成后自动读取
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".csv", delete=False)
    tmp.write(out.getvalue())
    tmp.close()
    return tmp.name

def refresh_faq_list():
    faqs = get_all_faqs()
    if not faqs:
        return "（暂无 FAQ，点击「新增 FAQ」添加）"
    lines = []
    for i, faq in enumerate(faqs):
        lines.append(f"**{i+1}. {faq['q']}**")
        lines.append(f"   {faq['a'][:120]}{'...' if len(faq['a']) > 120 else ''}")
        lines.append("")
    return "\n".join(lines)

def add_faq_entry(q, a):
    if not q.strip() or not a.strip():
        return "请输入问题和答案", refresh_faq_list()
    add_faq(q.strip(), a.strip())
    return "✅ 已添加", refresh_faq_list()

def delete_faq_entry(index_str):
    try:
        idx = int(index_str) - 1
        if delete_faq(idx):
            return f"✅ 已删除第 {index_str} 条", refresh_faq_list()
        return "❌ 无效编号", refresh_faq_list()
    except (ValueError, IndexError):
        return "❌ 请输入有效编号", refresh_faq_list()

def refresh_price_view():
    lib = get_price_library()
    if not lib:
        return "（暂无价格数据）"
    lines = []
    for cat in lib:
        lines.append(f"### {cat['category']}")
        for i, sub in enumerate(cat.get("subcategories", [])):
            lines.append(f"- {sub['name']}: ¥{sub['price_range']} | 成本¥{sub['cost_range']} | 竞争{sub.get('competition','?')}")
        lines.append("")
    return "\n".join(lines)

def add_price_item(category, name, price_range, cost_range, competition):
    if not category.strip() or not name.strip():
        return "请输入品类和子类名称", refresh_price_view()
    data = {"name": name.strip(), "price_range": price_range or "?", "cost_range": cost_range or "?", "target": "通用", "features": [], "competition": competition or "中"}
    ok = add_price_subcategory(category.strip(), data)
    return ("✅ 已添加" if ok else "❌ 品类不存在，请先确认品类名称"), refresh_price_view()

def refresh_supplier_view():
    suppliers = get_suppliers()
    if not suppliers:
        return "（暂无供应商数据）"
    lines = []
    for sup in suppliers:
        lines.append(f"### {sup['category']}")
        lines.append(f"产区: {', '.join(sup.get('sourcing_region', []))}")
        for i, p in enumerate(sup.get("products", [])):
            lines.append(f"  {i+1}. {p['name']} | 批发¥{p['wholesale_price']} | MOQ{p.get('moq','?')}")
        lines.append("")
    return "\n".join(lines)

def add_supplier_item(category, name, wholesale_price, moq, region):
    if not category.strip() or not name.strip():
        return "请输入品类和产品名称", refresh_supplier_view()
    data = {"name": name.strip(), "wholesale_price": wholesale_price or "?", "moq": moq or "?", "moq_price": "?", "supplier_types": [region or "未知"], "sourcing_notes": ""}
    ok = add_supplier(category.strip(), data)
    return ("✅ 已添加" if ok else "❌ 添加失败"), refresh_supplier_view()

def refresh_template_view():
    templates = get_all_templates()
    if not templates:
        return "（暂无模板）"
    lines = []
    for t in templates:
        lines.append(f"### {t['category']}")
        for tp in t.get("title_patterns", [])[:2]:
            lines.append(f"- 标题: {tp}")
        lines.append(f"- SEO: {', '.join(t.get('seo_keywords', [])[:3])}")
        lines.append("")
    return "\n".join(lines)


def refresh_conversation_view(stage: str = "", query: str = ""):
    from knowledge.conversation_records import get_records, STAGES
    try:
        records = get_records(stage=stage, keyword=query, limit=200)
    except Exception:
        records = get_all_conversation_records()
    if not records:
        return "（暂无对话记录，新增记录后系统会自动检索相似对话辅助客服回复）"
    lines = [f"共 {len(records)} 条记录：\n"]
    for r in records:
        stage_label = STAGES.get(r.get("stage", ""), r.get("stage", ""))
        tags = ", ".join(r.get("tags", [])) if r.get("tags") else ""
        outcome = f" → {r['outcome']}" if r.get("outcome") else ""
        product_info = f" [{r['product']}]" if r.get("product") else ""

        lines.append(f"**ID:{r['id']}** | {stage_label}{product_info}{outcome}")
        lines.append(f"- 顾客：{r['customer_question'][:200]}")
        lines.append(f"- 回复：{r['merchant_response'][:300]}")
        if tags:
            lines.append(f"- 标签：{tags}")
        lines.append("")
    return "\n".join(lines)


def add_conversation_entry(stage, question, response, product, category, tags, outcome):
    if not question.strip() or not response.strip():
        return "⚠️ 顾客问题和商家回复不能为空", refresh_conversation_view()
    ok = add_conversation_record_entry(stage, question, response, product, category, tags, outcome)
    if ok:
        return "✅ 已添加", refresh_conversation_view()
    return "❌ 添加失败", refresh_conversation_view()


def delete_conversation_entry(record_id):
    if not record_id or record_id < 1:
        return "⚠️ 请输入有效的记录 ID", refresh_conversation_view()
    if delete_conversation_record_entry(int(record_id)):
        return f"✅ 已删除 ID {int(record_id)}", refresh_conversation_view()
    return f"❌ 未找到 ID {int(record_id)}", refresh_conversation_view()


# ═════════════════════════════════════════════════
#  系统监控
# ═════════════════════════════════════════════════

def refresh_system_status():
    try:
        stats = get_stats(24)
        daily = get_daily_stats(7)
        recent = get_recent_calls(10)
    except Exception:
        return "（监控数据库尚未就绪，使用后自动生成数据）", ""

    lines = [
        f"### 概览（最近 24 小时）",
        f"- 总调用次数: {stats['calls']}",
        f"- 成功: {stats['success']} | 失败: {stats['failed']}",
        f"- 总费用: ¥{stats['total_cost']}",
        f"- 平均响应: {stats['avg_duration_ms']}ms",
        f"",
        f"### 按 Provider",
    ]
    for prov, data in stats["by_provider"].items():
        lines.append(f"- {prov}: {data['calls']} 次, ¥{data['cost']}")
    lines.append("")
    lines.append(f"### 每日趋势")
    for d in daily:
        lines.append(f"- {d['day']}: {d['calls']} 次, ¥{d['cost']}, {d['avg_duration_ms']}ms")

    recent_lines = ["### 最近调用"]
    for r in recent[-10:]:
        status = "✅" if r.get("success") else "❌"
        recent_lines.append(f"- {status} {r.get('provider','?')}/{r.get('model','?')} {r.get('duration_ms',0)}ms | {r.get('agent','')}")
    return "\n".join(lines), "\n".join(recent_lines)

# ═══════════════════════════════════════════════════
# 3C 技术尽调（真实 LLM 分析 + 知识库溯源）
# ═══════════════════════════════════════════════════
_RADAR_AXES = ["协议先进性", "芯片方案", "技术门槛", "生态兼容", "量产成熟度"]


def _radar_point(cx, cy, r, ang):
    ang = math.radians(ang - 90)
    return cx + r * math.cos(ang), cy + r * math.sin(ang)


def _radar_svg(series):
    """离线 SVG 雷达图，series: [(名称, 颜色, 5 个分数)]"""
    w, h = 440, 340
    cx, cy, r = 210, 170, 115
    n = len(_RADAR_AXES)
    grids, axes, labels, shapes = [], [], [], []
    for lvl in range(1, 6):
        rr = r * lvl / 5
        opacity = 0.16 if lvl < 5 else 0.28
        pts = " ".join(
            f"{_radar_point(cx, cy, rr, i * 360 / n)[0]:.1f},{_radar_point(cx, cy, rr, i * 360 / n)[1]:.1f}"
            for i in range(n)
        )
        grids.append(f'<polygon points="{pts}" fill="none" stroke="rgba(37, 99, 235, {opacity})" stroke-width="1"/>')
    for i, label in enumerate(_RADAR_AXES):
        ang = i * 360 / n
        x, y = _radar_point(cx, cy, r, ang)
        axes.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="rgba(15, 23, 42, 0.10)" stroke-width="1"/>')
        lx, ly = _radar_point(cx, cy, r + 32, ang)
        anchor = "start" if lx > cx + 7 else ("end" if lx < cx - 7 else "middle")
        dy = -2 if ly < cy - 40 else (10 if ly > cy + 40 else 4)
        labels.append(
            f'<text x="{lx:.1f}" y="{ly + dy:.1f}" text-anchor="{anchor}" '
            f'font-size="11.5" fill="#475569">{label}</text>'
        )
    for _name, color, scores in series:
        pts, dots = [], []
        for i, v in enumerate(scores):
            x, y = _radar_point(cx, cy, r * max(v, 0.15) / 5.0, i * 360 / n)
            pts.append(f"{x:.1f},{y:.1f}")
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
        shapes.append(
            f'<polygon points="{" ".join(pts)}" fill="{color}" fill-opacity="0.16" '
            f'stroke="{color}" stroke-width="2" stroke-linejoin="round"/>{"".join(dots)}'
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" aria-label="技术壁垒雷达图">'
        f'{"".join(grids)}{"".join(axes)}{"".join(shapes)}{"".join(labels)}</svg>'
    )


def _3c_barrier_badge(barrier) -> str:
    level = {"高": "lv-high", "中": "lv-mid", "低": "lv-low"}.get(str(barrier).strip(), "lv-mid")
    return f'<span class="lv {level}">{html_lib.escape(str(barrier or "未识别"))}</span>'


def _3c_scores(product: dict) -> list[float]:
    raw = product.get("scores") or {}
    values = []
    for axis in _RADAR_AXES:
        try:
            value = float(raw.get(axis, 3))
        except (TypeError, ValueError):
            value = 3.0
        values.append(max(0.5, min(5.0, value)))
    return values


def _3c_cards(product: dict, green: bool = False, tag: str = "") -> str:
    basis = product.get("basis") or {}
    cards = [
        ("通信协议", html_lib.escape(str(product.get("protocol") or "未识别")),
         html_lib.escape(str(basis.get("protocol", "")))),
        ("芯片方案", html_lib.escape(str(product.get("chip") or "未识别")),
         html_lib.escape(str(basis.get("chip", "")))),
        ("技术壁垒", _3c_barrier_badge(product.get("barrier")),
         html_lib.escape(str(basis.get("barrier", "")))),
    ]
    cards_html = "".join(
        f'<div class="tcard{" green" if green else ""}"><div class="k">{k}</div>'
        f'<div class="v">{v}</div><div class="d">{d or "—"}</div></div>'
        for k, v, d in cards
    )
    name = html_lib.escape(str(product.get("name") or "-"))
    label = tag or product.get("tag") or ("产品 B" if green else "产品 A")
    return (
        f'<div><div class="product-head">'
        f'<div class="product-name{" green" if green else ""}"><i></i>{name}</div>'
        f'<span class="product-tag">{label}</span></div>'
        f'<div class="tcards">{cards_html}</div></div>'
    )


def _3c_sources(product_name: str, category: str) -> list[dict]:
    """从本地知识库取可溯源条目"""
    try:
        from knowledge.rag import get_rag
        rag = get_rag()
    except Exception:
        return []

    out: list[dict] = []
    if category:
        for kind, getter in (
            ("价格库", rag.search_price_library),
            ("供应商库", rag.search_supplier),
            ("上架模板", rag.search_template),
        ):
            try:
                item = getter(category)
            except Exception:
                item = None
            if not item:
                continue
            if kind == "价格库":
                subs = item.get("subcategories", [])[:2]
                snippet = "；".join(
                    f"{s.get('name', '')} ¥{s.get('price_range', '')}" for s in subs
                )
            elif kind == "供应商库":
                prods = item.get("products", [])[:2]
                snippet = "；".join(
                    f"{p.get('name', '')} 批发¥{p.get('wholesale_price', '')}" for p in prods
                ) or ("产区：" + "、".join(item.get("sourcing_region", [])[:3]))
            else:
                snippet = "；".join(str(t) for t in item.get("title_patterns", [])[:1])
            out.append({
                "title": f"{kind} · {html_lib.escape(str(item.get('category', category)))}",
                "meta": "本地知识库",
                "snippet": html_lib.escape(str(snippet)[:160]),
            })

    try:
        for faq in rag.search_faq(product_name, k=2):
            out.append({
                "title": f"FAQ · {html_lib.escape(str(faq.get('q', ''))[:28])}",
                "meta": "本地知识库 · 问答",
                "snippet": html_lib.escape(str(faq.get("a", ""))[:160]),
            })
    except Exception:
        pass
    return out[:4]


def _3c_verdict(products: list[dict]) -> str:
    """用评分生成一句可执行的结论，避免空话"""
    if not products:
        return ""
    scores = [_3c_scores(p) for p in products]
    avgs = [sum(s) / len(s) for s in scores]

    if len(products) == 1:
        p, one, avg = products[0], scores[0], avgs[0]
        weak = _RADAR_AXES[one.index(min(one))]
        strong = _RADAR_AXES[one.index(max(one))]
        barrier = str(p.get("barrier") or "未识别")
        if barrier == "高":
            tail = "壁垒高，适合做差异化主推，但要先确认供应链与认证成本。"
        elif barrier == "中":
            tail = "壁垒中等，建议靠外观、套装或服务做差异，纯价格战空间有限。"
        else:
            tail = "壁垒偏低，同质化严重，只能拼成本与流量效率。"
        return f"综合 {avg:.1f}/5，擅长「{strong}」，短板在「{weak}」。技术壁垒为 {barrier} —— {tail}"

    a, b = products[0], products[1]
    if abs(avgs[0] - avgs[1]) < 0.3:
        return (
            f"两者综合分接近（{avgs[0]:.1f} vs {avgs[1]:.1f}），技术层面难分胜负。"
            "建议按价格带与渠道错位铺货，先小批量测试转化再放大。"
        )
    winner = a if avgs[0] > avgs[1] else b
    loser = b if avgs[0] > avgs[1] else a
    return (
        f"{winner.get('name', '')} 综合领先 {abs(avgs[0] - avgs[1]):.1f} 分，建议作为主推款；"
        f"{loser.get('name', '')} 可作为价格带补充，用于承接比价流量。"
    )


def _3c_report_html(payload: dict) -> str:
    products = payload.get("products", [])
    compare = payload.get("mode") == "compare" and len(products) > 1
    colors = ["#2563eb", "#0f9d58"]
    scores = [_3c_scores(p) for p in products]
    avgs = [sum(s) / len(s) for s in scores]
    radar = _radar_svg(
        [(p.get("name", "-"), colors[i % 2], scores[i]) for i, p in enumerate(products)]
    )

    if compare:
        cards_html = (
            f'<div class="duel">{_3c_cards(products[0])}{_3c_cards(products[1], green=True)}</div>'
        )
    else:
        cards_html = f'<div class="solo">{_3c_cards(products[0], tag="产品")}</div>'

    rows = []
    for i, axis in enumerate(_RADAR_AXES):
        values = [s[i] for s in scores]
        best = max(values)
        cells = []
        for v in values:
            win = ' class="win"' if compare and v == best and values.count(best) == 1 else ""
            cells.append(f"<td{win}>{v:.1f}</td>")
        if compare:
            diff = values[0] - values[1]
            conclusion = "基本相当" if abs(diff) < 0.3 else f"{'A' if diff > 0 else 'B'} 领先 {abs(diff):.1f}"
        else:
            conclusion = "—"
        rows.append(
            f"<tr><td>{axis}</td>{''.join(cells)}"
            + (f"<td>{conclusion}</td>" if compare else "")
            + "</tr>"
        )

    head_names = "".join(
        f"<th>{html_lib.escape(str(p.get('name', '-')))[:16]}</th>" for p in products
    )
    table = (
        '<table class="cmp"><thead><tr><th>维度</th>' + head_names
        + ("<th>结论</th>" if compare else "") + "</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )
    legend = "".join(
        f'<span><i style="background:{colors[i % 2]}"></i>'
        f'{html_lib.escape(str(p.get("name", "-")))[:16]}</span>'
        for i, p in enumerate(products)
    )

    sources = payload.get("sources") or []
    if sources:
        sources_html = '<div class="sources">' + "".join(
            f'<div class="src"><div class="src-title">{s["title"]}</div>'
            f'<div class="src-meta">{s["meta"]}</div>'
            f'<div class="src-snippet">{s["snippet"]}</div></div>'
            for s in sources
        ) + "</div>"
    else:
        sources_html = (
            '<div class="empty-hint">未匹配到本地知识库条目，结论仅基于模型对产品名称的判断。'
            "选择品类后可获得价格库、供应商库、模板等溯源引用。</div>"
        )

    score_line = " · ".join(
        f"{html_lib.escape(str(p.get('name', '-')))[:18]} {a:.1f}/5"
        for p, a in zip(products, avgs)
    )

    return f"""
    <div class="sec-head"><span class="sec-no">01</span><h2>产品技术概览</h2><span>模型分析结果 · 需实物验证</span></div>
    {cards_html}
    <div class="sec-head" style="margin-top:20px"><span class="sec-no">02</span><h2>五维评分与对比</h2></div>
    <div class="viz">
      <div class="viz-card"><div class="viz-title">技术评分雷达图</div>{radar}
        <div class="legend">{legend}</div>
      </div>
      <div class="viz-card"><div class="viz-title">逐维度对比</div>{table}</div>
    </div>
    <div class="verdict"><b>综合评分：</b>{score_line}<br>{payload.get('verdict', '')}</div>
    <div class="sec-head" style="margin-top:20px"><span class="sec-no">03</span><h2>引用来源</h2></div>
    {sources_html}
    """


def run_3c(a_name, b_name, mode, category, request: gr.Request):
    """真实 3C 技术尽调：调 tech_analyst 分析 + 查本地知识库溯源"""
    yield '<div class="empty-hint">正在调用模型分析，通常需要 20-60 秒，请勿关闭页面。</div>', None

    ok, err = _check_llm()
    if not ok:
        yield f'<div class="empty-hint">{html_lib.escape(err)}</div>', None
        return

    a_name = (a_name or "").strip()
    b_name = (b_name or "").strip()
    if not a_name:
        yield '<div class="empty-hint">请先填写产品 A 的名称。</div>', None
        return

    names = [a_name]
    if mode == "compare" and b_name:
        names.append(b_name)

    username = getattr(request, "username", "anonymous") or "anonymous"
    products = []
    try:
        for name in names:
            result = _get_orch().run_agent(
                "tech_analyst", name, session_id=f"tech_{username}_{uuid.uuid4().hex[:6]}"
            )
            if result.get("error"):
                yield f'<div class="empty-hint">{html_lib.escape(str(result["error"]))}</div>', None
                return
            result["name"] = name
            result["tag"] = "产品"
            products.append(result)
    except Exception as e:
        logger.error(f"3C 分析异常: {e}", exc_info=True)
        yield f'<div class="empty-hint">分析失败：{html_lib.escape(str(e))}</div>', None
        return

    avgs = [sum(_3c_scores(p)) / len(_RADAR_AXES) for p in products]
    payload = {
        "mode": "compare" if len(products) > 1 else "single",
        "products": products,
        "sources": _3c_sources(a_name, (category or "").strip()),
        "axes": _RADAR_AXES,
        "avgs": avgs,
        "verdict": _3c_verdict(products),
    }
    yield _3c_report_html(payload), payload


def export_3c_pdf(payload):
    """把当前分析结果导出 PDF"""
    if not payload:
        return None
    try:
        return build_tech_pdf(payload)
    except Exception as e:
        logger.error(f"PDF 导出失败: {e}", exc_info=True)
        return None


# ═══════════════════════════════════════════════════
# 商品主图 / 平台数据导入
# ═══════════════════════════════════════════════════

def run_main_image(name, features, price, template):
    """按表单内容合成商品主图"""
    if not (name or "").strip():
        return None, None, "请先填写商品名称"
    try:
        path = generate_main_image(name, features, price, template or "clean")
    except Exception as e:
        logger.error(f"主图生成失败: {e}", exc_info=True)
        return None, None, f"生成失败：{e}"
    return path, path, f"已生成 800×800 主图：{os.path.basename(path)}"


def _uploaded_path(file_obj) -> str:
    if not file_obj:
        return ""
    if isinstance(file_obj, str):
        return file_obj
    return getattr(file_obj, "name", "") or ""


def run_platform_import(file_obj, cost, price):
    """导入平台数据 → KPI 看板 + 预填经营数据"""
    path = _uploaded_path(file_obj)
    if not path:
        return (
            '<div class="empty-hint">请先上传 CSV 或 XLSX 文件。</div>',
            "",
            None,
            "未选择文件",
        )
    try:
        result = store_data.analyze(path)
        html_out = store_data.render_html(result, os.path.basename(path))
        payload = store_data.build_llm_payload(result, float(cost or 0), float(price or 0))
        export_path = store_data.export_csv(path)
    except Exception as e:
        logger.error(f"平台数据导入失败: {e}", exc_info=True)
        return (
            f'<div class="empty-hint">导入失败：{html_lib.escape(str(e))}</div>',
            "",
            None,
            "导入失败",
        )
    return html_out, payload, export_path, f"已导入 {result['rows']} 行数据，可继续生成运营建议。"


def _page_head(title: str, desc: str) -> str:
    """页面标题区：统一说明这个页面解决什么问题"""
    return (
        f'<div class="page-head"><h2>{title}</h2><p>{desc}</p></div>'
    )


def _result_head(title: str, badge: str = "") -> str:
    """结果区标题：可选角标，用来标记示例数据"""
    tag = f'<span class="badge-example">{badge}</span>' if badge else ""
    return f'<div class="result-head"><span>{title}</span>{tag}</div>'


def build_app():
    price_categories = [c.get("category", "") for c in get_price_library() if c.get("category")]

    with gr.Blocks(title="商家智能运营 Agent", theme=build_theme(), css=load_css()) as app:
        gr.HTML("""
        <div class="app-head">
          <div>
            <div class="app-kicker">MERCHANT WORKBENCH</div>
            <h1>商家智能运营工作台</h1>
            <p>选品 → 内容 → 客服 → 复盘，按一条主线完成日常经营</p>
          </div>
          <div class="app-meta">当前身份：管理员</div>
        </div>
        """, elem_classes=["html-block"])

        with gr.Tabs():

            with gr.TabItem("工作台"):
                with gr.Tabs():
                    with gr.TabItem("智能对话"):
                        gr.HTML(_page_head("智能对话", "不确定用哪个功能时，直接把问题发进来，系统自动分派给对应 Agent。"), elem_classes=["html-block"])
                        gr.ChatInterface(
                            agent_chat,
                            title=None,
                            description="例如：帮我分析 65W 氮化镓充电器的市场机会",
                        )
                    with gr.TabItem("一键工作流"):
                        gr.HTML(_page_head("一键工作流", "给定品类后，自动串联选品、上架、客服与复盘，输出完整方案。"), elem_classes=["html-block"])
                        with gr.Row(elem_classes=["form-grid"]):
                            wf_category = gr.Textbox(label="品类方向 *", placeholder="如: 宠物用品", scale=2)
                            wf_budget = gr.Textbox(label="预算（可选）", placeholder="如: 5000", scale=1)
                            wf_audience = gr.Textbox(label="目标人群（可选）", placeholder="如: 养猫人群", scale=1)
                        with gr.Row(elem_classes=["action-row"]):
                            btn_workflow = gr.Button("开始执行", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("工作流报告"), elem_classes=["html-block"])
                            wf_out = gr.Markdown("*填写品类后点击「开始执行」，结果会显示在这里。*")
                        btn_workflow.click(run_workflow, [wf_category, wf_budget, wf_audience], wf_out)

            with gr.TabItem("经营"):
                with gr.Tabs():
                    with gr.TabItem("选品分析"):
                        gr.HTML(_page_head("选品分析", "输入产品名或只选品类，得到候选商品、价格带与竞争度结论。"), elem_classes=["html-block"])
                        with gr.Row(elem_classes=["form-grid"]):
                            product_in = gr.Textbox(
                                label="产品名称",
                                placeholder="如: 氮化镓充电器（可留空，仅按品类分析）",
                                scale=2,
                            )
                            category_in = gr.Dropdown(
                                label="品类方向 *",
                                choices=price_categories,
                                value="数码配件" if "数码配件" in price_categories else None,
                                allow_custom_value=True,
                                scale=2,
                            )
                        with gr.Row(elem_classes=["form-grid"]):
                            budget_in = gr.Textbox(label="启动预算（可选）", placeholder="如: 10000")
                            audience_in = gr.Textbox(label="目标人群（可选）", placeholder="如: 大学生")
                        with gr.Row(elem_classes=["action-row"]):
                            btn_selector = gr.Button("开始分析", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("选品结论"), elem_classes=["html-block"])
                            selector_out = gr.Markdown("*填写上方条件后点击「开始分析」。*")
                            recs_out = gr.Markdown()
                        btn_selector.click(run_selector, [product_in, category_in, budget_in, audience_in], [selector_out, recs_out])

                    with gr.TabItem("一手货源"):
                        gr.HTML(_page_head("一手货源", "根据目标售价与采购预算，给出产地、批发价与起订量建议。"), elem_classes=["html-block"])
                        with gr.Row(elem_classes=["form-grid"]):
                            src_name = gr.Textbox(label="商品名称 *", placeholder="如: 迷你手持小风扇")
                            src_cat = gr.Textbox(label="所属品类", placeholder="如: 电风扇")
                        with gr.Row(elem_classes=["form-grid"]):
                            src_price = gr.Textbox(label="目标售价（可选）", placeholder="如: 39")
                            src_sales = gr.Textbox(label="预期月销量（可选）", placeholder="如: 500")
                            src_budget = gr.Textbox(label="采购预算（可选）", placeholder="如: 5000")
                        with gr.Row(elem_classes=["action-row"]):
                            btn_sourcing = gr.Button("分析货源", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("货源报告"), elem_classes=["html-block"])
                            sourcing_out = gr.Markdown("*填写商品信息后点击「分析货源」。*")
                        btn_sourcing.click(run_sourcing, [src_name, src_cat, src_price, src_sales, src_budget], sourcing_out)

                    with gr.TabItem("上架素材"):
                        gr.HTML(_page_head("上架素材", "生成可直接粘贴的标题与详情文案，并可一键合成 800×800 商品主图。"), elem_classes=["html-block"])
                        with gr.Row(elem_classes=["form-grid"]):
                            name_in = gr.Textbox(label="商品名称 *", placeholder="如: 智能保温杯", scale=2)
                            cat_in = gr.Textbox(label="所属品类", placeholder="如: 家居日用", scale=1)
                        with gr.Row(elem_classes=["form-grid"]):
                            feat_in = gr.Textbox(label="核心卖点（逗号分隔）", placeholder="如: 24小时保温,316不锈钢", scale=2)
                            price_in = gr.Textbox(label="目标售价", placeholder="如: 89", scale=1)
                            cost_in = gr.Textbox(label="成本价", placeholder="如: 35", scale=1)
                            img_tpl = gr.Dropdown(
                                label="主图模板",
                                choices=[("白底简约", "clean"), ("红橙促销", "promo"), ("浅绿清新", "fresh")],
                                value="clean",
                                scale=1,
                            )
                        with gr.Row(elem_classes=["action-row"]):
                            btn_lister = gr.Button("生成文案素材", variant="primary", scale=2)
                            btn_image = gr.Button("生成商品主图", scale=1)
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("文案素材"), elem_classes=["html-block"])
                            lister_out = gr.Markdown("*填写商品信息后点击「生成文案素材」。*")
                            gr.HTML(_result_head("商品主图"), elem_classes=["html-block"])
                            img_preview = gr.Image(label="主图预览", type="filepath", interactive=False, height=420)
                            img_status = gr.Markdown("*点击「生成商品主图」后在这里预览与下载。*")
                            img_file = gr.File(label="下载主图 PNG")
                        btn_lister.click(run_lister, [name_in, cat_in, feat_in, price_in, cost_in], lister_out)
                        btn_image.click(run_main_image, [name_in, feat_in, price_in, img_tpl],
                                        [img_preview, img_file, img_status])

                    with gr.TabItem("批量上架"):
                        gr.HTML(_page_head("批量上架", "上传 CSV 批量生成上架素材，完成后下载结果文件。"), elem_classes=["html-block"])
                        with gr.Group(elem_classes=["panel"]):
                            file_input = gr.File(label="上传 CSV（必填）", file_types=[".csv"])
                        with gr.Row(elem_classes=["action-row"]):
                            btn_batch = gr.Button("批量生成", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("处理结果"), elem_classes=["html-block"])
                            batch_out = gr.Markdown("*上传 CSV 后点击「批量生成」。*")
                            download_file = gr.File(label="下载结果 CSV")
                        state = gr.State()
                        btn_batch.click(run_batch_listing, file_input, [batch_out, state])
                        state.change(export_batch_csv, state, download_file)

                    with gr.TabItem("客服应答"):
                        gr.HTML(_page_head("客服应答", "输入顾客原话，生成可直接发送的回复。"), elem_classes=["html-block"])
                        with gr.Row(elem_classes=["form-grid"]):
                            query_in = gr.Textbox(label="顾客问题 *", placeholder="如: 什么时候发货？", lines=3, scale=2)
                            ctx_in = gr.Textbox(label="商品信息（可选）", placeholder="填写商品名称/规格/价格", lines=3, scale=1)
                        with gr.Row(elem_classes=["action-row"]):
                            btn_service = gr.Button("生成回复", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("推荐回复"), elem_classes=["html-block"])
                            service_out = gr.Markdown("*输入顾客问题后点击「生成回复」。*")
                        btn_service.click(run_service, [query_in, ctx_in], service_out)

            with gr.TabItem("数据"):
                with gr.Tabs():
                    with gr.TabItem("运营分析"):
                        gr.HTML(_page_head("运营分析", "导入平台导出的数据即可看到 KPI、趋势与商品排行，再让模型给出经营建议。"), elem_classes=["html-block"])

                        gr.HTML('<div class="step-line"><span class="step-no">01</span>导入平台数据（可选）</div>', elem_classes=["html-block"])
                        with gr.Group(elem_classes=["panel"]):
                            with gr.Row(elem_classes=["form-grid"]):
                                platform_file = gr.File(
                                    label="上传 CSV / XLSX",
                                    file_types=[".csv", ".xlsx", ".xlsm"],
                                    scale=2,
                                )
                                with gr.Column(scale=1, min_width=160):
                                    cost_an = gr.Number(label="成本价", value=0)
                                    price_an = gr.Number(label="售价", value=0)
                                    vol_an = gr.Number(label="销量", value=0)
                        with gr.Row(elem_classes=["action-row"]):
                            btn_import = gr.Button("导入并生成看板", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("平台数据看板"), elem_classes=["html-block"])
                            platform_out = gr.HTML(
                                '<div class="empty-hint">上传文件后点击「导入并生成看板」，这里会显示 KPI、趋势和商品排行。</div>',
                                elem_classes=["html-block"],
                            )
                            platform_msg = gr.Markdown("*支持生意参谋 / 京东商智导出的 CSV 或 XLSX，表头需含销售额或销量。*")
                            export_file = gr.File(label="导出规范化数据 CSV")
                            gr.DownloadButton("下载数据模板", value=store_data.write_template())

                        gr.HTML('<div class="step-line"><span class="step-no">02</span>生成运营建议</div>', elem_classes=["html-block"])
                        data_in = gr.Textbox(
                            label="经营数据",
                            placeholder="可手动填写，或在上一步导入后自动填充",
                            lines=6,
                        )
                        with gr.Row(elem_classes=["action-row"]):
                            btn_analyst = gr.Button("生成运营建议", variant="primary")
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("经营建议"), elem_classes=["html-block"])
                            analyst_out = gr.Markdown("*导入数据或手动填写后点击「生成运营建议」。*")
                            pricing_out = gr.Textbox(label="定价建议", lines=3, interactive=False)

                        btn_import.click(run_platform_import, [platform_file, cost_an, price_an],
                                         [platform_out, data_in, export_file, platform_msg])
                        btn_analyst.click(run_analyst, [data_in, cost_an, price_an, vol_an], [analyst_out, pricing_out])

                    with gr.TabItem("3C 技术尽调"):
                        gr.HTML(_page_head("3C 技术尽调", "分析通信协议、芯片方案与技术壁垒，五个维度打分；选择品类可追溯到本地知识库。"), elem_classes=["html-block"])
                        with gr.Group(elem_classes=["panel"]):
                            _tech_mode = gr.Radio(
                                choices=[("双竞品对比", "compare"), ("单产品分析", "single")],
                                value="compare",
                                label="分析模式",
                                elem_classes=["tech-mode"],
                            )
                            with gr.Row(elem_classes=["form-grid"]):
                                _tech_a = gr.Textbox(label="产品 A *", placeholder="如: Anker 65W 氮化镓充电器", elem_classes=["tech-input"])
                                _tech_b = gr.Textbox(label="产品 B（对比模式）", placeholder="如: 贝尔金 65W 氮化镓充电器", elem_classes=["tech-input"])
                            _tech_cat = gr.Dropdown(
                                label="品类（用于知识库溯源，可选）",
                                choices=price_categories,
                                value="数码配件" if "数码配件" in price_categories else None,
                                allow_custom_value=True,
                                elem_classes=["tech-input"],
                            )
                        with gr.Row(elem_classes=["action-row"]):
                            _tech_btn = gr.Button("开始分析", variant="primary", elem_classes=["tech-btn"])
                        with gr.Group(elem_classes=["result-panel"]):
                            gr.HTML(_result_head("分析结果"), elem_classes=["html-block"])
                            _tech_result = gr.HTML(
                                '<div class="empty-hint">填写产品名称后点击「开始分析」，通常需要 20-60 秒。</div>',
                                elem_classes=["html-block"],
                            )
                            _tech_state = gr.State()
                            _tech_pdf_btn = gr.Button("导出 PDF 报告")
                            _tech_pdf_file = gr.File(label="PDF 报告")
                        _tech_btn.click(fn=run_3c, inputs=[_tech_a, _tech_b, _tech_mode, _tech_cat],
                                        outputs=[_tech_result, _tech_state])
                        _tech_pdf_btn.click(fn=export_3c_pdf, inputs=[_tech_state], outputs=[_tech_pdf_file])


            with gr.TabItem("知识库"):
                with gr.Tabs():
                    # FAQ 管理
                    with gr.TabItem("FAQ 问答"):
                        gr.HTML(_page_head("FAQ 问答", "常用问答对，客服回复时优先命中这里，命中率高时答案更稳定。"), elem_classes=["html-block"])
                        faq_display = gr.Markdown(refresh_faq_list())
                        with gr.Row():
                            faq_q = gr.Textbox(label="问题", placeholder="如: 什么时候发货", scale=2)
                            faq_a = gr.Textbox(label="答案", placeholder="如: 工作日24小时内发货...", scale=3)
                        with gr.Row():
                            btn_faq_add = gr.Button("新增 FAQ", variant="primary")
                            faq_del_idx = gr.Textbox(label="删除编号", placeholder="输入要删除的 FAQ 编号", scale=1)
                            btn_faq_del = gr.Button("删除")
                        btn_faq_add.click(add_faq_entry, [faq_q, faq_a], [faq_q, faq_display])
                        btn_faq_del.click(delete_faq_entry, [faq_del_idx], [faq_del_idx, faq_display])

                    # 价格库管理
                    with gr.TabItem("价格库"):
                        gr.HTML(_page_head("价格库", "维护各品类的价格带与竞争度，选品分析会直接引用。"), elem_classes=["html-block"])
                        price_display = gr.Markdown(refresh_price_view)
                        with gr.Row():
                            pc_cat = gr.Textbox(label="品类", placeholder="如: 宠物用品")
                            pc_name = gr.Textbox(label="子类名称", placeholder="如: 猫抓板")
                        with gr.Row():
                            pc_price = gr.Textbox(label="价格范围", placeholder="如: 15-50")
                            pc_cost = gr.Textbox(label="成本范围", placeholder="如: 5-15")
                            pc_comp = gr.Dropdown(label="竞争度", choices=["极低", "低", "中低", "中", "高", "极高"], value="中")
                        btn_price_add = gr.Button("新增价格条目", variant="primary")
                        btn_price_add.click(add_price_item, [pc_cat, pc_name, pc_price, pc_cost, pc_comp], [pc_cat, price_display])

                    # 供应商管理
                    with gr.TabItem("供应商库"):
                        gr.HTML(_page_head("供应商库", "记录产区、批发价与起订量，货源分析会据此匹配。"), elem_classes=["html-block"])
                        sup_display = gr.Markdown(refresh_supplier_view)
                        with gr.Row():
                            sc_cat = gr.Textbox(label="品类", placeholder="如: 宠物用品")
                            sc_name = gr.Textbox(label="产品名称", placeholder="如: 猫抓板")
                        with gr.Row():
                            sc_wp = gr.Textbox(label="批发价范围", placeholder="如: 3-12")
                            sc_moq = gr.Textbox(label="MOQ", placeholder="如: 50-300")
                            sc_region = gr.Textbox(label="产区", placeholder="如: 河北邢台")
                        btn_sup_add = gr.Button("新增供应商产品", variant="primary")
                        btn_sup_add.click(add_supplier_item, [sc_cat, sc_name, sc_wp, sc_moq, sc_region], [sc_cat, sup_display])

                    # 上架模板
                    with gr.TabItem("上架模板"):
                        gr.HTML(_page_head("上架模板", "各品类的标题与详情结构模板，生成上架素材时按此套用。"), elem_classes=["html-block"])
                        tmpl_display = gr.Markdown(refresh_template_view)
                        gr.Markdown("> 模板仅支持通过 JSON 文件直接编辑：`knowledge/data/product_templates.json`")

                    # 对话记录管理
                    with gr.TabItem("对话记录"):
                        gr.HTML(_page_head("对话记录", "沉淀历史问答，客服回复时会检索相似对话作为参考。"), elem_classes=["html-block"])

                        with gr.Tabs():
                            with gr.TabItem("查看对话记录"):
                                conv_display = gr.Markdown(refresh_conversation_view)
                                conv_search_stage = gr.Dropdown(
                                    label="按场景筛选",
                                    choices=[("全部", ""), ("售前咨询", "pre_sale"), ("地址修改", "post_sale_address"),
                                             ("使用说明", "post_sale_usage"), ("商品售后", "after_sales")],
                                    value="",
                                )
                                conv_search_query = gr.Textbox(label="关键词搜索（可选）", placeholder="输入搜索关键词...")
                                conv_search_btn = gr.Button("搜索", variant="primary")
                                conv_search_btn.click(refresh_conversation_view,
                                                      [conv_search_stage, conv_search_query], conv_display)
                                gr.Markdown("---")

                            with gr.TabItem("新增对话记录"):
                                with gr.Row():
                                    conv_stage = gr.Dropdown(
                                        label="对话场景",
                                        choices=[("售前咨询（卖点/性能/性价比）", "pre_sale"),
                                                 ("买后地址修改/查询", "post_sale_address"),
                                                 ("买后使用说明", "post_sale_usage"),
                                                 ("商品售后", "after_sales")],
                                        value="pre_sale",
                                    )
                                    conv_outcome = gr.Dropdown(
                                        label="处理结果",
                                        choices=[("", ""), ("成交", "成交"), ("未成交", "未成交"),
                                                 ("已解决", "已解决"), ("退款", "退款"), ("换货", "换货")],
                                        value="",
                                    )
                                conv_question = gr.Textbox(label="顾客问题", placeholder="如：这个杯子保温效果怎么样？", lines=2)
                                conv_response = gr.Textbox(label="商家回复", placeholder="如：这款杯子采用316不锈钢...", lines=4)
                                with gr.Row():
                                    conv_product = gr.Textbox(label="商品名称（可选）", placeholder="如：智能保温杯")
                                    conv_category = gr.Textbox(label="品类（可选）", placeholder="如：家居日用")
                                    conv_tags = gr.Textbox(label="标签（可选，逗号分隔）", placeholder="如：保温效果,材质")
                                btn_conv_add = gr.Button("保存记录", variant="primary")
                                conv_add_msg = gr.Textbox(label="操作结果", interactive=False)
                                btn_conv_add.click(
                                    add_conversation_entry,
                                    [conv_stage, conv_question, conv_response,
                                     conv_product, conv_category, conv_tags, conv_outcome],
                                    [conv_add_msg, conv_display],
                                )

                            with gr.TabItem("删除记录"):
                                conv_del_id = gr.Number(label="输入要删除的记录ID", precision=0)
                                btn_conv_del = gr.Button("删除", variant="stop")
                                conv_del_msg = gr.Textbox(label="操作结果", interactive=False)
                                btn_conv_del.click(
                                    delete_conversation_entry,
                                    [conv_del_id],
                                    [conv_del_msg, conv_display],
                                )

            with gr.TabItem("系统"):
                gr.HTML(_page_head("系统状态", "查看最近 24 小时的模型调用量、成功率与响应耗时。"), elem_classes=["html-block"])
                with gr.Row(elem_classes=["action-row"]):
                    refresh_btn = gr.Button("刷新数据", variant="primary")
                with gr.Group(elem_classes=["result-panel"]):
                    gr.HTML(_result_head("调用监控（最近 24 小时）"), elem_classes=["html-block"])
                    status_out = gr.Markdown("*页面加载时自动刷新，也可点击「刷新数据」。*")
                    recent_out = gr.Markdown()
                refresh_btn.click(refresh_system_status, outputs=[status_out, recent_out])
                app.load(refresh_system_status, outputs=[status_out, recent_out])

    return app

def main():
    # 初始化用户数据库（延迟到启动时执行）
    _init_users()

    # 启动时自动检查
    ok, _, _ = check_env()
    if not ok:
        logger.warning(f"LLM({LLM_PROVIDER}) 不可用，启动后功能受限")

    app = build_app()
    app.queue()
    app.launch(
        server_name="127.0.0.1",
        server_port=WEB_PORT,
        auth=check_login,
        auth_message=f"请输入用户名和密码（默认: {ADMIN_USER} / {ADMIN_PASS}）",
        share=False,
        show_error=True,
    )

if __name__ == "__main__":
    main()
