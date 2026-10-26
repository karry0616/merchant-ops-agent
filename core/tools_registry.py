"""All tool registrations — import once to register all tools"""

# Import tool decorator
from core.tool import tool

# Tool 1: Knowledge Base Search

@tool(description="Search the product knowledge base for pricing data by category")
def search_price_library(category: str) -> str:
    """查找价格库中某个品类的市场价格参考

    Args:
        category: 商品品类名称，如"服装"、"数码配件"、"家居日用"
    """
    from knowledge.rag import get_rag
    rag = get_rag()
    ctx = rag.format_price_context(category)
    if not ctx:
        return f"知识库中未找到「{category}」的价格数据"
    return ctx

@tool(description="Search supplier database for factory sourcing info by category")
def search_suppliers(category: str) -> str:
    """查找某个品类的供应商/货源信息，包括产区、批发价、MOQ

    Args:
        category: 商品品类名称，如"服装"、"3C配件"、"玩具"
    """
    from knowledge.rag import get_rag
    rag = get_rag()
    ctx = rag.format_supplier_context(category)
    if not ctx:
        return f"知识库中未找到「{category}」的供应商数据"
    return ctx

@tool(description="Search regional industry cluster advantages for a product category")
def search_regions(category: str) -> str:
    """查找某个品类的地区产业集群优势，告诉你去哪里找工厂

    Args:
        category: 商品品类名称，如"服装"、"箱包"、"陶瓷"
    """
    from knowledge.rag import get_rag
    rag = get_rag()
    ctx, regions = rag.format_region_context(category)
    if not ctx:
        return f"知识库中未找到「{category}」的产区数据"
    return f"{ctx}\n\n涉及产区：{regions}"

@tool(description="Search FAQ knowledge base for customer service questions")
def search_faq(query: str) -> str:
    """查找 FAQ 知识库，获取客服常见问题答案

    Args:
        query: 顾客问题的关键词，去掉语气词，如"退换货"、"发货时间"
    """
    from knowledge.rag import get_rag
    rag = get_rag()
    ctx = rag.format_faq_context(query)
    if not ctx:
        return "FAQ 库中未找到相关问题"
    return ctx

# Tool 2: Taobao Market Data

@tool(description="Get Taobao search suggestion keywords (reflects real user demand)")
def taobao_suggest(keyword: str) -> str:
    """获取淘宝搜索下拉联想词，了解用户真实搜索需求

    Args:
        keyword: 搜索关键词，如"学生书包"、"蓝牙耳机"
    """
    from tools.taobao import suggest, format_suggest_report
    results = suggest(keyword)
    return format_suggest_report(results, keyword) or f"未能获取到「{keyword}」的搜索数据"

# Tool 3: Financial Calculator

@tool(description="Calculate profit margin, costs, and revenue for a product")
def calculate_profit(cost: float, price: float, volume: int = 1,
                     logistics: float = 0) -> str:
    """计算商品利润：输入成本、售价、销量，输出利润和利润率

    Args:
        cost: 商品成本价（元）
        price: 商品售价（元）
        volume: 销售数量，默认1
        logistics: 物流成本（元），默认0
    """
    from tools.calculator import profit_analysis
    result = profit_analysis(cost, price, volume, logistics_cost=logistics)
    lines = [
        f"📊 利润分析",
        f"  营收: ¥{result['revenue']}",
        f"  总成本: ¥{result['total_cost']}",
        f"  利润: ¥{result['profit']}",
        f"  利润率: {result['margin']}%",
    ]
    return "\n".join(lines)

@tool(description="Suggest optimal pricing based on cost and target margin")
def suggest_price(cost: float, target_margin: float = 30.0) -> str:
    """建议售价：根据成本和目标利润率，给出保本价/常规价/溢价价

    Args:
        cost: 商品成本价（元）
        target_margin: 目标利润率（百分比），默认30%
    """
    from tools.calculator import price_suggestion
    result = price_suggestion(cost, target_margin)
    lines = [
        f"💰 定价建议（成本 ¥{result['cost']}）",
        f"  保本价: ¥{result['min_price']}",
        f"  常规售价: ¥{result['competitive_price']}",
        f"  溢价售价: ¥{result['premium_price']}",
    ]
    return "\n".join(lines)

