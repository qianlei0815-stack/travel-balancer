# 🌍 旅游端水大师 (Multi-Agent Travel Balancer) - MVP

## 1. 项目简介 (Project Overview)
本项目是一个多智能体(Multi-Agent)应用，旨在解决多人旅行中“众口难调”的问题。应用会分别收集每位成员的旅行偏好（预算、口味、作息等），然后通过多个 AI Agent 之间的协作与谈判，生成一个平衡所有人利益的最优行程规划，并高情商地解释协调理由。

## 2. 技术栈 (Tech Stack)
* **语言:** Python 3.10+
* **前端:** Streamlit (用于快速构建用户对话和结果展示界面)
* **多智能体框架:** CrewAI (用于编排和管理不同角色的 Agent)
* **大模型:** DeepSeek / OpenAI API (作为 Agent 的底层大脑)
* **数据存储:** 本地 JSON 文件 (MVP 阶段不使用数据库，将每个用户的需求暂存本地)

## 3. 核心文件结构 (Directory Structure)
* `app.py`: Streamlit 前端入口文件。
* `agents.py`: 定义 CrewAI 的所有 Agent 角色（收集者、谈判者、规划师）。
* `tasks.py`: 定义每个 Agent 需要执行的具体任务。
* `crew_logic.py`: 将 Agents 和 Tasks 组装成 Crew 并执行的业务逻辑。
* `amap_service.py`: 高德地图 API 封装（地理编码、路径规划、天气预报、地名提取）。
* `data/`: 存放用户偏好数据的 JSON 文件。

## 4. 开发与代码规范 (Coding Guidelines)
* **Streamlit 规范:** 优先使用 `st.chat_message` 和 `st.session_state` 来管理多用户的对话上下文。保持界面清爽。
* **Agent 设定:** 为每个 CrewAI Agent 编写丰富、明确的 `backstory`（背景故事）和 `goal`（目标）。
* **数据流转:** 严格校验 JSON 数据的读写，确保 Agent 之间传递的参数格式（如 Pydantic models）是一致的。
* **注释与文档:** 核心逻辑必须有清晰的中文注释，特别是 Agent 冲突解决（Negotiation）相关的逻辑。
* **错误处理:** 捕获 LLM API 超时或返回非结构化数据的情况，并在 Streamlit 界面给出友好的提示。

## 5. 常用命令 (Commands)
* 安装依赖: `pip install -r requirements.txt`
* 运行应用: `streamlit run app.py`