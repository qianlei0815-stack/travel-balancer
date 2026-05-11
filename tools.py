"""
CrewAI 工具模块 —— 封装高德地图服务为 Agent 可调用的工具

所有工具均通过 @tool 装饰器注册，返回字符串而非抛出异常，
确保 Agent 在任何异常情况下都能收到友好提示而非崩溃。
"""

from crewai.tools import tool

from amap_service import get_route_info, search_nearby_poi


@tool("AmapRouteTool")
def amap_route_tool(origin_name: str, destination_name: str) -> str:
    """当需要安排两个连续景点/餐厅，或者评估交通耗时时，必须调用此工具。
    传入起点和终点名称，返回驾车距离和预估耗时。

    **重要：** 传入的地名必须带上目的地城市名（如"成都武侯祠"而非"武侯祠"），
    否则高德地图可能匹配到外省同名地点，导致跨省几百公里的错误数据。

    Args:
        origin_name: 起点地名，例如"成都武侯祠"
        destination_name: 终点地名，例如"成都杜甫草堂"
    """
    return get_route_info(origin_name, destination_name)


@tool("AmapPoiTool")
def amap_poi_tool(center_name: str, keyword: str, radius: int = 1000) -> str:
    """当需要寻找特定要求的餐厅、咖啡馆或休息点时调用此工具。
    传入中心地标名称和关键词（如'不辣美食'或'咖啡'），返回附近推荐列表。

    **重要：** center_name 必须带上目的地城市名（如"成都春熙路"而非"春熙路"），
    否则高德地图可能匹配到外省同名地点。

    Args:
        center_name: 中心地标名称，例如"成都春熙路"
        keyword: 搜索关键词，例如"火锅"、"咖啡"、"不辣美食"
        radius: 搜索半径（米），默认 1000 米
    """
    return search_nearby_poi(center_name, keyword, radius)
