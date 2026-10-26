"""Service Agent — 自动检索 FAQ + 历史对话记录生成客服回复"""

from typing import Any

from core.agent import ReActAgent
from config import AGENT_MODEL, AGENT_LIGHT_MODEL
from knowledge.conversation_rag import get_conversation_rag

SERVICE_SYSTEM = """你是专业电商客服，精通淘宝/拼多多平台规则。你的核心价值是**准确回答 + 情绪安抚 + 引导成交**。

## ⚡ 工具使用规则（必须遵守）
收到顾客问题后，必须先用工具查知识库，不能凭记忆编造：

1. 判断顾客问题属于哪个阶段，调用 **search_conversations** 搜索历史对话记录
   - 如果顾客在问性能/卖点/价格 → pre_sale 阶段
   - 如果顾客在问改地址/查订单 → post_sale_address 阶段
   - 如果顾客在问怎么用/怎么安装 → post_sale_usage 阶段
   - 如果顾客在问退换货/质量/售后 → after_sales 阶段
2. 再调用 **search_faq** 搜索 FAQ
3. 结合两者的结果，给出恰当的回复
4. 如果都没有匹配 → 如实告知，引导联系人工客服，绝不编造答案

## 场景响应策略

### 🟢 售前咨询（买家有意向但犹豫）
目标：解答疑虑 → 建立信任 → 引导下单
- 先肯定买家的关注点："您关心这个问题说明很细心"
- 用具体信息回答（尺寸/材质/使用效果）
- 适当制造紧迫感但不虚假："这款最近咨询的比较多，建议尽早下单"
- 结束语加转化引导："需要我现在帮您下单吗？今天发货哦"

### 🟡 售后问题（退换货/质量问题/物流延误）
目标：倾听 → 共情 → 解决
- **第一步永远是道歉和共情**："很抱歉给您带来了不好的体验，我完全理解您的感受"
- 明确告知处理流程和时间节点
- 主动承担而非推卸："我来帮您跟进，不需要您再打电话"
- 给出具体方案而非模糊承诺："我帮您申请换货，预计后天新货发出"

### 🔴 投诉/愤怒顾客
目标：灭火 → 确认问题 → 给出明确补偿方案
- 道歉要真诚不敷衍："非常抱歉，这个问题确实是我们的疏忽"
- 不要解释原因或推卸（顾客不关心为什么错，只关心怎么解决）
- 给方案要有选择："您看是给您退款还是重新发一件？"
- 适当补偿："为表歉意，给您补偿一张10元优惠券"
- **绝对不能说**："这是快递的问题""系统就是这样""我也没办法"

### 🔵 物流查询/地址修改
- 先查历史对话记录中的类似处理方式
- 再查 FAQ 中的物流政策
- 给出查询方法（快递单号/预计时效）
- 超时未到的主动表示跟进
- 地址修改说明操作方法和注意事项

### 🟣 使用说明/安装指导
- 先查历史对话记录中的类似解答
- 提供清晰的分步指导
- 说明注意事项
- 可建议联系客服获取视频教程

## 回复质量标准
✓ 每次回复 50-150字，信息密度高但不啰嗦
✓ 一个问题最多追问2次，第3次直接给电话/微信
✓ 涉及金额/日期/地址等关键信息必须准确复述确认
✓ 使用适当的emoji增加亲和力（每2-3条用1个即可）

## 升级标准
以下情况果断引导联系人工/电话：
- 涉及退款金额争议 >50元
- 顾客明确说"投诉""举报""差评"
- 需要查询具体订单物流状态（你查不到）
- 同一问题顾客重复3次以上表示不满

## 禁止行为
- 不透露你是AI（不说"作为AI""根据算法""系统推荐"）
- 不对顾客说"您理解错了""你没看清楚"
- 不承诺做不到的事（"明天一定到""保证不坏"）
- 不提供法律/食品安全等专业意见
- 不在顾客未提及的情况下主动推销"""

class ServiceAgent(ReActAgent):
    """Service Agent — auto-retrieves FAQ + conversation records for responses"""

    def __init__(self):
        super().__init__(
            name="客服助手",
            description="售前咨询、售后处理、FAQ 应答 — 自动检索知识库和历史对话",
            system_prompt=SERVICE_SYSTEM,
            tools=[
                "search_faq",
                "search_conversations",
                "save_note",
                "recall_notes",
            ],
            use_memory=True,
            model=AGENT_MODEL["service"],
            light_model=AGENT_LIGHT_MODEL["service"],
        )

    def run(self, input_data: Any, session_id: str = None, **kwargs) -> dict:
        query = input_data if isinstance(input_data, str) else input_data.get("query", "")
        product_context = kwargs.get("product_context", "")

        # Auto-inject similar past conversations via Conversation RAG
        conv_rag = get_conversation_rag()
        # Determine the most likely stage from the query
        stage = self._detect_stage(query)
        # Try to extract product category from product_context if available
        category = ""
        if product_context:
            import re as _re
            m = _re.search(r'(?:品类|category)[：:]\s*(\S+)', product_context, _re.IGNORECASE)
            if m:
                category = m.group(1)
        conv_context = conv_rag.format_context(query, stage=stage, category=category)

        user_parts = [f"顾客问题：{query}"]
        if conv_context:
            user_parts.append(f"\n{conv_context}")
        if product_context:
            user_parts.append(f"\n【当前商品信息】\n{product_context}")
        user_parts.append("\n请先搜索历史对话记录和 FAQ 知识库，然后给出恰当的客服回复。")
        user_input = "\n".join(user_parts)

        result = super().run(user_input, session_id=session_id)
        response = result.get("report", "")

        # Auto-save this interaction as a conversation record for future learning
        if response and not response.startswith("[错误]") and not response.startswith("[超时]"):
            self._auto_save_interaction(query, response, stage)

        return {
            "agent": self.name,
            "query": query,
            "answer": response,
        }

    @staticmethod
    def _detect_stage(query: str) -> str:
        """Detect the conversation stage from the customer's query"""
        q = query.lower()

        # Post-sale address / order inquiry
        if any(kw in q for kw in ["地址", "改地址", "修改地址", "发货地址", "收货地址",
                                   "订单", "查订单", "订单号", "物流", "快递"]):
            return "post_sale_address"

        # Post-sale usage instructions
        if any(kw in q for kw in ["怎么用", "如何使用", "安装", "怎么安装", "怎么操作",
                                   "使用说明", "教程", "怎么充电", "怎么清洗", "怎么保养"]):
            return "post_sale_usage"

        # After-sales service
        if any(kw in q for kw in ["退货", "换货", "退款", "售后", "维修", "保修",
                                   "坏了", "碎了", "破了", "问题", "质量", "投诉",
                                   "赔偿", "补偿", "补发", "漏发", "发错", "瑕疵"]):
            return "after_sales"

        # Pre-sale (default for sales-related queries)
        if any(kw in q for kw in ["多少钱", "价格", "优惠", "包邮", "运费",
                                   "质量", "材质", "效果", "好用", "卖点",
                                   "性能", "性价比", "值得", "推荐"]):
            return "pre_sale"

        # Default: return empty to search all stages
        return ""

    @staticmethod
    def _auto_save_interaction(question: str, response: str, stage: str):
        """Automatically save high-quality interactions as conversation records"""
        # Only save non-trivial interactions with a valid stage
        if len(question) < 10 or len(response) < 20 or not stage:
            return
        try:
            from knowledge.conversation_records import add_record
            add_record(
                stage=stage,
                customer_question=question[:500],
                merchant_response=response[:500],
                tags="auto-saved",
            )
        except Exception:
            pass
