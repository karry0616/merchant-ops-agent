"""Tech Analyst Agent — 3C 产品技术分析（协议/芯片/壁垒）"""

import json
import re
from typing import Any

from core.agent import ReActAgent
from config import AGENT_MODEL, AGENT_LIGHT_MODEL

TECH_ANALYST_SYSTEM = """你是一个专业的 3C 产品技术分析师。你的任务是根据用户输入的产品名称，分析该产品的技术特征，并给出可比较的维度评分。

## 输出格式（严格遵守）
你必须返回一个 JSON 对象，字段如下：
```json
{
  "protocol": "通信协议，如 USB PD3.0、WiFi 6、蓝牙5.3、QC3.0 等",
  "chip": "芯片方案，如 高通骁龙、联发科天玑、英飞凌、TI 等",
  "barrier": "技术壁垒等级：高/中/低",
  "scores": {
    "协议先进性": 4.0,
    "芯片方案": 3.5,
    "技术门槛": 3.0,
    "生态兼容": 4.0,
    "量产成熟度": 4.5
  },
  "basis": {
    "protocol": "判断依据，不超过 60 字",
    "chip": "判断依据，不超过 60 字",
    "barrier": "判断依据，不超过 60 字",
    "scores": "评分理由，不超过 80 字"
  }
}
```

## 分析规则
1. **protocol（通信协议）**：根据产品类型判断主流协议
   - 充电器：USB PD、QC、PPS 等
   - 耳机：蓝牙版本（5.0/5.2/5.3）、编解码协议（AAC/aptX/LDAC）
   - 路由器：WiFi 标准（WiFi 5/6/6E/7）
   - 手机：5G 频段、WiFi 标准、NFC 等

2. **chip（芯片方案）**：根据产品类型判断主流芯片
   - 充电器：英飞凌、TI、PI、纳微半导体等
   - 耳机：高通、络达、恒玄、BES 等
   - 路由器：高通、联发科、博通、瑞昱等
   - 手机：高通骁龙、联发科天玑、苹果 A 系列等

3. **barrier（技术壁垒）**：评估进入该领域的难度
   - 高：需要核心专利、复杂工艺、高研发投入
   - 中：需要一定技术积累、供应链整合能力
   - 低：技术成熟、方案公开、门槛较低

4. **scores（五个维度，0-5 分，一位小数）**
   - 协议先进性：协议版本与覆盖范围越新越广，分越高
   - 芯片方案：方案集成度与性能越强，分越高
   - 技术门槛：越难被山寨复制，分越高（对毛利是正向）
   - 生态兼容：跨品牌、跨设备兼容越好，分越高
   - 量产成熟度：供应链越成熟、良率越稳，分越高
   - 评分基准：5 = 行业领先，3 = 主流水平，1 = 明显落后或空白

## 重要约束
- 只返回 JSON，不要有任何额外文字
- 不要使用 markdown 代码块包裹
- 如果无法确定，给出最可能的答案，并在 basis 里注明"推测"
- scores 必须是 0-5 之间的数字，不能是文字
"""


class TechAnalystAgent(ReActAgent):
    """3C 技术分析师 — 分析产品的协议/芯片/壁垒"""

    def __init__(self):
        super().__init__(
            name="3C技术分析师",
            description="分析 3C 产品的通信协议、芯片方案、技术壁垒",
            system_prompt=TECH_ANALYST_SYSTEM,
            tools=["analyze_3c_product"],
            use_memory=True,
            model=AGENT_MODEL.get("tech_analyst", "deepseek:deepseek-chat"),
            light_model=AGENT_LIGHT_MODEL.get("tech_analyst", "deepseek:deepseek-chat"),
        )

    def run(self, input_data: Any, session_id: str = None, **kwargs) -> dict:
        if isinstance(input_data, str):
            product_name = input_data
        elif isinstance(input_data, dict):
            product_name = input_data.get("product_name", "") or input_data.get("name", "")
        else:
            product_name = str(input_data)

        if not product_name.strip():
            return {
                "agent": self.name,
                "error": "请输入产品名称",
                "protocol": "",
                "chip": "",
                "barrier": "",
                "scores": {},
                "basis": {},
            }

        user_input = f"请分析这个 3C 产品：{product_name}"
        result = super().run(user_input, session_id=session_id)
        report = result.get("report", "")

        # 尝试从报告中提取 JSON
        tech_data = self._extract_json(report)

        return {
            "agent": self.name,
            "product_name": product_name,
            "protocol": tech_data.get("protocol", "未识别"),
            "chip": tech_data.get("chip", "未识别"),
            "barrier": tech_data.get("barrier", "未识别"),
            "scores": tech_data.get("scores", {}) if isinstance(tech_data.get("scores"), dict) else {},
            "basis": tech_data.get("basis", {}) if isinstance(tech_data.get("basis"), dict) else {},
            "report": report,
            "tool_calls": result.get("tool_calls", 0),
        }

    def _extract_json(self, text: str) -> dict:
        """从任意文本中提取第一个可解析的 JSON 对象（支持嵌套）"""
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        return {"protocol": "", "chip": "", "barrier": ""}