@tool(description="Score a product keyword/category for market potential (0-100)")
def score_keyword(search_volume: int, competition: int,
                  avg_price: float, cost: float) -> str:
    """评估关键词/品类的市场潜力，返回0-100分

    Args:
        search_volume: 月搜索量（整数）
        competition: 竞争度0-100（越高越激烈）
        avg_price: 市场均价（元）
        cost: 成本价（元）
    """
    from tools.calculator import keyword_score
    score = keyword_score(search_volume, competition, avg_price, cost)
    level = "优秀" if score >= 70 else "良好" if score >= 50 else "一般" if score >= 30 else "较差"
    return f"品类评分: {score}/100 ({level})"

# Tool 4: 1688 Sourcing

@tool(description="Generate 1688 search URL for product sourcing")
def generate_1688_url(product_name: str, search_type: str = "产品") -> str:
    """生成1688搜索链接：type=产品 搜商品报价，type=工厂 找供应商

    Args:
        product_name: 商品名称，如"迷你风扇"、"保温杯"
        search_type: 搜索类型，"产品"搜商品报价，"工厂"找供应商，默认"产品"
    """
    from urllib.parse import quote
    encoded = quote(product_name)
    if search_type == "工厂":
        return f"https://s.1688.com/company/company_search.htm?keywords={encoded}%20%E5%B7%A5%E5%8E%82"
    return f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}"

# Tool 5: Memory & Notes

from core.memory import ConversationMemory
_memory_db = ConversationMemory()

@tool(description="Save a note/fact to memory for future reference")
def save_note(note: str) -> str:
    """保存一条笔记到记忆库，之后的对话可以回忆

    Args:
        note: 要保存的笔记内容文本
    """
    _memory_db.add_note("agent", note)
    return f"已保存笔记"

@tool(description="Recall previously saved notes from memory")
def recall_notes() -> str:
    """回忆之前保存的笔记，不需要参数"""
    notes = _memory_db.get_notes("agent")
    if not notes:
        return "暂无保存的笔记"
    return "\n".join(f"• {n}" for n in notes)

# Tool 6: Product Listing Generator

@tool(description="Generate product listing content (title, description, features)")
def generate_listing(product_name: str, category: str, features: str,
                     target_price: str = "", cost: str = "") -> str:
    """生成商品上架素材：标题、卖点、描述

    Args:
        product_name: 商品名称
        category: 所属品类
        features: 核心卖点，逗号分隔
        target_price: 目标售价（可选）
        cost: 成本价（可选）
    """
    from agents.lister import ListerAgent
    lister = ListerAgent()
    info = {
        "name": product_name,
        "category": category,
        "features": features,
        "target_price": target_price,
        "cost": cost,
    }
    result = lister.run(info)
    return result.get("listing_content", "生成失败")

# Tool 7: Product Price Manager

@tool(description="Search manually recorded products by keyword, category, or price range")
def search_product_db(keyword: str = "", category: str = "",
                      max_price: float = 0, min_price: float = 0) -> str:
    """搜索手动录入的商品价格库，返回匹配的商品列表（名称、价格、品类、来源平台）

    使用场景：查询之前记录过的商品价格，做价格参考。

    Args:
        keyword: 搜索关键词（可选），匹配名称/品类/备注
        category: 按品类筛选（可选）
        max_price: 最高价格筛选（可选），0表示不限制
        min_price: 最低价格筛选（可选），0表示不限制
    """
    from tools.product_manager import search_products
    results = search_products(keyword, category, max_price, min_price)
    if not results:
        return "商品库中未找到匹配的记录"
    lines = [f"找到 {len(results)} 个商品："]
    for r in results:
        lines.append(f"· {r['name']} — ¥{r['price']} | {r.get('category','')} | {r.get('platform','')}")
        if r.get("note"):
            lines.append(f"  备注：{r['note']}")
    return "\n".join(lines)

@tool(description="Add a product record to personal price database (name, price, category, platform)")
def add_product_record(name: str, price: float, category: str = "",
                       platform: str = "", note: str = "") -> str:
    """手动录入一个商品到价格库，供后续查询参考

    使用场景：在1688/淘宝上看到了一个商品的价格，记录下来以后用。

    Args:
        name: 商品名称
        price: 价格（元）
        category: 所属品类（可选）
        platform: 来源平台（可选），如"1688"、"淘宝"、"拼多多"
        note: 备注信息（可选）
    """
    from tools.product_manager import add_product
    rec = add_product(name, price, category, platform, note=note)
    return f"已记录：{rec['name']} ¥{rec['price']}（品类：{rec.get('category', '未分类')}）"


# ─────────────────────────────────────────────
# Tool 8: Conversation Record Manager (电商对话记录RAG)
# ─────────────────────────────────────────────

