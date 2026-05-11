"""
高德地图 API 服务模块 —— 地理编码 / 路径规划 / 天气预报 / 地理聚合

所有函数均以静态方法形式提供，无需实例化 AmapService。
依赖环境变量: AMAP_API_KEY
"""

import logging
import math
import os
import re
import time
from typing import Any

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("AMAP_API_KEY", "")
_BASE = "https://restapi.amap.com/v3"


class AmapError(Exception):
    """高德 API 调用异常"""


# ====================================================================
#  内部基础请求（带重试机制的 Session + 24h TTL 缓存）
# ====================================================================

_session = requests.Session()
_retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[408, 429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# 简单 TTL 缓存：高频测试场景下避免重复调用高德 API
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 86400  # 24 小时


def _cache_key(endpoint: str, params: dict) -> str:
    items = sorted((k, v) for k, v in params.items() if k != "key")
    return f"{endpoint}:{items}"


def _get(endpoint: str, params: dict) -> dict:
    if not _API_KEY:
        raise AmapError("AMAP_API_KEY 未设置，请在 .env 文件中配置")
    params["key"] = _API_KEY

    # 查缓存（TTL 内且 status=1 的正常结果才缓存）
    ck = _cache_key(endpoint, params)
    now = time.time()
    cached = _cache.get(ck)
    if cached and cached[0] > now:
        logger.debug("高德 API 缓存命中: %s", endpoint)
        return cached[1]

    url = f"{_BASE}/{endpoint}"
    try:
        resp = _session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("高德 API 请求超时 (endpoint=%s, params=%s)", endpoint, params)
        raise AmapError("地图服务暂时拥堵（请求超时），请稍后重试")
    except requests.exceptions.ConnectionError:
        logger.error("高德 API 连接失败 (endpoint=%s)", endpoint)
        raise AmapError("地图服务网络连接失败，请检查网络配置")
    except requests.exceptions.RequestException as e:
        logger.error("高德 API 请求异常: %s", e)
        raise AmapError(f"地图服务请求失败: {e}")
    if data.get("status") != "1":
        raise AmapError(f"高德 API 错误 [{info(data)}] — {data.get('info', '未知错误')}")

    # 写入缓存
    _cache[ck] = (now + _CACHE_TTL, data)
    return data


def info(data: dict) -> str:
    return data.get("infocode", data.get("info", "???"))


# ====================================================================
#  1. 地理编码
# ====================================================================

def geocode(address: str, city: str = "") -> dict[str, Any]:
    """地名 → 经纬度

    返回: {"name": str, "lng": float, "lat": float, "formatted": str,
           "level": str, "adcode": str}
    """
    params: dict[str, str] = {"address": address}
    if city:
        params["city"] = city
    data = _get("geocode/geo", params)
    geocodes = data.get("geocodes", [])
    if not geocodes:
        raise AmapError(f"未找到地址: {address}")
    g = geocodes[0]
    lng, lat = g["location"].split(",")
    return {
        "name": address,
        "lng": float(lng),
        "lat": float(lat),
        "formatted": g.get("formatted_address", address),
        "level": g.get("level", ""),
        "adcode": g.get("adcode", ""),
    }


def batch_geocode(addresses: list[str], city: str = "") -> list[dict]:
    """批量地理编码（逐个调用，自带容错）"""
    results = []
    for addr in addresses:
        try:
            results.append(geocode(addr, city))
        except AmapError:
            continue
    return results


# ====================================================================
#  2. 路径规划
# ====================================================================

def driving_route(origin: str, destination: str) -> dict:
    """驾车路径规划

    参数: origin/destination 为 "lng,lat" 格式

    返回: {"distance_m": int, "duration_s": int, "distance_km": float,
           "duration_min": float, "polyline_pts": [(lng,lat), ...]}
    """
    data = _get("direction/driving", {
        "origin": origin,
        "destination": destination,
        "strategy": 0,  # 最快路线
    })
    paths = data.get("route", {}).get("paths", [])
    if not paths:
        raise AmapError("驾车路线规划失败")
    path = paths[0]
    dist_m = int(path.get("distance", 0))
    dur_s = int(path.get("duration", 0))

    # 解析 polyline（各路段坐标点）
    pts = []
    for step in path.get("steps", []):
        pl = step.get("polyline", "")
        for seg in pl.split(";"):
            if seg:
                lng_s, lat_s = seg.split(",")
                pts.append((float(lng_s), float(lat_s)))

    return {
        "distance_m": dist_m,
        "duration_s": dur_s,
        "distance_km": round(dist_m / 1000, 1),
        "duration_min": round(dur_s / 60, 1),
        "polyline_pts": pts,
    }


def walking_route(origin: str, destination: str) -> dict:
    """步行路径规划，返回格式同上"""
    data = _get("direction/walking", {
        "origin": origin,
        "destination": destination,
    })
    paths = data.get("route", {}).get("paths", [])
    if not paths:
        raise AmapError("步行路线规划失败")
    path = paths[0]
    dist_m = int(path.get("distance", 0))
    dur_s = int(path.get("duration", 0))

    pts = []
    for step in path.get("steps", []):
        pl = step.get("polyline", "")
        for seg in pl.split(";"):
            if seg:
                lng_s, lat_s = seg.split(",")
                pts.append((float(lng_s), float(lat_s)))

    return {
        "distance_m": dist_m,
        "duration_s": dur_s,
        "distance_km": round(dist_m / 1000, 1),
        "duration_min": round(dur_s / 60, 1),
        "polyline_pts": pts,
    }


# ====================================================================
#  3. 天气预报
# ====================================================================

def weather_forecast(city: str, extensions: str = "all") -> dict:
    """天气预报

    参数:
        city: 城市名称 或 adcode（推荐使用 adcode）
        extensions: "base" → 实况天气; "all" → 3 天预报（默认）

    返回:
        实况: {"weather": str, "temperature": str, "winddirection": str,
               "windpower": str, "humidity": str, "reporttime": str}
        预报: {"casts": [{date, week, dayweather, nightweather,
               daytemp, nighttemp, daywind, nightwind}, ...]}
    """
    data = _get("weather/weatherInfo", {
        "city": city,
        "extensions": extensions,
    })
    return data


def format_weather_summary(city: str) -> str:
    """获取城市天气预报并格式化为可读文本（供 LLM 注入）"""
    try:
        f = weather_forecast(city, "all")
        lives = f.get("lives", [])
        forecasts = f.get("forecasts", [])

        parts = []
        if lives:
            live = lives[0]
            parts.append(
                f"【实况】{live.get('weather','')} / "
                f"{live.get('temperature','')}°C / "
                f"{live.get('winddirection','')}风{live.get('windpower','')}级"
            )

        if forecasts:
            for cast in forecasts[0].get("casts", []):
                parts.append(
                    f"{cast.get('date','')}（周{cast.get('week','')}）: "
                    f"白天{cast.get('dayweather','')} {cast.get('daytemp','')}°C / "
                    f"夜间{cast.get('nightweather','')} {cast.get('nighttemp','')}°C"
                )

        return f"📍 {city} 天气预报\n" + "\n".join(parts) if parts else "暂无天气数据"
    except AmapError:
        return "⚠️ 天气数据获取失败"


# ====================================================================
#  4. 地理聚合
# ====================================================================

def _haversine_km(a: dict, b: dict) -> float:
    """Haversine 公式计算两点距离（公里）"""
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lng"] - a["lng"])
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    a_val = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * 6371 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))


