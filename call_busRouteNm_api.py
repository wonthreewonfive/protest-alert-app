# -*- coding: utf-8 -*-
# pip install pandas requests

import re
import time
import json
import requests
import pandas as pd
from typing import Dict, Any, List, Tuple

# ==== 설정 ====
INPUT_CSV   = "bus_stops.csv"
OUTPUT_CSV  = "routes_final.csv"
API_URL     = "http://ws.bus.go.kr/api/rest/stationinfo/getRouteByStation"
SERVICE_KEY = "E+z7rp0Eg8e2iAjfm3HOgbdX7Z7VSaVWl1K8gzEcJ/83+0Ejt9oiAGlBURxi0T+PBWsPXWCaW3pU6bI6xEFG1g=="
TPS_DELAY   = 0.10  # 호출 간 최소 간격(초) - 과호출 방지

# ---- 유틸 ----
def normalize_ars_id(stop_id: str) -> str:

    if stop_id is None:
        return ""
    s = str(stop_id).strip()
    if not re.match(r"^(01\d{3}|01-\d{3})$", s):
        return ""
    digits_only = re.sub(r"[^0-9]", "", s)
    return digits_only if len(digits_only) == 5 else ""

def call_station_routes(ars_id: str, timeout: float = 8.0, debug: bool = False) -> Dict[str, Any]:

    params = {"serviceKey": SERVICE_KEY, "arsId": ars_id, "resultType": "json"}
    r = requests.get(API_URL, params=params, timeout=timeout)
    if debug:
        print(f"[HTTP] {r.request.method} {r.url}")
        print(f"[HTTP] status={r.status_code}")
        print(f"[HTTP] body[:200]={r.text[:200]!r}")
    r.raise_for_status()
    data = r.json()
    header = data.get("msgHeader") or data.get("ServiceResult", {}).get("msgHeader", {})
    cd = (header or {}).get("headerCd")
    if cd not in (None, "0", 0):
        msg = (header or {}).get("headerMsg")
        raise RuntimeError(f"API 오류: headerCd={cd}, headerMsg={msg}")
    return data

def extract_busRouteNm_list(api_json: Dict[str, Any]) -> List[str]:
    body = api_json.get("msgBody") or api_json.get("ServiceResult", {}).get("msgBody", {}) or {}
    items = body.get("itemList") or []
    if isinstance(items, dict):
        items = [items]
    out, seen = [], set()
    for it in items:
        nm = (it.get("busRouteNm") or "").strip()
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out


def main():
    df = pd.read_csv(INPUT_CSV, dtype={"stop_id": str})
    if list(df.columns[:2]) != ["date", "stop_id"]:
        cols = list(df.columns)
        cols[:2] = ["date", "stop_id"]
        df.columns = cols
    df["stop_id"] = df["stop_id"].astype(str).str.strip()

    df["ars_id"] = df["stop_id"].apply(normalize_ars_id)
    df_filt = df[df["ars_id"] != ""].copy()

    pairs: List[Tuple[str, str]] = (
        df_filt[["date", "ars_id"]].drop_duplicates().itertuples(index=False, name=None)
    )

    cache: Dict[str, List[str]] = {}
    rows: List[Dict[str, Any]] = []  # 최종 CSV: date, ars_id, route

    for date_str, ars_id in pairs:
        if ars_id not in cache:
            try:
                data = call_station_routes(ars_id, debug=False)
                routes = extract_busRouteNm_list(data)
                cache[ars_id] = routes
            except Exception as e:
                print(f"[WARN] {ars_id}: {e}")
                cache[ars_id] = []
            time.sleep(TPS_DELAY)
        routes = cache[ars_id]
        if routes:
            for rt in routes:
                rows.append({"date": date_str, "ars_id": ars_id, "route": rt})
        else:
            pass

    out_df = pd.DataFrame(rows).sort_values(["date", "ars_id", "route"], na_position="last")
    out_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"완료: {OUTPUT_CSV}  (rows={len(out_df)})")

if __name__ == "__main__":
    main()
