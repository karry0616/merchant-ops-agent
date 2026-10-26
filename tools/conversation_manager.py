"""Conversation Record Manager — CRUD & import for merchant's past customer conversations

Covers four stages:
  - pre_sale:         售前咨询（卖点/性能/性价比）
  - post_sale_address: 买后地址修改/查询
  - post_sale_usage:   买后使用说明
  - after_sales:       商品售后
"""

from knowledge.conversation_records import (
    add_record,
    update_record,
    delete_record,
    get_records,
    get_record_count,
    import_records,
    STAGES,
)


def add_conversation_record(
    stage: str,
    customer_question: str,
    merchant_response: str,
    product: str = "",
    category: str = "",
    tags: str = "",
    outcome: str = "",
) -> str:
    """Add a merchant-customer conversation record for future reference.

    Use this to save real customer conversations so the agent can learn from them.

    Args:
        stage: Conversation stage. One of: pre_sale (售前咨询), post_sale_address (地址修改), post_sale_usage (使用说明), after_sales (售后)
        customer_question: What the customer asked
        merchant_response: How the merchant responded
        product: Product name (optional)
        category: Product category (optional)
        tags: Comma-separated tags for search (optional), e.g. "退换货,质量问题"
        outcome: Outcome (optional), e.g. "成交", "已解决", "退款"
    """
    if stage not in STAGES:
        stages_list = ", ".join(f"{k}({v})" for k, v in STAGES.items())
        return f"错误：无效的场景「{stage}」。可选场景: {stages_list}"

    if not customer_question.strip() or not merchant_response.strip():
        return "错误：顾客问题和商家回复不能为空"

    record = add_record(stage, customer_question, merchant_response, product, category, tags, outcome)
    if record:
        stage_label = STAGES.get(stage, stage)
        return f"✅ 已保存{stage_label}对话记录 (ID: {record['id']})"
    return "❌ 保存失败"


def search_conversation_records(
    query: str = "",
    stage: str = "",
    product: str = "",
    category: str = "",
    limit: int = 10,
) -> str:
    """Search past conversation records by keyword, stage, product, or category.

    Use this to find similar past customer interactions to inform responses.

    Args:
        query: Search keywords matching customer question, merchant response, or tags
        stage: Filter by stage. One of: pre_sale, post_sale_address, post_sale_usage, after_sales
        product: Filter by product name
        category: Filter by product category
        limit: Max results to return (default 10, max 50)
    """
    if limit > 50:
        limit = 50

    records = get_records(stage=stage, keyword=query, product=product, category=category, limit=limit)
    if not records:
        return "未找到匹配的历史对话记录"

    lines = [f"找到 {len(records)} 条匹配的历史对话记录：\n"]
    for r in records:
        stage_label = STAGES.get(r.get("stage", ""), r.get("stage", ""))
        tags = ", ".join(r.get("tags", [])) if r.get("tags") else ""
        product_info = f"[{r['product']}] " if r.get("product") else ""
        outcome = f" → {r['outcome']}" if r.get("outcome") else ""

        lines.append(f"--- ID:{r['id']} | {stage_label}{outcome} ---")
        lines.append(f"  商品：{product_info}{r.get('category', '')}")
        lines.append(f"  顾客：{r['customer_question'][:200]}")
        lines.append(f"  回复：{r['merchant_response'][:200]}")
        if tags:
            lines.append(f"  标签：{tags}")
        lines.append("")

    return "\n".join(lines)


def delete_conversation_record(record_id: int) -> str:
    """Delete a conversation record by ID.

    Args:
        record_id: The ID of the record to delete
    """
    if delete_record(record_id):
        return f"✅ 已删除 ID {record_id} 的对话记录"
    return f"❌ 未找到 ID {record_id} 的对话记录"


def get_conversation_stats() -> str:
    """Get statistics about stored conversation records, grouped by stage."""
    counts = get_record_count()
    lines = ["[对话记录统计]\n"]
    lines.append(f"  总计：{counts['total']} 条\n")
    for stage_key, stage_label in STAGES.items():
        count = counts.get(stage_key, 0)
        bar = "█" * min(count, 20) + "░" * max(0, 20 - min(count, 20))
        lines.append(f"  {stage_label}: {count}条 {bar}")
    return "\n".join(lines)