def cluster_by_distance(pois: list[dict],
                        threshold_km: float = 2.0) -> list[list[dict]]:
    """将 POI 按地理距离分组

    参数:
        pois: [{"name": str, "lng": float, "lat": float}, ...]
        threshold_km: 归组阈值（公里），最小 0.5 km

    返回:
        [[poi1, poi2], [poi3], ...] 每组内的 POI 互相靠近
    """
    threshold_km = max(threshold_km, 0.5)
    clusters: list[list[dict]] = []
    assigned: set[int] = set()

    for i, poi in enumerate(pois):
        if i in assigned:
            continue
        cluster = [poi]
        assigned.add(i)
        for j in range(i + 1, len(pois)):
            if j in assigned:
                continue
            if _haversine_km(poi, pois[j]) <= threshold_km:
                cluster.append(pois[j])
                assigned.add(j)
        clusters.append(cluster)

    return clusters


def describe_clusters(clusters: list[list[dict]]) -> str:
    """将聚类结果转换为可读文本"""
    lines = []
    for idx, cluster in enumerate(clusters, 1):
        names = "、".join(p["name"] for p in cluster)
        lines.append(f"区域 {idx}: {names}")
    return "\n".join(lines)


# ====================================================================
#  5. 从行程文本中提取景点名称
# ====================================================================

# 严格模式：要求前缀动词 + 格式化标点
_STRICT_PATTERN = re.compile(
    r'[📍🏛️🎯🏔️⛰️🏖️🏕️]?\s*'
    r'(?:前往|去|到|参观|游览|游玩|打卡|逛|访|走进|抵达)?'
    r'[《「『]?\s*'
    r'(【([^】]+)】|\*\*([^*]+)\*\*|「([^」]+)」|《([^》]+)》)'
)

