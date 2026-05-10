"""
Crew 编排模块 —— 将 Agents 和 Tasks 组装成 Crew 并执行
支持直接运行：python crew_logic.py

单/多人模式分流：
  - 单人模式（len(users)==1）：跳过谈判，直接由个人管家定制攻略
  - 多人模式（len(users)>=2）：需求分析师 → 行程规划师 → 导游沟通者
    - 多人模式强制输出 AB 双方案（方案 A 分头行动 / 方案 B 折中妥协）
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ====================================================================
#  Windows pywin32 兼容性修复（与 app.py 中的修复保持一致）
# ====================================================================
_USER_SITE = Path.home() / "AppData" / "Roaming" / "Python" / "Python312" / "site-packages"
_pywin32_dll_dir = _USER_SITE / "pywin32_system32"
if _pywin32_dll_dir.exists():
    try:
        os.add_dll_directory(str(_pywin32_dll_dir))
    except OSError:
        pass
for _rel in ("win32", "win32/lib", "Pythonwin"):
    _p = _USER_SITE / _rel
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
for _mod in ("_win32sysloader", "pywintypes"):
    try:
        __import__(_mod)
    except Exception:
        pass

from crewai import Crew, Process  # noqa: E402

from agents import (  # noqa: E402
    create_llm,
    create_analyst,
    create_planner,
    create_communicator,
    create_personal_concierge,
)

# DuckDuckGo 搜索工具（零门槛，无需 API Key）
try:
    from langchain_community.tools import DuckDuckGoSearchRun
    _search_tool = DuckDuckGoSearchRun()
except Exception:
    _search_tool = None
from tasks import (  # noqa: E402
    create_analysis_task,
    create_planning_task,
    create_communication_task,
    create_concierge_task,
)

# 高德地图服务（天气预取 + 地理编码）
try:
    from amap_service import format_weather_summary
    _has_amap = True
except Exception:
    _has_amap = False


def _fetch_weather(destination: str) -> str:
    """预取目的地天气预报，返回文本摘要（失败时返回空字符串）"""
    if not _has_amap or not destination.strip():
        return ""
    try:
        return format_weather_summary(destination)
    except Exception:
        return ""


def check_api_key() -> str | None:
    """检查大模型 API 密钥是否配置，返回 None 或错误信息"""
    key = os.getenv("LLM_API_KEY")
    if not key:
        return "未设置 LLM_API_KEY 环境变量。请在终端执行：\n\n  set LLM_API_KEY=sk-xxxx\n\n或通过系统环境变量配置。"
    return None


# ====================================================================
#  数据注入模块 —— 从 group 目录加载所有成员数据
# ====================================================================

_MEMBER_FIELDS = ["name", "budget", "sleep_energy", "intensity_score", "wishlist", "is_private"]


def load_group_data(group_id: str) -> dict:
    """
    遍历 group 目录下所有 user JSON，组装结构化上下文。

    参数:
        group_id: 小组标识

    返回:
        {"users": [...], "destination": "...", "days": N}
        如果目录或数据不存在，返回空结构。
    """
    group_path = Path("data") / group_id
    group_file = group_path / "group.json"

    if not group_file.exists():
        return {"users": [], "destination": "", "days": 3}

    try:
        group = json.loads(group_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"users": [], "destination": "", "days": 3}

    destination = group.get("destination", "")
    days = group.get("days", 3)
    users = []

    for f in sorted(group_path.glob("*.json")):
        if f.name in ("group.json", "result.json"):
            continue
        try:
            user_data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if user_data.get("status") == "completed" and user_data.get("name", "").strip():
            users.append({k: user_data.get(k, "") for k in _MEMBER_FIELDS})

    return {"users": users, "destination": destination, "days": days}


def parse_ab_plans(raw: str) -> dict:
    """
    从 LLM 输出中解析方案 A 和方案 B。

    LLM 输出格式预期：
      (共享开篇...)
      ## 方案 A：集体妥协路线
      (方案 A 内容...)
      ## 方案 B：动态分头路线
      (方案 B 内容...)

    返回 dict: {"intro": "...", "plan_a": "...", "plan_b": "..."}
    如果解析失败，plan_b 为空字符串，plan_a 为全文。
    """
    # 尝试按方案 A 标题分割
    parts = re.split(r'^## 方案 A', raw, flags=re.MULTILINE)
    if len(parts) >= 2:
        intro = parts[0].strip()
        rest = parts[1]
        # 再从剩余部分按方案 B 标题分割
        rest_parts = re.split(r'^## 方案 B', rest, flags=re.MULTILINE)
        if len(rest_parts) >= 2:
            plan_a = rest_parts[0].strip()
            plan_b = rest_parts[1].strip()
            return {"intro": intro, "plan_a": plan_a, "plan_b": plan_b}

    # 解析失败：返回全文作为方案 A
    return {"intro": "", "plan_a": raw.strip(), "plan_b": ""}


def run_multi(users: list, destination: str, days: int) -> dict:
    """
    多人模式：需求分析师 → 行程规划师（AB 双方案）→ 导游沟通者（润色双方案）

    参数:
        users: 成员列表
        destination: 目的地
        days: 旅行天数

    返回:
        dict: {"intro": "...", "plan_a": "...", "plan_b": "..."}
    """
    llm = create_llm()
    analyst = create_analyst(llm)
    planner = create_planner(llm, tools=[_search_tool] if _search_tool else None)
    communicator = create_communicator(llm)

    preferences_json = json.dumps(users, ensure_ascii=False, indent=2)
    weather_ctx = _fetch_weather(destination)

    task1 = create_analysis_task(analyst, preferences_json, destination, days)
    task2 = create_planning_task(planner, task1, destination, days,
                                 weather_context=weather_ctx)
    task3 = create_communication_task(communicator, task2, destination, days,
                                      weather_context=weather_ctx)

    crew = Crew(
        agents=[analyst, planner, communicator],
        tasks=[task1, task2, task3],
        process=Process.sequential,
        verbose=True,
    )
    result = str(crew.kickoff())
    return parse_ab_plans(result)


def run_single(users: list, destination: str, days: int) -> str:
    """单人模式：个人管家 → 导游沟通者（返回普通文本）"""
    llm = create_llm()
    concierge = create_personal_concierge(llm)
    communicator = create_communicator(llm)

    preferences_json = json.dumps(users, ensure_ascii=False, indent=2)
    weather_ctx = _fetch_weather(destination)

    task1 = create_concierge_task(concierge, preferences_json, destination, days,
                                   weather_context=weather_ctx)
    task2 = create_communication_task(communicator, task1, destination, days,
                                      is_single_mode=True,
                                      weather_context=weather_ctx)

    crew = Crew(
        agents=[concierge, communicator],
        tasks=[task1, task2],
        process=Process.sequential,
        verbose=True,
    )
    return str(crew.kickoff())


def run(users: list, destination: str, days: int) -> dict:
    """
    智能分流入口。
    - 1 人 → run_single（个人管家），返回 {"plan_a": "攻略"}
    - 多人 → run_multi（AB 双方案），返回 {"intro": "...", "plan_a": "...", "plan_b": "..."}
    """
    if len(users) == 1:
        result = run_single(users, destination, days)
        return {"plan_a": result}
    return run_multi(users, destination, days)


def run_from_group(group_id: str) -> dict:
    """
    从 group_id 出发，加载所有成员数据，执行完整的多智能体流程。

    这是 Streamlit 管理后台的推荐入口——无需在 app.py 中手动组装用户数据。

    返回:
        {"intro": "...", "plan_a": "...", "plan_b": "..."}
        如果数据不足，返回含错误信息的结构。
    """
    data = load_group_data(group_id)
    users = data["users"]
    destination = data["destination"]
    days = data["days"]

    if not users:
        return {"intro": "", "plan_a": "暂无已提交的成员数据，请等待成员完成填写。", "plan_b": ""}
    if not destination.strip():
        return {"intro": "", "plan_a": "请先在管理后台设置目的地。", "plan_b": ""}

    return run(users, destination, days)


# ====================================================================
#  命令行入口（仅用于测试）
# ====================================================================
if __name__ == "__main__":
    group_id = os.getenv("TEST_GROUP_ID", "")
    if group_id:
        # 基于 group_id 加载（推荐）
        print(f"📂 加载小组: {group_id}")
        result = run_from_group(group_id)
    else:
        # 兼容旧方式：从文件加载
        data_path = os.getenv("PREFERENCES_FILE", "data/preferences.json")
        if not os.path.exists(data_path):
            fallback = "data/sample_preferences.json"
            print(f"⚠️  {data_path} 不存在，使用示例数据: {fallback}")
            data_path = fallback

        try:
            with open(data_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            if isinstance(raw, dict) and "members" in raw:
                users = raw["members"]
                dest = raw.get("destination", "未知目的地")
                ndays = raw.get("days", 3)
            elif isinstance(raw, dict):
                users = list(raw.values())
                dest = os.getenv("TEST_DESTINATION", "成都")
                ndays = int(os.getenv("TEST_DAYS", "3"))
            else:
                users = raw
                dest = os.getenv("TEST_DESTINATION", "成都")
                ndays = int(os.getenv("TEST_DAYS", "3"))

            result = run(users, dest, ndays)
        except (ValueError, FileNotFoundError, KeyError) as e:
            print(f"❌  错误: {e}")
            sys.exit(1)

    # 输出结果
    n_members = 0
    if result.get("plan_b"):
        combined = ""
        if result.get("intro"):
            combined += result["intro"] + "\n\n"
        combined += "## 方案 A：集体妥协路线\n\n" + result["plan_a"]
        combined += "\n\n## 方案 B：动态分头路线\n\n" + result["plan_b"]

        output_path = "data/final_guide.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(combined)
        print(f"\n✅  双方案攻略已保存至: {output_path}")
        print(f"   📄 方案 A 约 {len(result['plan_a'])} 字符")
        print(f"   📄 方案 B 约 {len(result['plan_b'])} 字符")
    else:
        output_path = "data/final_guide.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.get("plan_a", ""))
        print(f"\n✅  攻略已保存至: {output_path}")
        print(f"   📄 约 {len(result.get('plan_a', ''))} 字符")
