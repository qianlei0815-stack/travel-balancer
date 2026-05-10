"""
app.py —— 旅游端水大师（盲选需求收集系统）
一人一链 · 旅行 DNA 测验 · 管理员汇总

路由规则：
  无参数             → 欢迎页（创建旅行 / 输入邀请码）
  ?admin=true        → 管理员后台
  ?group_id=XXX&user_id=YYY → 成员游戏表单
"""

import streamlit as st
import json
import os
import sys
import secrets
import string
from pathlib import Path
from datetime import date, datetime

# ====================================================================
#  Windows pywin32 兼容性修复
# ====================================================================
_USER_SITE = (
    Path.home() / "AppData" / "Roaming" / "Python" / "Python312"
    / "site-packages"
)
_pywin32_dll_dir = _USER_SITE / "pywin32_system32"
if _pywin32_dll_dir.exists():
    try:
        os.add_dll_directory(str(_pywin32_dll_dir))
    except OSError:
        pass  # 某些 Windows 配置可能拒绝 add_dll_directory
for _rel in ("win32", "win32/lib", "Pythonwin"):
    _p = _USER_SITE / _rel
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
for _mod in ("_win32sysloader", "pywintypes"):
    try:
        __import__(_mod)
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

# 高德地图服务（地理编码 + 地图可视化）
try:
    from amap_service import (
        extract_per_day_places,
        build_day_routes,
        batch_geocode,
    )
    _has_amap = bool(os.getenv("AMAP_JS_API_KEY"))
except Exception:
    _has_amap = False

st.set_page_config(page_title="旅游端水大师", page_icon="🌍", layout="centered")

# ====================================================================
#  常量
# ====================================================================
DATA_DIR = Path("data")

MEMBER_FIELDS = ["name", "budget", "sleep_energy", "intensity_score", "wishlist", "is_private"]

BUDGET_OPTIONS = [
    "💰 省钱党：能省则省，追求性价比",
    "💰💰 适中派：该花就花，但不过度",
    "💰💰💰 宽裕派：追求品质体验，预算不限",
]

SLEEP_OPTIONS = [
    "🌅 早睡早起：晚11点前睡，早7点起，精力充沛",
    "🌗 正常作息：12点左右睡，8点左右起，中等体力",
    "🌙 夜猫子：凌晨后入睡，上午起床，夜间精力好",
]

_HAS_PILLS = hasattr(st, "pills")


# ====================================================================
#  数据层 — 按小组/用户隔离的 JSON 持久化
# ====================================================================

def generate_id(length: int = 8) -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def _group_path(group_id: str) -> Path:
    return DATA_DIR / group_id


def load_group(group_id: str) -> dict:
    path = _group_path(group_id) / "group.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_group(group_id: str, data: dict) -> None:
    path = _group_path(group_id) / "group.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_user_data(group_id: str, user_id: str) -> dict:
    """只读自己那份数据，绝不碰其他文件"""
    path = _group_path(group_id) / f"{user_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_user_data(group_id: str, user_id: str, data: dict) -> None:
    """只写自己那份数据，绝不碰其他文件"""
    path = _group_path(group_id) / f"{user_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_result(group_id: str) -> dict | None:
    path = _group_path(group_id) / "result.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_result(group_id: str, data: dict) -> None:
    path = _group_path(group_id) / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_group(group_id: str) -> None:
    import shutil
    path = _group_path(group_id)
    if path.exists():
        shutil.rmtree(path)