@tool(description="Search past merchant-customer conversation records by keyword, stage, or product")
def search_conversations(query: str = "", stage: str = "",
                         product: str = "", category: str = "",
                         limit: int = 10) -> str:
    """搜索历史对话记录，找到类似场景的商家回复参考。

    覆盖四个阶段：
    - pre_sale: 售前咨询（卖点/性能/性价比）
    - post_sale_address: 买后地址修改/查询
    - post_sale_usage: 买后使用说明
    - after_sales: 商品售后

    Args:
        query: 搜索关键词，匹配顾客问题、商家回复、标签
        stage: 筛选场景，可选 pre_sale / post_sale_address / post_sale_usage / after_sales
        product: 按商品名称筛选（可选）
        category: 按品类筛选（可选）
        limit: 返回结果数量上限，默认10
    """
    from tools.conversation_manager import search_conversation_records
    return search_conversation_records(query=query, stage=stage,
                                        product=product, category=category,
                                        limit=limit)


@tool(description="Add a merchant-customer conversation record so the agent can learn from past interactions")
def add_conversation_record(stage: str, customer_question: str,
                            merchant_response: str, product: str = "",
                            category: str = "", tags: str = "",
                            outcome: str = "") -> str:
    """保存一条商家与顾客的真实对话记录，供后续客服参考学习。

    Args:
        stage: 对话场景。pre_sale=售前咨询, post_sale_address=地址修改, post_sale_usage=使用说明, after_sales=售后
        customer_question: 顾客的问题/咨询内容
        merchant_response: 商家的回复内容
        product: 涉及的商品名称（可选）
        category: 所属品类（可选）
        tags: 逗号分隔的标签（可选），如"退换货,质量问题"
        outcome: 处理结果（可选），如"成交"、"已解决"、"退款"
    """
    from tools.conversation_manager import add_conversation_record as _add
    return _add(stage=stage, customer_question=customer_question,
                merchant_response=merchant_response, product=product,
                category=category, tags=tags, outcome=outcome)


@tool(description="Delete a conversation record by its ID")
def delete_conversation_record(record_id: int) -> str:
    """删除一条历史对话记录。

    Args:
        record_id: 要删除的记录ID
    """
    from tools.conversation_manager import delete_conversation_record as _del
    return _del(record_id)


@tool(description="Get statistics about stored conversation records grouped by stage")
def conversation_stats() -> str:
    """查看历史对话记录的数量统计，按场景分组显示。"""
    from tools.conversation_manager import get_conversation_stats
    return get_conversation_stats()


# ─────────────────────────────────────────────
# Tool 9: 3C Product Tech Analyzer (DeepSeek API)
# ─────────────────────────────────────────────

@tool(description="Analyze 3C product technical specs: protocol, chip, and technology barrier level")
def analyze_3c_product(product_name: str) -> str:
    """分析 3C 产品的技术特征：通信协议、芯片方案、技术壁垒等级。

    调用 DeepSeek API 获取结构化的技术分析数据。

    Args:
        product_name: 3C 产品名称，如"氮化镓充电器"、"蓝牙耳机"、"WiFi6路由器"
    """
    import os
    import json
    import requests
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    if not api_key:
        return "❌ 未配置 DEEPSEEK_API_KEY，请在 .env 文件中设置"

    system_prompt = """你是一个专业的 3C 产品技术分析师。根据用户输入的产品名称，返回 JSON 格式的技术分析结果。

必须返回以下 JSON 格式（不要有任何其他文字，不要用 markdown 代码块包裹）：
{
  "protocol": "通信协议，如 USB PD3.0、WiFi 6、蓝牙5.3",
  "chip": "芯片方案，如 高通骁龙、英飞凌、TI",
  "barrier": "技术壁垒：高/中/低"
}"""

    try:
        response = requests.post(
            f"{api_base}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"分析产品：{product_name}"}
                ],
                "temperature": 0.3,
                "max_tokens": 200,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()

        # 尝试解析 JSON
        try:
            result = json.loads(content)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            # 如果不是纯 JSON，尝试提取
            import re
            json_match = re.search(r'\{[^{}]*"protocol"[^{}]*\}', content, re.DOTALL)
            if json_match:
                return json_match.group(0)
            return content

    except requests.exceptions.Timeout:
        return "❌ API 请求超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        return f"❌ API 请求失败: {str(e)}"
    except Exception as e:
        return f"❌ 分析失败: {str(e)}"
