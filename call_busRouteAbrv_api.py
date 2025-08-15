# pip install requests
import os
import json
import requests
from urllib.parse import quote
from typing import List, Dict, Any

API_URL = "http://ws.bus.go.kr/api/rest/stationinfo/getRouteByStation"
SERVICE_KEY =  "E+z7rp0Eg8e2iAjfm3HOgbdX7Z7VSaVWl1K8gzEcJ/83+0Ejt9oiAGlBURxi0T+PBWsPXWCaW3pU6bI6xEFG1g=="

def _call_api(ars_id: str, *, timeout: float = 8.0, debug: bool = True) -> Dict[str, Any]:

    params = {"serviceKey": SERVICE_KEY, "arsId": str(ars_id).strip(), "resultType": "json"}
    r = requests.get(API_URL, params=params, timeout=timeout)

    if debug:
        print(f"[HTTP] {r.request.method} {r.url}")
        print(f"[HTTP] status={r.status_code}")
        print(f"[HTTP] body[:300]={r.text[:300]!r}")

    r.raise_for_status()
    data = r.json()

    if debug:
        print("\n=== [DEBUG] Parsed JSON ===")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print("=== [END DEBUG] ===\n")

    return data

def _get_item_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:

    item_list = None

    # 스키마 #1: ServiceResult 경로
    sr = data.get("ServiceResult")
    if isinstance(sr, dict):
        msg_body = sr.get("msgBody", {})
        item_list = msg_body.get("itemList")

    # 스키마 #2: 최상위 msgBody 경로
    if item_list is None:
        msg_body = data.get("msgBody", {})
        item_list = msg_body.get("itemList")

    if item_list is None:
        return []

    # 단일 객체가 올 수 있어 list로 정규화
    if isinstance(item_list, dict):
        return [item_list]
    if isinstance(item_list, list):
        return item_list
    return []

def _extract_busRouteAbrv_list(api_json: Dict[str, Any]) -> List[str]:
    items = _get_item_list(api_json)
    out: List[str] = []
    seen = set()
    for it in items:
        abrv = (it.get("busRouteAbrv") or "").strip()
        if abrv and abrv not in seen:
            seen.add(abrv)
            out.append(abrv)
    return out

def get_bus_numbers_by_station(ars_id: str, *, debug: bool = True) -> List[str]:
    data = _call_api(ars_id, debug=debug)
    nums = _extract_busRouteAbrv_list(data)

    return nums

if __name__ == "__main__":
    ars = "01001"  # 추후 데이터팀에서 받은 버스우회정보 대입 필요
    try:
        routes = get_bus_numbers_by_station(ars, debug=True)
        print(f"[{ars}] busRouteAbrv = {routes}")
    except Exception as e:
        print("에러:", e)