def _scan_members(group_id: str) -> dict:
    """
    扫描目录获取成员列表 —— 仅限 admin 页面调用（admin=true 时）。
    返回 {user_id: {"name": str, "status": str}}
    """
    members = {}
    path = _group_path(group_id)
    if not path.exists():
        return members
    for f in sorted(path.glob("*.json")):
        if f.name in ("group.json", "result.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("name", "").strip()
            if name:
                members[f.stem] = {"name": name, "status": data.get("status", "pending")}
        except (json.JSONDecodeError, OSError):
            continue
    return members


# ====================================================================
#  CSS
# ====================================================================

def _custom_css():
    st.markdown("""
    <style>
        .block-container { max-width: 680px; padding-top: 3rem !important; padding-bottom: 2rem !important; }
        [data-testid="stHeader"] { background: transparent; }
        .success-box {
            text-align: center; padding: 2rem 1rem;
            background: linear-gradient(135deg, #e8f5e9, #f1f8e9);
            border-radius: 16px; margin-bottom: 1.5rem;
        }
        .success-box h2 { color: #2e7d32; margin-bottom: 0.5rem; }
        .big-link {
            font-size: 1.1rem; font-weight: 700;
            background: #e3f2fd; padding: 0.5rem 1rem;
            border-radius: 8px; font-family: monospace; text-align: center;
        }
        .level-card {
            background: #f8f9fa; border-radius: 12px;
            padding: 1.2rem 1.5rem 0.8rem 1.5rem;
            margin-bottom: 0.8rem;
            border-left: 4px solid #ff6b6b;
        }
    </style>
    """, unsafe_allow_html=True)


# ====================================================================
#  页面：欢迎页
# ====================================================================

def show_welcome():
    """首页 —— 创建旅行 或 输入邀请码"""
    st.title("🌍 旅游端水大师")
    st.markdown("### 一场公平的旅行，从了解彼此开始")
    st.markdown("每个人悄悄写下自己的心愿，让 AI 帮你端平这碗水 🤝")

    st.markdown("")
    if st.button("🚀 **创建新旅行**", type="primary", use_container_width=True):
        gid = generate_id()
        save_group(gid, {
            "group_id": gid,
            "destination": "",
            "days": 3,
            "start_date": datetime.now().strftime("%Y-%m-%d"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        st.query_params["group_id"] = gid
        st.query_params["admin"] = "true"
        st.rerun()

    st.markdown("---")
    with st.expander("🔗 已有邀请链接？"):
        col1, col2 = st.columns(2)
        with col1:
            invite_gid = st.text_input("小组代码", placeholder="如：a3b2c1d8")
        with col2:
            invite_uid = st.text_input("成员代码", placeholder="如：x9y8z7w6")
        if st.button("加入旅行", use_container_width=True):
            if invite_gid.strip() and invite_uid.strip():
                st.query_params["group_id"] = invite_gid.strip()
                st.query_params["user_id"] = invite_uid.strip()
                st.rerun()
            else:
                st.error("请填写完整的小组代码和成员代码")


# ====================================================================
#  页面：游戏化表单（旅行 DNA 测验）
# ====================================================================

def show_game_form(group_id: str, user_id: str):
    """
    成员填写偏好的游戏界面。
    严守隔离：只读/写自己的 user data，不碰 group.json 和其他成员文件。
    """
    user_data = load_user_data(group_id, user_id)
    if not user_data or not user_data.get("name"):
        st.error("❌ 无效的成员链接，请联系发起人获取正确链接")
        if st.button("🏠 回到首页"):
            st.query_params.clear()
            st.rerun()
        return

    name = user_data["name"]
    is_submitted = user_data.get("status") == "completed"

    # 首次提交成功的庆祝动画
    if is_submitted and "balloon_shown" not in st.session_state:
        st.balloons()
        st.session_state.balloon_shown = True

    # ---- 每个 widget 的唯一 key ----
    K = {
        "intensity": f"int_{user_id}",
        "budget":    f"bud_{user_id}",
        "sleep":     f"slp_{user_id}",
        "wishlist":  f"wsh_{user_id}",
        "private":   f"prv_{user_id}",
    }

    # ---- 从已有数据或默认值预填 session_state（仅在首次加载时） ----
    if K["intensity"] not in st.session_state:
        v = user_data.get("intensity_score", 5)
        st.session_state[K["intensity"]] = v if isinstance(v, int) else 5
    if K["budget"] not in st.session_state:
        v = user_data.get("budget")
        st.session_state[K["budget"]] = v if v in BUDGET_OPTIONS else None
    if K["sleep"] not in st.session_state:
        v = user_data.get("sleep_energy")
        st.session_state[K["sleep"]] = v if v in SLEEP_OPTIONS else None
    if K["wishlist"] not in st.session_state:
        st.session_state[K["wishlist"]] = user_data.get("wishlist", "")
    if K["private"] not in st.session_state:
        st.session_state[K["private"]] = user_data.get("is_private", False)

    # ---- 进度条 ----
    vals = [st.session_state[k] for k in (K["intensity"], K["budget"], K["sleep"], K["wishlist"])]
    filled = sum(1 for v in vals if v)
    total = len(vals)

    st.markdown(f"### 🧬 **{name}** 的旅行 DNA 测验")
    st.progress(filled / total)
    st.caption(f"已完成 **{filled} / {total}** 关")

    # ---- 已提交横幅 ----
    if is_submitted:
        st.markdown(
            '<div class="success-box">'
            '<h2>🎉 提交成功！</h2>'
            '<p style="font-size:1.05rem;">🔒 你的旅行 DNA 已加密上传！<br>'
            '请等待其他小伙伴完成，<strong>端水大师</strong>正在后台计算最优解...</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ---- 查看行程入口 ----
        result = load_result(group_id)
        if result:
            st.markdown("---")
            st.markdown("### 🎯 行程已出炉！")
            if st.button("🗺️ **查看我的行程**", type="primary", use_container_width=True):
                st.session_state[f"show_result_{user_id}"] = True
            if st.session_state.get(f"show_result_{user_id}"):
                group = load_group(group_id)
                _show_result(result, group)
        else:
            st.markdown(
                '<div style="text-align:center;padding:1rem;background:#fef3e2;'
                'border-radius:12px;margin-top:0.5rem;">'
                '<p style="font-size:1rem;color:#b85c00;">⏳ 行程计算中……</p>'
                '<p style="font-size:0.85rem;color:#999;">'
                '发起人正在协调所有成员的偏好，稍后再来看看吧</p>'
                '</div>',
                unsafe_allow_html=True,
            )

    # ==================== 第一关：体力挑战 ====================
    st.markdown("---")
    st.markdown("### 🏃 第一关：体力挑战")
    st.markdown("<small>你愿意为这次旅行付出多少体力？</small>", unsafe_allow_html=True)

    c1, c_slider, c3 = st.columns([1.2, 6, 1.2])
    with c1:
        st.markdown("##### ☕\n躺平")
    with c_slider:
        st.select_slider(
            "体力值",
            options=list(range(1, 11)),
            key=K["intensity"],
            label_visibility="collapsed",
            disabled=is_submitted,
        )
        cur = st.session_state[K["intensity"]]
        label = (
            "🛋️ 绝对躺平" if cur <= 2 else
            "🚶 悠闲散步" if cur <= 4 else
            "⚖️ 适中平衡" if cur <= 6 else
            "🏃 精力充沛" if cur <= 8 else
            "🚀 极限特种兵"
        )
        st.markdown(f"<div style='text-align:center;color:#666;'>{label}</div>",
                    unsafe_allow_html=True)
    with c3:
        st.markdown("##### 🏃\n特种兵")

    # ==================== 第二关：消费画像 ====================
    st.markdown("---")
    st.markdown("### 💰 第二关：消费画像")
    st.markdown("<small>你的旅行消费风格是？</small>", unsafe_allow_html=True)

    if _HAS_PILLS:
        st.pills("预算偏好", options=BUDGET_OPTIONS, key=K["budget"],
                  disabled=is_submitted, label_visibility="collapsed")
    else:
        st.radio("预算偏好", options=BUDGET_OPTIONS, key=K["budget"],
                  horizontal=True, disabled=is_submitted, label_visibility="collapsed")

    # ==================== 第三关：作息密码 ====================
    st.markdown("---")
    st.markdown("### 🌙 第三关：作息密码")
    st.markdown("<small>你的生物钟是哪种？</small>", unsafe_allow_html=True)

    if _HAS_PILLS:
        st.pills("作息选择", options=SLEEP_OPTIONS, key=K["sleep"],
                  disabled=is_submitted, label_visibility="collapsed")
    else:
        st.radio("作息选择", options=SLEEP_OPTIONS, key=K["sleep"],
                  horizontal=True, disabled=is_submitted, label_visibility="collapsed")

    # ==================== 第四关：心愿盲盒 ====================
    st.markdown("---")
    st.markdown("### 🎁 第四关：心愿盲盒")
    st.markdown("<small>写下你的秘密心愿，系统会替你保密，只在最终平衡方案中巧妙体现。</small>",
                unsafe_allow_html=True)

    st.text_area(
        "心愿单与避雷指南",
        placeholder="例如：我一定要去看熊猫、想吃地道的火锅……\n"
                    "绝对不爬山！不吃香菜！不坐夜车！\n"
                    "你的秘密，只有端水大师知道 😎",
        key=K["wishlist"],
        disabled=is_submitted,
        height=120,
        label_visibility="collapsed",
    )

    st.checkbox("🔒 保密此心愿（在最终攻略中不公开归属信息）",
                key=K["private"], disabled=is_submitted)

    # ==================== 提交 ====================
    st.markdown("---")
    all_filled = all([
        st.session_state[K["budget"]],
        st.session_state[K["sleep"]],
        st.session_state[K["wishlist"]],
    ])
    # intensity 的 select_slider 始终有值，无需校验

    if is_submitted:
        st.success("✅ 已提交。如需修改，点击下方按钮重新编辑")
        if st.button("✏️ **重新编辑**", use_container_width=True):
            user_data["status"] = "pending"
            save_user_data(group_id, user_id, user_data)
            if "balloon_shown" in st.session_state:
                del st.session_state.balloon_shown
            st.rerun()
    elif all_filled:
        if st.button("🎯 **提交我的旅行 DNA**", type="primary", use_container_width=True):
            payload = {
                "name": name,
                "intensity_score": st.session_state[K["intensity"]],
                "budget": st.session_state[K["budget"]],
                "sleep_energy": st.session_state[K["sleep"]],
                "wishlist": st.session_state[K["wishlist"]],
                "is_private": st.session_state[K["private"]],
                "status": "completed",
                "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_user_data(group_id, user_id, payload)
            st.rerun()
    else:
        missing = []
        if not st.session_state[K["budget"]]:    missing.append("💰 消费画像")
        if not st.session_state[K["sleep"]]:     missing.append("🌙 作息密码")
        if not st.session_state[K["wishlist"]]:  missing.append("🎁 心愿盲盒")
        st.info(f"还差 **{len(missing)} 关**：{'、'.join(missing)}，完成后即可提交")
        st.button("🎯 **提交我的旅行 DNA**", type="primary", use_container_width=True,
                  disabled=True)


# ====================================================================
#  页面：管理员后台
# ====================================================================

def show_admin(group_id: str):
    """管理员视图 —— 设置行程 / 加人 / 监控 / 计算"""
    group = load_group(group_id)

    if not group:
        st.error("❌ 小组不存在")
        if st.button("🏠 回到首页"):
            st.query_params.clear()
            st.rerun()
        return

    st.title("🌍 端水大师 · 管理后台")
    st.caption(f"小组代码：`{group_id}`")

    # ----- 行程设置 -----
    st.markdown("#### 📍 行程设置")
    dest = st.text_input("目的地", value=group.get("destination", ""),
                         placeholder="例如：成都、东京、巴黎")
    days = st.number_input("天数", min_value=1, max_value=30,
                           value=group.get("days", 3))

    # 出发日期（带默认值）
    raw_date = group.get("start_date", "")
    if not raw_date:
        raw_date = date.today()
    else:
        try:
            raw_date = date.fromisoformat(raw_date)
        except (ValueError, TypeError):
            raw_date = date.today()
    start_date = st.date_input("出发日期", value=raw_date)

    if (dest != group.get("destination")
            or days != group.get("days")
            or str(start_date) != group.get("start_date", "")):
        group["destination"] = dest
        group["days"] = days
        group["start_date"] = str(start_date)
        save_group(group_id, group)

    # ----- 邀请体系 -----
    st.markdown("---")
    st.markdown("#### 📎 邀请成员")
    st.info("添加成员后，将每位成员的专属链接发给他们即可（一人一链，彼此隔离）")

    # 自动检测部署域名，支持环境变量 PUBLIC_URL 覆盖
    def _base_url() -> str:
        env = os.getenv("PUBLIC_URL", "").strip()
        if env:
            return env.rstrip("/")
        try:
            origin = st.context.headers.get("origin", "")
            if origin:
                return origin.rstrip("/")
        except Exception:
            pass
        return "http://localhost:8501"

    base_url = _base_url()

    members = _scan_members(group_id)
    all_completed = bool(members)

    # 已添加的成员列表
    if members:
        st.markdown("**👥 已添加的成员：**")
        for uid, m in members.items():
            full_link = f"{base_url}/?group_id={group_id}&user_id={uid}"
            if m["status"] == "completed":
                st.success(f"✅ **{m['name']}** — 已提交")
                with st.expander(f"🔗 {m['name']} 的专属链接"):
                    st.markdown(f"[{full_link}]({full_link})")
                    st.code(full_link)
            else:
                st.warning(f"⏳ **{m['name']}** — 未提交")
                with st.expander(f"🔗 {m['name']} 的专属链接"):
                    st.markdown(f"[{full_link}]({full_link})")
                    st.code(full_link)
                all_completed = False
        st.caption(f"**{sum(1 for m in members.values() if m['status']=='completed')} / {len(members)}** 人已完成")
    else:
        st.info("⏳ 还没有添加成员，在下方添加第一位成员吧")

    # 添加新成员
    with st.expander("➕ 添加新成员", expanded=not bool(members)):
        new_name = st.text_input("成员名字", key="admin_new_name",
                                 placeholder="例如：晓明")
        if st.button("生成邀请链接", use_container_width=True):
            name = new_name.strip()
            if not name:
                st.error("请输入成员名字")
            elif any(m["name"] == name for m in members.values()):
                st.warning(f"『{name}』已存在，请勿重复添加")
            else:
                uid = generate_id()
                save_user_data(group_id, uid, {"name": name})
                st.success(f"✅ 已添加 **{name}**，专属链接已生成")
                st.rerun()

    # ----- 计算结果 -----
    st.markdown("---")
    st.markdown("#### 🏁 最终行程")
    has_api = bool(os.getenv("LLM_API_KEY"))
    if not has_api:
        st.warning("⚠️ 请在 `.env` 文件中设置 `LLM_API_KEY`")

    result = load_result(group_id)
    if result:
        _show_result(result, group)
        if st.button("🔄 **重新计算**", use_container_width=True):
            save_result(group_id, None)
            st.rerun()
    else:
        ready = all_completed and bool(members) and has_api and bool(dest.strip())
        if ready:
            if st.button("✨ **开始计算最终行程**", type="primary", use_container_width=True):
                with st.spinner("🧠 多智能体协同中……冲突分析 → 双轨规划 → 端水润色..."):
                    try:
                        import crew_logic
                        res = crew_logic.run_from_group(group_id)
                        save_result(group_id, res)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 计算失败：{e}")
        else:
            reason = (
                "⚠️ 等待所有成员提交" if not all_completed else
                "⚠️ 暂无成员" if not members else
                "⚠️ 请填写目的地" if not dest.strip() else
                "⚠️ 请设置 LLM_API_KEY")
            st.info(reason)

    # ----- 危险操作 -----
    with st.expander("⚙️ 管理操作"):
        if st.button("🗑️ **删除此小组**", type="secondary", use_container_width=True):
            delete_group(group_id)
            st.query_params.clear()
            st.rerun()


# ====================================================================
#  结果展示组件
# ====================================================================

# ====================================================================
#  高德地图可视化组件
# ====================================================================

_AMAP_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
    "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
]

_AMAP_HTML_TPL = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>行程路线 · {title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; }}
  #map {{ width: 100%; height: 520px; border-radius: 8px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 6px 12px; padding: 8px 12px;
             background: #fff; border-radius: 6px; margin: 6px 0; font-size: 13px; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .tab-bar {{ display: flex; gap: 4px; margin-bottom: 6px; }}
  .tab-btn {{ padding: 4px 14px; border: 1px solid #ddd; border-radius: 4px;
              background: #fff; cursor: pointer; font-size: 13px; }}
  .tab-btn.active {{ background: #4A90D9; color: #fff; border-color: #4A90D9; }}
</style>
</head>
<body>
<div class="tab-bar" id="tabBar"></div>
<div class="legend" id="legend"></div>
<div id="map"></div>

<script src="https://webapi.amap.com/maps?v=2.0&key={api_key}"></script>
<script>
(function() {{
  var map = new AMap.Map('map', {{
    zoom: 12,
    center: [{center_lng}, {center_lat}],
    resizeEnable: true,
    mapStyle: 'amap://styles/light'
  }});

  var allData = {route_json};
  var currentDay = 1;
  var overlays = [];

  function getDayColor(day) {{
    var colors = {color_json};
    return colors[(day - 1) % colors.length];
  }}

  function clearMap() {{
    overlays.forEach(function(o) {{ map.remove(o); }});
    overlays = [];
  }}

  function renderDay(day) {{
    clearMap();
    currentDay = day;
    var dayData = allData[String(day)];
    if (!dayData || dayData.length === 0) return;

    var color = getDayColor(day);
    var pts = [];

    // Markers + polylines
    dayData.forEach(function(poi, idx) {{
      var pos = [poi.lng, poi.lat];
      pts.push(pos);

      var labelText = String(idx + 1);
      var marker = new AMap.Marker({{
        position: pos,
        title: poi.name,
        label: {{ content: labelText, direction: 'center',
                   offset: new AMap.Pixel(-6, -6),
                   style: {{ background: color, color: '#fff', fontSize: '11px',
                             width: '20px', height: '20px', lineHeight: '20px',
                             border: '2px solid #fff', borderRadius: '50%',
                             textAlign: 'center', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} }}
      }});

      var infoContent = '<div style="font-size:13px;max-width:220px">' +
        '<b>' + poi.name + '</b><br>' +
        (poi.dist_km > 0 ? '🚗 距上一站 ' + poi.dist_km + ' km · ' +
          (poi.duration_min > 0 ? '⏱ ' + Math.round(poi.duration_min) + ' 分钟<br>' : '<br>') : '') +
        (poi.cluster ? '<span style="color:#999">📍 区域 ' + poi.cluster + '</span>' : '') +
        '</div>';

      marker.on('click', function() {{
        var info = new AMap.InfoWindow({{ content: infoContent, offset: new AMap.Pixel(0, -30) }});
        info.open(map, pos);
      }});

      map.add(marker);
      overlays.push(marker);

      // Cluster info label on map
      if (idx === 0 && poi.cluster) {{
        var text = new AMap.Text({{
          text: '📍 区域 ' + poi.cluster,
          position: pos,
          offset: new AMap.Pixel(0, 32),
          style: {{ background: 'rgba(255,255,255,0.9)', borderRadius: '4px',
                    padding: '2px 8px', fontSize: '11px', color: '#666' }}
        }});
        map.add(text);
        overlays.push(text);
      }}
    }});

    // Polyline connecting all points
    if (pts.length > 1) {{
      var polyline = new AMap.Polyline({{
        path: pts,
        strokeColor: color,
        strokeWeight: 3,
        strokeOpacity: 0.8,
        lineJoin: 'round',
        strokeStyle: 'dashed',
        showDir: true
      }});
      map.add(polyline);
      overlays.push(polyline);
    }}

    // Fit bounds
    if (pts.length > 0) {{
      map.setFitView(null, false, [40, 40, 40, 40]);
    }}

    // Update tabs
    document.querySelectorAll('.tab-btn').forEach(function(btn) {{
      btn.classList.toggle('active', String(btn.dataset.day) === String(day));
    }});
  }}

  // Build tab bar
  var days = Object.keys(allData).sort(function(a,b) {{ return a - b; }});
  var tabHtml = '';
  days.forEach(function(d) {{
    tabHtml += '<button class="tab-btn" data-day="' + d + '" onclick="renderDay(' + d + ')">Day ' + d + '</button>';
  }});
  document.getElementById('tabBar').innerHTML = tabHtml;

  // Build legend
  var legendHtml = days.map(function(d) {{
    return '<span class="legend-item"><span class="legend-dot" style="background:' + getDayColor(d) + '"></span> Day ' + d + '</span>';
  }}).join('');
  document.getElementById('legend').innerHTML = legendHtml;

  // Render first day
  if (days.length > 0) renderDay(parseInt(days[0]));
}})();
</script>
</body>
</html>
"""


def _render_route_map(plan_text: str, destination: str, days: int,
                      title: str) -> tuple[str | None, str]:
    """生成 Amap 地图 HTML

    返回 (html_string_or_None, error_or_empty_string)
    """
    if not _has_amap:
        return None, "未检测到 AMAP_JS_API_KEY，请在 .env 中设置"
    amap_key = os.getenv("AMAP_JS_API_KEY", "")
    if not amap_key:
        return None, "AMAP_JS_API_KEY 为空，请在 .env 中配置"
    web_key = os.getenv("AMAP_API_KEY", "")
    if not web_key:
        return None, "AMAP_API_KEY 为空，地理编码无法工作，请在 .env 中配置"

    ndays = max(days, 1)
    try:
        day_places = extract_per_day_places(plan_text, ndays)
        if not day_places:
            return None, "未能从行程文本中提取到景点名称（需要 **加粗** 或 【书名号】 标注）"

        route_data = build_day_routes(day_places, destination)
        # route_data 可能是 {1: [], 2: []}（所有景點編碼失敗）
        has_any_poi = any(pts for pts in route_data.values())
        if not route_data or not has_any_poi:
            return (None,
                "景点地理编码失败，请检查 AMAP_API_KEY：\n"
                f"1. 当前值: {web_key[:8]}...\n"
                "2. 是否开通了「Web 服务」API（不是 JSAPI）\n"
                "3. 网络能否访问 restapi.amap.com")

        # 目的地地理编码获取中心点
        try:
            center = batch_geocode([destination], destination)[0]
            clng, clat = center["lng"], center["lat"]
        except Exception:
            # 如目的地无法解析，用第一个 POI 坐标
            for day in sorted(route_data.keys()):
                if route_data[day]:
                    clng = route_data[day][0]["lng"]
                    clat = route_data[day][0]["lat"]
                    break
            else:
                # route_data 不为空但每个 day 都是空列表 → 所有景点编码全失败
                return (None,
                    "所有景点地理编码均失败。请检查：\n"
                    f"1. AMAP_API_KEY 是否有效（当前值: {web_key[:6]}...）\n"
                    "2. 是否开通了「Web 服务」API（不是 JSAPI）\n"
                    "3. 网络能否访问 restapi.amap.com")

        import json as _json
        route_json = _json.dumps(route_data, ensure_ascii=False)
        color_json = _json.dumps(_AMAP_COLORS)

        html = _AMAP_HTML_TPL.format(
            title=title,
            api_key=amap_key,
            center_lng=clng,
            center_lat=clat,
            route_json=route_json,
            color_json=color_json,
        )
        return html, ""
    except Exception as e:
        return None, f"地图渲染异常: {e}"


def _show_result(result: dict, group: dict):
    """渲染 AB 双方案或单人方案"""
    n = len(_scan_members(group.get("group_id", "")))
    tag = "单人 · 个人定制" if n == 1 else f"{n} 人 · 平衡协调"
    st.markdown(f"**📍 {group.get('destination','')} · {group.get('days',3)} 天 · {tag}**")

    if isinstance(result, str):
        st.markdown(result)
        return

    dest = group.get("destination", "")
    ndays = group.get("days", 3)

    if n == 1 or not result.get("plan_b"):
        st.markdown(result.get("plan_a", ""))
        # 单人地图
        map_html, map_err = _render_route_map(
            result.get("plan_a", ""), dest, ndays, "个人定制行程"
        )
        if map_html:
            st.markdown("#### 🗺️ 路线地图")
            st.caption("📍 各景点按 Day 分色，点击标记查看详情和交通耗时")
            st.components.v1.html(map_html, height=600)
        elif map_err:
            st.markdown("#### 🗺️ 路线地图")
            st.info(f"地图暂不可用：{map_err}")
    else:
        st.info(
            "💡 由于团队成员的旅行节奏存在差异，"
            "**端水大师**准备了两套方案，请大家投票选出最心仪的一套！"
        )
        ta, tb = st.tabs(["方案 A：集体妥协 🤝", "方案 B：动态分头 🏃/☕"])
        with ta:
            plan_a_full = (
                (result.get("intro", "") + "\n\n---\n\n")
                if result.get("intro") else ""
            ) + result.get("plan_a", "")
            st.markdown(plan_a_full)
        with tb:
            plan_b_full = (
                (result.get("intro", "") + "\n\n---\n\n")
                if result.get("intro") else ""
            ) + result.get("plan_b", "")
            st.markdown(plan_b_full)

        # 双方案地图对比
        map_a, map_a_err = _render_route_map(
            result.get("plan_a", ""), dest, ndays, "方案 A：集体妥协"
        )
        map_b, map_b_err = _render_route_map(
            result.get("plan_b", ""), dest, ndays, "方案 B：动态分头"
        )
        if map_a or map_b:
            st.markdown("#### 🗺️ 路线地图对比")
            ma, mb = st.tabs(["🗺️ 方案 A 地图", "🗺️ 方案 B 地图"])
            with ma:
                if map_a:
                    st.caption("📍 各景点按 Day 分色，点击标记查看详情和交通耗时")
                    st.components.v1.html(map_a, height=600)
                else:
                    st.info(f"方案 A 地图暂不可用：{map_a_err}")
            with mb:
                if map_b:
                    st.caption("📍 各景点按 Day 分色，点击标记查看详情和交通耗时")
                    st.components.v1.html(map_b, height=600)
                else:
                    st.info(f"方案 B 地图暂不可用：{map_b_err}")
        elif map_a_err or map_b_err:
            st.markdown("#### 🗺️ 路线地图对比")
            st.info(f"地图暂不可用：{map_a_err or map_b_err}")


# ====================================================================
#  路由入口
# ====================================================================

def main():
    _custom_css()

    params = st.query_params
    group_id = params.get("group_id")
    user_id = params.get("user_id")
    is_admin = params.get("admin", "").lower() == "true"

    if is_admin:
        show_admin(group_id)
    elif user_id:
        show_game_form(group_id, user_id)
    else:
        show_welcome()

    st.markdown("---")
    st.caption("Powered by 🤖 Multi-Agent System · 旅游端水大师")


if __name__ == "__main__":
    main()