# 宽泛模式：只要被 **加粗** 或 【】 包裹就提取（不限前缀）
_BROAD_PATTERN = re.compile(r'\*\*([^*]+)\*\*|【([^】]+)】')


def extract_place_names(markdown_text: str) -> list[str]:
    """从 Markdown 行程文本中提取景点名称

    先尝试严格模式（带前缀动词的），再回退到宽泛模式（任何加粗/书名号内容），
    最后过滤掉常见非景点词汇。
    """
    seen: set[str] = set()
    places: list[str] = []

    _skip_words = {
        "推荐理由", "对谁友好", "交通方式", "步行", "驾车", "打车", "地铁",
        "上午", "下午", "晚上", "中午", "早上", "夜间",
        "高强度组", "低强度组", "汇合点", "集体行动", "分头行动",
        "设计理念", "方案", "行程", "安排", "活动", "餐厅", "景点",
    }

    def _add(name: str):
        name = name.strip().rstrip("，。！？、：;；,.:;!?")
        if name and len(name) >= 2 and name not in seen and name not in _skip_words:
            seen.add(name)
            places.append(name)

    # 第一轮：严格模式
    for m in _STRICT_PATTERN.finditer(markdown_text):
        for g in m.groups()[1:]:
            if g:
                _add(g)
                break

    # 第二轮（若第一轮没结果）：宽泛模式
    if not places:
        for m in _BROAD_PATTERN.finditer(markdown_text):
            for g in m.groups():
                if g:
                    _add(g)
                    break

    return places


def extract_per_day_places(markdown_text: str,
                           total_days: int) -> dict[int, list[str]]:
    """按天提取景点名称

    返回: {1: ["熊猫基地", ...], 2: [...], ...}
    """
    day_places: dict[int, list[str]] = {}
    current_day = 0

    for line in markdown_text.split("\n"):
        # 检测 Day 标题行
        day_m = re.search(r'(?:Day|第)\s*(\d+)', line, re.IGNORECASE)
        if day_m:
            d = int(day_m.group(1))
            if 1 <= d <= total_days:
                current_day = d
                continue

        if current_day > 0:
            places = extract_place_names(line)
            if places:
                day_places.setdefault(current_day, []).extend(places)

    return day_places


def build_day_routes(day_places: dict[int, list[str]],
                     city: str = "") -> dict[int, list[dict]]:
    """为每天的景点构建完整的路线数据（含坐标、距离、耗时）

    返回:
        {1: [{"name": ..., "lng": ..., "lat": ..., "dist_km": ...}, ...], ...}
    """
    result: dict[int, list[dict]] = {}
    for day in sorted(day_places.keys()):
        places = day_places[day]
        geocoded = batch_geocode(places, city)
        enriched: list[dict] = []
        for i, poi in enumerate(geocoded):
            entry: dict[str, Any] = {**poi, "dist_km": 0, "duration_min": 0}
            if i > 0 and enriched:
                prev = enriched[-1]
                prev_lnglat = f"{prev['lng']},{prev['lat']}"
                curr_lnglat = f"{poi['lng']},{poi['lat']}"
                try:
                    route = driving_route(prev_lnglat, curr_lnglat)
                    entry["dist_km"] = route["distance_km"]
                    entry["duration_min"] = route["duration_min"]
                except AmapError:
                    # 走路试试
                    try:
                        route = walking_route(prev_lnglat, curr_lnglat)
                        entry["dist_km"] = route["distance_km"]
                        entry["duration_min"] = route["duration_min"]
                    except AmapError:
                        entry["dist_km"] = 0
                        entry["duration_min"] = 0
            enriched.append(entry)

        # 聚类检测
        enriched_clusters = cluster_by_distance(enriched, 2.0)
        for ci, cluster in enumerate(enriched_clusters):
            for poi in cluster:
                poi["cluster"] = ci + 1

        result[day] = enriched

    return result


# ====================================================================
#  6. 工具方法（供 CrewAI Agent 调用，返回简洁字符串）
# ====================================================================

def get_location(address: str, city: str = "") -> str:
    """地名 → "经度,纬度" 字符串

    参数:
        address: 地名/景点名（建议包含城市名防同名匹配）
        city: 城市限定，传空则自动匹配

    返回:
        "lng,lat" 字符串，失败时返回空字符串
    """
    try:
        g = geocode(address, city=city)
        return f"{g['lng']},{g['lat']}"
    except AmapError:
        logger.warning("get_location 失败: %s (%s)", address, city)
        return ""
    except Exception as e:
        logger.error("get_location 意外异常: %s", e)
        return ""


