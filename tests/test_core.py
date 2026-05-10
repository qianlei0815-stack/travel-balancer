"""
旅游端水大师 —— 核心逻辑测试
运行: python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from amap_service import (
    extract_place_names,
    extract_per_day_places,
    cluster_by_distance,
    _haversine_km,
)
from crew_logic import (
    parse_ab_plans,
    load_group_data,
    _MEMBER_FIELDS,
)


# ====================================================================
#  1. 景点名称提取
# ====================================================================

class TestExtractPlaceNames:
    """从 Markdown 行程文本中提取景点名称"""

    def test_bold_pattern(self):
        """**加粗** 模式"""
        text = "上午前往 **熊猫基地** 看花花，下午去 **宽窄巷子** 逛街"
        assert extract_place_names(text) == ["熊猫基地", "宽窄巷子"]

    def test_book_title_pattern(self):
        """【书名号】 模式"""
        text = "推荐景点：【都江堰】、【青城山】"
        assert extract_place_names(text) == ["都江堰", "青城山"]

    def test_angle_bracket_pattern(self):
        """《》模式"""
        text = "参观《三星堆博物馆》，游览《锦里》"
        assert extract_place_names(text) == ["三星堆博物馆", "锦里"]

    def test_mixed_patterns(self):
        """混合多种格式"""
        text = (
            "Day 1:\n"
            "- **熊猫基地** - 看大熊猫\n"
            "- 下午前往【宽窄巷子】\n"
            "- 晚上逛《锦里》\n"
        )
        assert extract_place_names(text) == ["熊猫基地", "宽窄巷子", "锦里"]

    def test_no_duplicates(self):
        """同名景点只提取一次"""
        text = "**熊猫基地** 很棒，一定要再去 **熊猫基地**"
        assert extract_place_names(text) == ["熊猫基地"]

    def test_skip_non_place_keywords(self):
        """过滤非景点关键词"""
        text = "**推荐理由** 这里很棒，**交通方式** 步行"
        names = extract_place_names(text)
        assert "推荐理由" not in names
        assert "交通方式" not in names

    def test_empty_text(self):
        """空文本"""
        assert extract_place_names("") == []
        assert extract_place_names("   ") == []

    def test_no_match(self):
        """无匹配格式"""
        text = "今天去熊猫基地玩，明天去宽窄巷子"  # 没有加粗/书名号
        assert extract_place_names(text) == []

    def test_fallback_broad_pattern(self):
        """宽泛模式回退（当严格模式无结果时）"""
        # 只有 **加粗** 没有前缀动词
        text = "**武侯祠** - 历史遗迹\n**杜甫草堂** - 诗人故居"
        names = extract_place_names(text)
        assert "武侯祠" in names
        assert "杜甫草堂" in names


class TestExtractPerDayPlaces:
    """按天提取景点"""

    def test_basic_days(self):
        text = (
            "### Day 1\n"
            "- **熊猫基地**\n"
            "- **宽窄巷子**\n"
            "### Day 2\n"
            "- **都江堰**\n"
        )
        result = extract_per_day_places(text, 3)
        assert result[1] == ["熊猫基地", "宽窄巷子"]
        assert result[2] == ["都江堰"]
        assert 3 not in result  # Day 3 无内容

    def test_chinese_day_format(self):
        """中文 '第 N 天' 格式"""
        text = (
            "第 1 天\n"
            "- **熊猫基地**\n"
            "第 2 天\n"
            "- **都江堰**\n"
        )
        result = extract_per_day_places(text, 3)
        assert result[1] == ["熊猫基地"]
        assert result[2] == ["都江堰"]

    def test_out_of_range_day(self):
        """超过 total_days 的天数应忽略"""
        text = (
            "### Day 1\n**熊猫基地**\n"
            "### Day 99\n**外星景点**\n"
        )
        result = extract_per_day_places(text, 3)
        assert 1 in result
        assert 99 not in result


# ====================================================================
#  2. 地理距离与聚类
# ====================================================================

class TestHaversine:
    """Haversine 距离计算"""

    def test_same_point(self):
        """同一点距离为 0"""
        p = {"lng": 104.06, "lat": 30.67}
        assert _haversine_km(p, p) == 0.0

    def test_chengdu_to_chongqing(self):
        """成都 → 重庆 约 270km"""
        chengdu = {"lng": 104.06, "lat": 30.67}
        chongqing = {"lng": 106.55, "lat": 29.57}
        dist = _haversine_km(chengdu, chongqing)
        assert 260 <= dist <= 280  # 允许一定误差

    def test_small_distance(self):
        """近距离（宽窄巷子 → 人民公园 ~1km）"""
        kuanzhai = {"lng": 104.055, "lat": 30.665}
        renmin = {"lng": 104.063, "lat": 30.659}
        dist = _haversine_km(kuanzhai, renmin)
        assert 0.5 <= dist <= 2.0


class TestClusterByDistance:
    """地理聚类"""

    def test_two_clusters(self):
        pois = [
            {"name": "熊猫基地", "lng": 104.145, "lat": 30.735},   # 北
            {"name": "宽窄巷子", "lng": 104.055, "lat": 30.665},   # 市中心
            {"name": "人民公园", "lng": 104.063, "lat": 30.659},   # 市中心
        ]
        clusters = cluster_by_distance(pois, threshold_km=2.0)
        # 宽窄巷子和人民公园应在一组（~1km），熊猫基地单独一组（>5km）
        assert len(clusters) == 2
        names_in_clusters = [
            sorted(p["name"] for p in c) for c in clusters
        ]
        names_in_clusters.sort()
        assert names_in_clusters == [
            ["人民公园", "宽窄巷子"],
            ["熊猫基地"],
        ]

    def test_single_poi(self):
        """单个 POI 自成一组"""
        clusters = cluster_by_distance([{"name": "A", "lng": 104.0, "lat": 30.6}])
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_empty_list(self):
        assert cluster_by_distance([]) == []


# ====================================================================
#  3. AB 双方案解析
# ====================================================================

class TestParseABPlans:
    """从 LLM 输出中解析方案 A / 方案 B"""

    def test_both_plans(self):
        raw = (
            "大家好，这是你们的旅行攻略。\n\n"
            "## 方案 A：集体妥协路线\n"
            "Day 1: 熊猫基地\n\n"
            "## 方案 B：动态分头路线\n"
            "Day 1: 分开玩\n"
        )
        result = parse_ab_plans(raw)
        assert "大家好" in result["intro"]
        assert "熊猫基地" in result["plan_a"]
        assert "分开玩" in result["plan_b"]

    def test_only_plan_a(self):
        """只有方案 A（没有方案 B 时，全文作为 plan_a）"""
        raw = "## 方案 A：集体妥协路线\nDay 1: 熊猫基地\n"
        result = parse_ab_plans(raw)
        assert "熊猫基地" in result["plan_a"]
        assert result["plan_b"] == ""

    def test_no_section_headers(self):
        """没有分段标题时，全文作为 plan_a"""
        raw = "这是一篇没有标题的攻略。"
        result = parse_ab_plans(raw)
        assert result["plan_a"] == raw
        assert result["intro"] == ""

    def test_empty_string(self):
        result = parse_ab_plans("")
        assert result["plan_a"] == ""
        assert result["plan_b"] == ""


# ====================================================================
#  4. 数据加载
# ====================================================================

class TestLoadGroupData:
    """从 group 目录加载成员数据"""

    def test_no_group_dir(self, tmp_path):
        """不存在的目录返回空结构"""
        # 模拟：临时切到 tmp_path 确保 data/ 不存在
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = load_group_data("nonexistent")
            assert result == {"users": [], "destination": "", "days": 3}
        finally:
            os.chdir(original_cwd)

    def test_load_with_mock_data(self, tmp_path):
        """加载有效的小组数据"""
        group_dir = tmp_path / "data" / "test_group"
        group_dir.mkdir(parents=True)

        # group.json
        (group_dir / "group.json").write_text(
            json.dumps({"destination": "成都", "days": 3}, ensure_ascii=False),
            encoding="utf-8",
        )

        # 两个成员
        user1 = {
            "name": "晓明", "budget": "宽裕派",
            "sleep_energy": "夜猫子", "intensity_score": 9,
            "wishlist": "吃火锅", "is_private": False,
            "status": "completed",
        }
        user2 = {
            "name": "小美", "budget": "省钱党",
            "sleep_energy": "早睡早起", "intensity_score": 3,
            "wishlist": "吃甜品", "is_private": True,
            "status": "completed",
        }
        (group_dir / "user1.json").write_text(
            json.dumps(user1, ensure_ascii=False), encoding="utf-8"
        )
        (group_dir / "user2.json").write_text(
            json.dumps(user2, ensure_ascii=False), encoding="utf-8"
        )

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = load_group_data("test_group")
            assert result["destination"] == "成都"
            assert result["days"] == 3
            assert len(result["users"]) == 2
        finally:
            os.chdir(original_cwd)

    def test_skip_incomplete_users(self, tmp_path):
        """跳过未提交的成员"""
        group_dir = tmp_path / "data" / "partial"
        group_dir.mkdir(parents=True)
        (group_dir / "group.json").write_text(
            json.dumps({"destination": "北京", "days": 2}), encoding="utf-8"
        )
        (group_dir / "u1.json").write_text(
            json.dumps({"name": "A", "status": "completed", "intensity_score": 5}),
            encoding="utf-8",
        )
        (group_dir / "u2.json").write_text(
            json.dumps({"name": "B", "status": "pending", "intensity_score": 5}),
            encoding="utf-8",
        )

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = load_group_data("partial")
            assert len(result["users"]) == 1
            assert result["users"][0]["name"] == "A"
        finally:
            os.chdir(original_cwd)

    def test_missing_group_json(self, tmp_path):
        """没有 group.json 时返回默认值"""
        group_dir = tmp_path / "data" / "nogroupjson"
        group_dir.mkdir(parents=True)

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = load_group_data("nogroupjson")
            assert result["destination"] == ""
            assert result["days"] == 3
        finally:
            os.chdir(original_cwd)

    def test_skip_result_json(self, tmp_path):
        """跳过 result.json 不当作成员"""
        group_dir = tmp_path / "data" / "withresult"
        group_dir.mkdir(parents=True)
        (group_dir / "group.json").write_text(
            json.dumps({"destination": "上海", "days": 2}), encoding="utf-8"
        )
        (group_dir / "result.json").write_text(
            json.dumps({"plan_a": "xxx"}), encoding="utf-8"
        )
        (group_dir / "u1.json").write_text(
            json.dumps({"name": "C", "status": "completed", "intensity_score": 5}),
            encoding="utf-8",
        )

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = load_group_data("withresult")
            assert len(result["users"]) == 1
        finally:
            os.chdir(original_cwd)


# ====================================================================
#  5. app.py 数据层
# ====================================================================

class TestAppDataLayer:
    """app.py 中的数据持久化函数"""

    def _import_data_funcs(self):
        """动态导入 app.py 中的数据函数"""
        import importlib
        spec = importlib.util.spec_from_file_location(
            "app_module", _project_root / "app.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # 避免触发 streamlit 运行时导入
        # 只测试纯数据函数
        return mod

    def test_generate_id(self):
        """generate_id 生成 8 位字符"""
        from app import generate_id
        gid = generate_id()
        assert len(gid) == 8
        assert gid.isalnum()  # 只含字母数字

    def test_generate_id_unique(self):
        """多次生成的 ID 不重复"""
        from app import generate_id
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100

    def test_save_and_load_user_data(self, tmp_path):
        """保存后能正确读取用户数据"""
        from app import save_user_data, load_user_data
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            save_user_data("g1", "u1", {"name": "Test", "status": "pending"})
            data = load_user_data("g1", "u1")
            assert data["name"] == "Test"
            assert data["status"] == "pending"
        finally:
            os.chdir(original_cwd)

    def test_load_nonexistent_user(self, tmp_path):
        """读取不存在的用户返回空字典"""
        from app import load_user_data
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            data = load_user_data("nonexist", "nobody")
            assert data == {}
        finally:
            os.chdir(original_cwd)

    def test_save_and_load_group(self, tmp_path):
        """保存后能正确读取小组数据"""
        from app import save_group, load_group
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            save_group("testg", {"destination": "东京", "days": 5})
            data = load_group("testg")
            assert data["destination"] == "东京"
            assert data["days"] == 5
        finally:
            os.chdir(original_cwd)

    def test_delete_group(self, tmp_path):
        """删除小组目录"""
        from app import save_group, load_group, delete_group
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            save_group("delg", {"destination": "巴黎"})
            assert load_group("delg") != {}
            delete_group("delg")
            assert load_group("delg") == {}
        finally:
            os.chdir(original_cwd)


# ====================================================================
#  6. 示例数据格式校验
# ====================================================================

class TestSampleData:
    """示例数据格式正确性"""

    def test_sample_preferences_structure(self):
        """sample_preferences.json 包含必填字段"""
        path = _project_root / "data" / "sample_preferences.json"
        if not path.exists():
            pytest.skip("示例数据文件不存在")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "destination" in data
        assert "days" in data
        assert "members" in data
        for m in data["members"]:
            assert "name" in m
            assert "budget" in m
            assert "sleep_energy" in m
            assert "intensity_score" in m
            assert "wishlist" in m
            assert isinstance(m["intensity_score"], int)
            assert 1 <= m["intensity_score"] <= 10
