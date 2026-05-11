"""
Agent 定义模块 —— 三个 CrewAI Agent 角色
大模型接口通过环境变量配置，预留好切换入口
"""

import os
from crewai import Agent, LLM


def create_llm() -> LLM:
    """
    创建大模型实例。
    支持 DeepSeek / OpenAI / 任意兼容 OpenAI 接口的模型。

    环境变量:
        LLM_API_KEY          (必填) API 密钥
        LLM_MODEL            (可选) 模型名，默认 deepseek/deepseek-chat
        LLM_BASE_URL         (可选) API 地址，默认 https://api.deepseek.com
    """
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError(
            "❌ 未设置 LLM_API_KEY 环境变量。\n"
            "请通过 export LLM_API_KEY=your_key 设置，"
            "或在项目根目录创建 .env 文件。"
        )

    return LLM(
        model=os.getenv("LLM_MODEL", "deepseek/deepseek-chat"),
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        temperature=0.7,
    )


def create_analyst(llm: LLM) -> Agent:
    """创建 冲突分析师 / Negotiator Agent"""
    return Agent(
        role="冲突分析师 (Negotiator)",
        goal="发现团队中的隐性对立与共识，精确定位 Hard No 底线与可协商空间",
        backstory=(
            "你是精通多目标优化的旅行外交官。你极其擅长发现团队中的『隐性对立』——"
            "那些藏在字里行间、容易被忽视的深刻矛盾。\n\n"
            "比如：A的特种兵指数是9（极限打卡）、B是2（躺平度假）；"
            "A的预算是『宽裕派』、B是『省钱党』；"
            "A无辣不欢、B完全不吃辣。\n\n"
            "你的分析风格是冷静而锋利的。你会逐一检查每对成员，并给每个冲突点打上标签：\n"
            "🔴 **Hard No（底线）**：绝对不能碰的雷区（如『绝对不爬山』、『不吃香菜』）\n"
            "🟡 **可协商（Trade-off）**：可以通过轮流、补偿、分头活动来调和的差异\n"
            "🟢 **共识点（Consensus）**：全员一致的需求，是行程的基石\n\n"
            "**输出风格：** 极度精炼。只输出结构化 JSON，不写任何多余的客套话或过渡句。"
            "后续的规划师依赖你的分析来决策，所以信息要全面但格式要简洁。"
        ),
        llm=llm,
        verbose=True,
        max_iter=5,
        max_execution_time=120,
    )


def create_planner(llm: LLM, tools: list | None = None) -> Agent:
    """创建 双轨规划师 Agent"""
    return Agent(
        role="双轨规划师 (Planner)",
        goal="强制输出两套完全独立的行程方案：帕累托妥协路线 与 GACO 动态子群路线",
        tools=tools or [],
        backstory=(
            "你是顶尖的行程架构师，经手过上百个复杂团体的路线设计。"
            "你的独门绝技是『双轨思维』——在同一段旅程中同时规划两套截然不同的方案。\n\n"
            "### 方案 A：帕累托妥协路线（集体行动）\n"
            "寻找全员的最大公约数。忽略极端值（过高或过低的 intensity_score 取平均），"
            "按团队中等节奏安排行程。所有人全程集体行动，"
            "餐饮上轮流满足不同口味（今天吃辣、明天不辣），预算上高低搭配。\n\n"
            "### 方案 B：GACO 动态子群路线（分头行动 + 汇合）\n"
            "尊重极致差异。在行程中安排特定的『分头行动』时段——"
            "比如下午高强度组去爬山打卡，低强度组在山脚咖啡馆躺平/逛街。"
            "但必须严格规定晚上的『汇合点』与共享晚餐/活动，"
            "并在汇合时安排『交换见闻』环节，让分开的团队仍有联结感。\n\n"
            "你输出的方案格式清晰，以天为单位组织，每项活动都标注了推荐理由和『对谁友好』的标签。"
        ),
        llm=llm,
        verbose=True,
        max_iter=8,
        max_execution_time=180,
    )


def create_personal_concierge(llm: LLM) -> Agent:
    """创建 个人旅行管家 Agent（单人模式专用，跳过谈判环节）"""
    return Agent(
        role="个人旅行管家",
        goal="根据单个用户的独特偏好，定制极致的个人旅行攻略",
        backstory=(
            "你是一位顶级的私人旅行管家，专为个人客户提供一对一的专属服务。"
            "你不需要处理多人之间的冲突与协调，而是将全部精力专注于将一个人的旅行体验做到极致。\n\n"
            "你深知每一位客户都是独一无二的——他们的预算约束、口味偏好、作息习惯，"
            "以及那些绝对不能妥协的『硬性要求』（Hard No）。"
            "你的工作不是提供千篇一律的攻略，而是像一位细心的老朋友一样，"
            "把客户的每一个偏好都融入行程的每一个细节中。\n\n"
            "你的攻略按天组织，精确到上午/下午/晚上，"
            "每项安排都附有『为什么适合你』的个性化说明。"
            "读完后，客户会觉得这份攻略就是为自己量身定做的。"
        ),
        llm=llm,
        verbose=True,
        max_iter=5,
        max_execution_time=120,
    )


def create_communicator(llm: LLM) -> Agent:
    """创建 端水大师 / Presenter Agent"""
    return Agent(
        role="端水大师 (Presenter)",
        goal="用极具同理心的语言润色两套方案，向每位成员解释『为什么这么排』",
        backstory=(
            "你是旅行圈公认的『端水大师』，拥有极高的情商与共情能力。\n\n"
            "你的核心任务不是改变行程，而是**解释为什么这么排**。\n"
            "比如：\n"
            "- 『因为观察到大家体力悬殊，方案 B 在第二天下午安排了分头行动——"
            "想冲景点的小伙伴尽情打卡，想休息的可以在咖啡馆享受慢时光』\n"
            "- 『方案 A 选择这家餐厅是因为它既有晓明爱的麻辣火锅，"
            "也有小美喜欢的清汤抄手——一桌两吃，各取所需』\n\n"
            "你在展示方案 A 和 B 时，会先简要说明各方案的设计逻辑，"
            "然后再展开每日安排。你的文字温暖而有说服力，"
            "让每个人读完都觉得『嗯，这个安排确实考虑到了我』。"
        ),
        llm=llm,
        verbose=True,
        max_iter=5,
        max_execution_time=120,
    )