def get_route_info(origin_name: str, destination_name: str,
                   city: str = "") -> str:
    """起止地名 → 驾车路线自然语言描述

    参数:
        origin_name: 起点地名（建议包含城市名）
        destination_name: 终点地名（建议包含城市名）
        city: 城市限定，传空则自动匹配

    返回:
        "从[A]到[B]驾车距离约 X 公里，预估耗时 Y 分钟。"
        失败时返回友好提示。
    """
    try:
        origin_loc = get_location(origin_name, city=city)
        if not origin_loc:
            return f"无法获取 {origin_name} 的位置信息。"
        dest_loc = get_location(destination_name, city=city)
        if not dest_loc:
            return f"无法获取 {destination_name} 的位置信息。"

        route = driving_route(origin_loc, dest_loc)
        return (
            f"从{origin_name}到{destination_name}"
            f"驾车距离约 {route['distance_km']} 公里，"
            f"预估耗时 {route['duration_min']} 分钟。"
        )
    except AmapError as e:
        logger.warning("get_route_info 高德错误: %s", e)
        return f"抱歉，暂时无法查询从{origin_name}到{destination_name}的驾车信息，建议根据常识判断交通耗时。"
    except Exception as e:
        logger.error("get_route_info 意外异常: %s", e)
        return f"路线查询异常，请根据常识估算从{origin_name}到{destination_name}的交通时间。"


def search_nearby_poi(center_name: str, keyword: str, radius: int = 1000,
                      city: str = "") -> str:
    """周边 POI 搜索 → 格式化的结果列表字符串

    参数:
        center_name: 中心地标名称（建议包含城市名）
        keyword: 搜索关键词（如"火锅"、"咖啡"、"不辣美食"）
        radius: 搜索半径（米），默认 1000
        city: 城市限定，传空则自动匹配

    返回:
        格式化字符串："1. 店铺名 - 距离 Xm - 地址: xxx\\n2. ..."
        失败时返回友好提示。
    """
    try:
        center_loc = get_location(center_name, city=city)
        if not center_loc:
            return f"无法获取 {center_name} 的位置信息，请根据常识推荐。"
    except Exception as e:
        logger.error("search_nearby_poi 定位失败: %s", e)
        return f"无法获取 {center_name} 的位置信息，请根据常识推荐。"

    # === 关键词脱敏：去掉 Agent 可能夹带的噪音词 ===
    _noise_words = {"成都", "推荐", "好吃的", "必去", "打卡", "著名的", "好玩的"}
    cleaned = keyword.strip()
    for w in _noise_words:
        cleaned = cleaned.replace(w, "").strip()
    # 去掉多余空格和标点
    cleaned = re.sub(r"[，、\s]+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "美食"

    # === 带降级兜底的搜索 ===
    def _do_search(kw: str) -> list[dict]:
        try:
            data = _get("place/around", {
                "location": center_loc,
                "keywords": kw,
                "radius": str(radius),
                "offset": "5",
            })
            return data.get("pois", [])
        except AmapError:
            return []

    pois = _do_search(cleaned)

    # 降级：原词无结果 → 逐级缩小关键词
    if not pois:
        fallback_chain = []
        # 尝试提取最后一个有意义的词（如 "陶德砂锅" → "砂锅"）
        words = cleaned.split()
        if len(words) > 1:
            fallback_chain.append(words[-1])
        # 通用兜底
        fallback_chain.extend(["川菜", "小吃", "美食", "餐厅"])
        for fb in fallback_chain:
            if fb == cleaned:
                continue
            pois = _do_search(fb)
            if pois:
                logger.info("POI 搜索降级: '%s' → '%s' 命中 %d 条", cleaned, fb, len(pois))
                break

    if not pois:
        return f"在{center_name}附近未找到「{keyword}」相关地点，建议换一批关键词或根据常识推荐。"

    lines = []
    for i, poi in enumerate(pois[:5], 1):
        name = poi.get("name", "未知")
        dist = poi.get("distance", "")
        address = poi.get("address", "")
        poi_type = poi.get("type", "")
        parts = [f"{i}. {name}"]
        if dist:
            parts.append(f"距离 {dist}m")
        if address:
            parts.append(f"地址: {address}")
        if poi_type:
            parts.append(f"类型: {poi_type}")
        lines.append(" - ".join(parts))
    return "\n".join(lines)
