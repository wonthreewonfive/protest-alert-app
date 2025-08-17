# app.py
import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from dateutil import parser
from datetime import date, datetime
from streamlit_calendar import calendar
from pathlib import Path
import re
import textwrap
from collections import Counter

# --- optional: wordcloud ---
try:
    from wordcloud import WordCloud
    WORDCLOUD_AVAILABLE = True
except Exception:
    WORDCLOUD_AVAILABLE = False

st.set_page_config(page_title="집회/시위 알림 서비스", page_icon="📅", layout="wide")

# ===== 스타일 =====
st.markdown("""
<style>
  .stApp, .main, [data-testid="stHeader"] { background: #ffffff !important; }

  /* 상단 사이트 타이틀 헤더 */
  .app-header{
    border:1px solid #e5e7eb; border-radius:12px;
    background:#f3f4f6; padding:14px 24px;
    font-weight:800; font-size:20px; color:#111827;
    text-align:center; margin:6px 0 16px 0;
  }

  /* 카드 공통 */
  .card { border:1px solid #e5e7eb; border-radius:14px; padding:16px; margin:12px 6px; background:#fff; }
  .time { font-weight:800; font-size:18px; margin-bottom:6px; color:#111827; }
  .sub  { color:#6b7280; font-size:14px; margin-bottom:8px; }
  .meta { color:#374151; font-size:14px; }

  /* 카드형 링크 */
  a.card-link { display:block; text-decoration:none; color:inherit; }
  a.card-link .card:hover { border-color:#94a3b8; background:#f8fafc; }

  /* 달력: 텍스트 숨기고 도트만 보이게 */
  .fc .fc-daygrid-dot-event .fc-event-time,
  .fc .fc-daygrid-dot-event .fc-event-title,
  .fc .fc-daygrid-event-harness .fc-event-time,
  .fc .fc-daygrid-event-harness .fc-event-title { display:none !important; }
  .fc-daygrid-dot-event > .fc-event-dot { width:10px; height:10px; border:0; }
</style>
""", unsafe_allow_html=True)

# ---------- 데이터 로드 ----------
@st.cache_data
def load_events(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    df = pd.read_excel(p) if p.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(p)

    variants = {
        "date": ["date","날짜"],
        "start_time": ["start_time","start","시작","starttime"],
        "end_time": ["end_time","end","종료","endtime"],
        "location": ["location","장소","place"],
        "district": ["district","관할서","구"],
        "reported_head": ["reported_head","reported_headcount","신고인원","인원"],
        "memo": ["memo","비고","메모"],
    }
    def find_col(k):
        for cand in variants[k]:
            for c in df.columns:
                if str(c).strip().lower() == cand.lower():
                    return c
        return None
    col = {k: find_col(k) for k in variants}
    for k in ["date","start_time","end_time","location"]:
        if col[k] is None: raise ValueError(f"'{k}' 컬럼이 필요합니다.")

    def to_date(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', s):
            s = s.replace(".", "-")
        try: return parser.parse(s).date()
        except: return None

    def to_time(x):
        if pd.isna(x): return None
        try:
            t = parser.parse(str(x)).time()
            return f"{t.hour:02d}:{t.minute:02d}"
        except: return None

    df["_date"]  = df[col["date"]].apply(to_date)
    df["_start"] = df[col["start_time"]].apply(to_time)
    df["_end"]   = df[col["end_time"]].apply(to_time)
    df["_loc"]   = df[col["location"]].astype(str)
    df["_dist"]  = df[col["district"]].astype(str) if col["district"] else ""
    df["_head"]  = df[col["reported_head"]] if col["reported_head"] else ""
    df["_memo"]  = df[col["memo"]].astype(str) if col["memo"] else ""

    df = df[df["_date"].notnull() & df["_start"].notnull() & df["_end"].notnull()]
    return df.reset_index(drop=True)

@st.cache_data
def load_bus(path: str) -> pd.DataFrame:
    """
    bus_data.xlsx
    필요한 컬럼: start_date, start_time, end_date, end_time, ARS_ID, 정류소명, x좌표(lon), y좌표(lat)
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_excel(p)

    def to_date(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', s):
            s = s.replace(".", "-")
        try: return parser.parse(s).date()
        except: return None

    def to_time(x):
        if pd.isna(x): return None
        try:
            t = parser.parse(str(x)).time()
            return f"{t.hour:02d}:{t.minute:02d}"
        except: return None

    # 유연 컬럼명 매핑
    cols = {c: str(c).strip().lower() for c in df.columns}
    def pick(*names):
        for n in names:
            for c, lc in cols.items():
                if lc == n:
                    return c
        return None

    c_sd = pick("start_date","시작일")
    c_st = pick("start_time","시작시간")
    c_ed = pick("end_date","종료일")
    c_et = pick("end_time","종료시간")
    c_ars= pick("ars_id","ars","정류장id")
    c_nm = pick("정류소명","정류장명","stop_name")
    c_x  = pick("x좌표","x","lon","lng")
    c_y  = pick("y좌표","y","lat")

    req = [c_sd,c_st,c_ed,c_et,c_ars,c_nm,c_x,c_y]
    if any(c is None for c in req):
        return pd.DataFrame()

    # ARS_ID → 숫자/점 제거 후 5자리 0-padding
    ars_series = (
        df[c_ars]
        .astype(str)
        .map(lambda s: re.sub(r"\D", "", s))
        .map(lambda s: s.zfill(5))
    )

    out = pd.DataFrame({
        "start_date": df[c_sd].apply(to_date),
        "start_time": df[c_st].apply(to_time),
        "end_date":   df[c_ed].apply(to_date),
        "end_time":   df[c_et].apply(to_time),
        "ARS_ID":     ars_series,
        "정류소명":      df[c_nm].astype(str),
        "lon":        pd.to_numeric(df[c_x], errors="coerce"),
        "lat":        pd.to_numeric(df[c_y], errors="coerce"),
    })
    out = out.dropna(subset=["start_date","end_date","lon","lat"]).reset_index(drop=True)
    return out

@st.cache_data
def load_routes(path: str) -> pd.DataFrame:
    """
    routes_final.csv (예시 컬럼: date, ars_id, route)
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["date","ars_id","route"])
    df = pd.read_csv(p, dtype={"ars_id": str, "route": str})

    def to_date(x):
        try:
            return parser.parse(str(x)).date()
        except Exception:
            return None

    df["date"] = df["date"].apply(to_date)
    df["ars_id"] = (
        df["ars_id"].astype(str)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(5)
    )
    df["route"] = df["route"].fillna("").astype(str).str.strip()
    return df.dropna(subset=["date","ars_id"]).reset_index(drop=True)

def color_by_headcount(h):
    try:
        n = int(h)
        if n >= 1000: return "#ef4444"
        if n >= 500:  return "#f59e0b"
        return "#3b82f6"
    except:
        return "#3b82f6"

def df_to_month_dots(df: pd.DataFrame):
    events = []
    for _, r in df.iterrows():
        start_iso = f"{r['_date']}T{r['_start']}:00"
        end_iso   = f"{r['_date']}T{r['_end']}:00"
        events.append({
            "title": "",
            "start": start_iso,
            "end": end_iso,
            "display": "list-item",
            "color": color_by_headcount(r["_head"]),
        })
    return events

def filter_by_day(df: pd.DataFrame, d: date) -> pd.DataFrame:
    return df[df["_date"] == d].sort_values(by=["_start","_end","_loc"])

def get_bus_rows_for_date(bus_df: pd.DataFrame, d: date) -> pd.DataFrame:
    if bus_df is None or bus_df.empty:
        return pd.DataFrame()
    m = (bus_df["start_date"] <= d) & (bus_df["end_date"] >= d)
    return bus_df[m].copy()

# -------------- 텍스트 전처리/키워드 --------------
_STOPWORDS = {
    "그리고","그러나","하지만","또는","및","때문","때문에","대한","관련","대해",
    "여러분","정도","부분","등","좀","너무","수","것","거","이것","저것","우리",
    "입니다","합니다","하는","있는","되는","됩니다","드립니다","해주시면","해주십시오",
    "해주세요","부탁드립니다","같습니다","감사합니다","감사하겠습니다","불편합니다",
    "입니다만","않습니다","않아요","않구요","됩니다만",
    "으로","로","에서","에게","에는","에","의","을","를","이","가","와","과","도","만","보다",
}
_SUFFIX_PAT = re.compile(
    r"(입니다|합니다|하십시오|해주세요|해주시기|해주시길|해주시면|해주십시오|"
    r"되겠습니다|되겠습|되었습|되었으면|되면|되어|되었습니다|되는데|않습니다|않아요|"
    r"같습니다|하겠습니다|부탁드립니다|감사합니다|감사하겠습니다|해요|했어요|합니다만)$"
)
def strip_suffix(tok: str) -> str:
    tok = re.sub(_SUFFIX_PAT, "", tok);  return tok
def tokenize_ko(s: str):
    if not isinstance(s, str): return []
    cand = re.findall(r"[가-힣A-Za-z0-9]+", s)
    out = []
    for t in cand:
        t = strip_suffix(t)
        if len(t) < 2:   # 한 글자 제거
            continue
        if t in _STOPWORDS:
            continue
        out.append(t)
    return out
def make_bigrams(tokens, join_str=" "):
    return [join_str.join(pair) for pair in zip(tokens, tokens[1:])]
def build_wordcloud_image(fb_df: pd.DataFrame, date_filter=None, use_bigrams=False,
                          font_path="data/Nanum_Gothic/NanumGothic-Regular.ttf"):
    if not WORDCLOUD_AVAILABLE: return None
    if fb_df is None or fb_df.empty or "feedback" not in fb_df.columns: return None
    df = fb_df.copy()
    if date_filter is not None and "date" in df.columns:
        df = df[df["date"].astype(str) == str(date_filter)]
    texts = df["feedback"].dropna().astype(str).tolist()
    if not texts: return None
    counter = Counter()
    for t in texts:
        toks = tokenize_ko(t)
        if use_bigrams:
            toks = make_bigrams(toks)
        counter.update(toks)
    if not counter: return None
    fp = font_path if Path(font_path).exists() else None
    wc = WordCloud(font_path=fp, width=1200, height=600, background_color="white", colormap="tab20c")
    return wc.generate_from_frequencies(counter).to_image()
def top_terms_from_feedback(fb_df, date_filter=None, use_bigrams=False, top_k=20):
    if fb_df is None or fb_df.empty or "feedback" not in fb_df.columns:
        return pd.DataFrame(columns=["term","count","pct"])
    df = fb_df.copy()
    if date_filter is not None and "date" in df.columns:
        df = df[df["date"].astype(str) == str(date_filter)]
    texts = df["feedback"].dropna().astype(str).tolist()
    if not texts:
        return pd.DataFrame(columns=["term","count","pct"])
    counter = Counter()
    for t in texts:
        toks = tokenize_ko(t)
        if use_bigrams:
            toks = make_bigrams(toks)
        counter.update(toks)
    if not counter:
        return pd.DataFrame(columns=["term","count","pct"])
    items = counter.most_common(top_k)
    out = pd.DataFrame(items, columns=["term","count"])
    out["pct"] = (out["count"] / counter.total() * 100).round(1)
    return out
def load_feedback(path="data/feedback.csv"):
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()

# ---------- 상세 페이지 ----------
def render_detail(df_all: pd.DataFrame, bus_df: pd.DataFrame, routes_df: pd.DataFrame, d: date, idx: int):
    day_df = filter_by_day(df_all, d)
    if len(day_df) == 0 or idx < 0 or idx >= len(day_df):
        st.error("상세 정보를 찾을 수 없어요.")
        if st.button("← 목록으로"):
            st.query_params.clear()
            st.rerun()
        return

    row = day_df.iloc[idx]

    WEEK_KO = ["월","화","수","목","금","토","일"]
    st.markdown(f"## {d.month}월 {d.day}일({WEEK_KO[d.weekday()]}) 상세 정보")
    if st.button("← 목록으로"):
        st.query_params.clear()
        st.rerun()

    # (1) 오늘의 집회/시위
    st.subheader("오늘의 집회/시위")
    time_str = f"{row['_start']} ~ {row['_end']}"
    loc_str  = f"{(row['_dist']+' ') if row['_dist'] not in ['','nan','None'] else ''}{row['_loc']}"
    if pd.notna(row["_head"]) and str(row["_head"]).strip() != "":
        try: head_str = f"{int(row['_head'])}명"
        except: head_str = f"{row['_head']}명"
    else:
        head_str = ""
    keywords = str(row["_memo"]).strip() if str(row["_memo"]).strip() not in ["nan","None"] else ""
    info_df = pd.DataFrame([[time_str, loc_str, head_str, keywords]],
                           columns=["집회 시간","집회 장소(행진로)","신고 인원","관련 이슈"])
    st.table(info_df)

    # (1-1) 버스 우회 정보 + 지도 (+노선)
    st.markdown("### 버스 우회 정보")
    bus_rows = get_bus_rows_for_date(bus_df, d)

    # routes_final.csv 와 결합 (같은 날짜 d, 같은 정류장 ARS_ID)
    route_slice = pd.DataFrame()
    if routes_df is not None and not routes_df.empty:
        route_slice = routes_df[routes_df["date"] == d].copy()

    if bus_rows.empty:
        st.caption("※ 해당 날짜의 버스 우회 정보가 없습니다.")
    else:
        if not route_slice.empty:
            # 정류장별 노선 리스트 합치기
            agg = (route_slice
                   .dropna(subset=["ars_id","route"])
                   .groupby("ars_id")["route"]
                   .apply(lambda s: ", ".join(sorted(set(s))))
                   .rename("노선"))
            bus_rows = bus_rows.merge(agg, left_on="ARS_ID", right_index=True, how="left")
        else:
            bus_rows["노선"] = ""

        # 표
        bus_view = bus_rows[["start_time","end_time","ARS_ID","정류소명","노선"]].rename(
            columns={"start_time":"시작 시간","end_time":"종료 시간","ARS_ID":"버스 정류소 번호","정류소명":"버스 정류소 명"}
        )
        st.table(bus_view.reset_index(drop=True))

        # 지도: 마커 + 정류소 번호 + (툴팁에 노선)
        map_df = bus_rows[["lat","lon","정류소명","ARS_ID","노선"]].copy()
        if not map_df.empty:
            view_state = pdk.ViewState(
                latitude=float(map_df["lat"].mean()),
                longitude=float(map_df["lon"].mean()),
                zoom=16
            )
            point_layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position='[lon, lat]',
                get_radius=25,
                get_fill_color=[0, 122, 255, 200],
                pickable=True,
            )
            text_layer = pdk.Layer(
                "TextLayer",
                data=map_df,
                get_position='[lon, lat]',
                get_text="ARS_ID",
                get_color=[0, 0, 0, 255],
                get_size=16,
                get_angle=0,
                get_alignment_baseline='"top"',
                get_pixel_offset=[0, -18],
                billboard=True,
            )
            tooltip = {
                "html": "<b>{정류소명}</b><br/>정류소 번호: {ARS_ID}<br/>노선: {노선}",
                "style": {"backgroundColor": "white", "color": "black"}
            }
            st.pydeck_chart(pdk.Deck(
                layers=[point_layer, text_layer],
                initial_view_state=view_state,
                tooltip=tooltip
            ))

    # (2) 기사 영역 (placeholder)
    st.subheader("집회/시위 관련 기사 보기")
    st.caption("※ 크롤링 연동 예정. 데이터 준비되면 이 영역에 노출됩니다.")
    st.empty()

    # (2.5) 건의사항 키워드 요약 (워드클라우드 + Top N + 예시)
    st.subheader("건의사항 키워드 요약")
    fb_all = load_feedback("data/feedback.csv")
    if fb_all.empty:
        st.caption("아직 저장된 건의사항이 없습니다.")
    else:
        colA, colB = st.columns([1,1])
        with colA:
            only_today = st.toggle("이 날짜만 보기", value=True, key="wc_today")
            use_bigrams = st.toggle("연결어(2단어)로 보기", value=False, key="wc_bigram")
            img = build_wordcloud_image(
                fb_all,
                date_filter=d if only_today else None,
                use_bigrams=use_bigrams,
                font_path="data/Nanum_Gothic/NanumGothic-Regular.ttf"
            )
            if img is not None:
                st.image(img, use_container_width=True)
            else:
                st.caption("워드클라우드를 만들 수 있는 텍스트가 부족합니다.")
        with colB:
            top_df = top_terms_from_feedback(
                fb_all,
                date_filter=d if only_today else None,
                use_bigrams=use_bigrams,
                top_k=20
            )
            if top_df.empty:
                st.caption("표시할 키워드가 없습니다.")
            else:
                st.markdown("**상위 키워드/표현 TOP 20**")
                chart = (
                    alt.Chart(top_df)
                    .mark_bar()
                    .encode(
                        x=alt.X("count:Q", title="건수"),
                        y=alt.Y("term:N", sort="-x", title=None),
                        tooltip=[alt.Tooltip("term:N", title="용어"),
                                 alt.Tooltip("count:Q", title="건수"),
                                 alt.Tooltip("pct:Q", title="비율(%)")]
                    )
                    .properties(height=420)
                )
                st.altair_chart(chart, use_container_width=True)

                sel = st.selectbox("예시 문장 보기: 키워드 선택", ["선택 안 함"] + top_df["term"].tolist())
                if sel != "선택 안 함":
                    _df = fb_all.copy()
                    if only_today and "date" in _df.columns:
                        _df = _df[_df["date"].astype(str) == str(d)]
                    ex = _df[_df["feedback"].str.contains(re.escape(sel), case=False, na=False)] \
                        .tail(5)["feedback"]
                    if ex.empty:
                        st.caption("해당 키워드의 예시가 없습니다.")
                    else:
                        st.markdown("**최근 예시 5건**")
                        for i, line in enumerate(ex, 1):
                            st.write(f"{i}. {line}")

    # (3) 건의사항 입력
    st.subheader("오늘의 집회/시위에 대한 여러분의 건의사항을 남겨주세요")
    fb = st.text_area("의견을 작성해주세요 (관리자에게 전달됩니다)", height=140, key="fb_detail")
    if st.button("등록"):
        if not fb.strip():
            st.warning("내용을 입력해주세요.")
        else:
            save_path = Path("data/feedback.csv")
            save_path.parent.mkdir(parents=True, exist_ok=True)
            row_dict = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "date": str(d),
                "start": row["_start"],
                "end": row["_end"],
                "location": row["_loc"],
                "district": row["_dist"],
                "reported_head": row["_head"],
                "memo": row["_memo"],
                "feedback": fb.strip(),
            }
            if save_path.exists():
                prev = pd.read_csv(save_path)
                new  = pd.concat([prev, pd.DataFrame([row_dict])], ignore_index=True)
            else:
                new = pd.DataFrame([row_dict])
            new.to_csv(save_path, index=False, encoding="utf-8-sig")
            st.success("건의사항이 저장되었습니다. 감사합니다!")
            st.query_params.clear()

# ===================== 메인/라우팅 =====================
st.markdown("<div class='app-header'>집회/시위 알림 서비스</div>", unsafe_allow_html=True)

# 좌/우 높이 동기화
CALENDAR_H = 520
HEADER_OFFSET = 85
PANEL_BODY_H = CALENDAR_H - HEADER_OFFSET   # 오른쪽 스크롤 영역 높이

# 데이터 경로
DATA_PATH = st.sidebar.text_input(
    "집회 데이터 경로 (xlsx/csv)",
    value="data/protest_data.xlsx"
)
BUS_PATH = st.sidebar.text_input(
    "버스 우회 데이터 경로 (xlsx)",
    value="data/bus_data.xlsx"
)
ROUTES_PATH = st.sidebar.text_input(
    "버스 노선 데이터 경로 (CSV: routes_final.csv)",
    value="/Users/byun-yewon/KT_project/routes_final.csv"
)

# 데이터 로드
try:
    df = load_events(DATA_PATH)
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()
bus_df = load_bus(BUS_PATH)
routes_df = load_routes(ROUTES_PATH)

# ---- 라우팅: 쿼리 파라미터(detail 모드) ----
qp = st.query_params
view = qp.get("view", "")
if view == "detail":
    d_str = qp.get("date", "")
    idx_str = qp.get("idx", "0")
    try:
        d_sel = parser.parse(d_str).date()
        idx_sel = int(idx_str)
        render_detail(df, bus_df, routes_df, d_sel, idx_sel)
        st.stop()
    except Exception:
        st.warning("잘못된 링크입니다. 목록으로 돌아갑니다.")
        st.query_params.clear()

# ---------- 메인 화면 ----------
st.markdown("### 이달의 집회")
st.caption("이번 달의 집회를 한눈에 확인해보세요.")

left, right = st.columns(2)

# 왼쪽: 캘린더
with left:
    with st.container(border=True):
        events = df_to_month_dots(df)
        options = {
            "initialView": "dayGridMonth",
            "locale": "ko",
            "height": CALENDAR_H,
            "firstDay": 0,
            "headerToolbar": {"left":"prev,next today", "center":"title", "right":""},
            "dayMaxEventRows": True,
        }
        calendar(events=events, options=options)

# 오른쪽: 날짜 네비 + 카드 목록(HTML 링크, 고정 높이 컨테이너)
if "sel_date" not in st.session_state:
    st.session_state.sel_date = date.today()

with right:
    with st.container(border=True):
        nav1, nav2, nav3, nav4 = st.columns([1, 2.2, 1, 1])
        with nav1:
            if st.button("◀", use_container_width=True):
                d = st.session_state.sel_date
                st.session_state.sel_date = d.fromordinal(d.toordinal() - 1)
        with nav2:
            dnew = st.date_input("날짜 선택", value=st.session_state.sel_date, label_visibility="collapsed")
            if dnew != st.session_state.sel_date:
                st.session_state.sel_date = dnew
        with nav3:
            if st.button("오늘", use_container_width=True):
                st.session_state.sel_date = date.today()
        with nav4:
            if st.button("▶", use_container_width=True):
                d = st.session_state.sel_date
                st.session_state.sel_date = d.fromordinal(d.toordinal() + 1)

        sel_date = st.session_state.sel_date
        WEEK_KO = ["월","화","수","목","금","토","일"]
        st.markdown(f"#### {sel_date.month}월 {sel_date.day}일({WEEK_KO[sel_date.weekday()]}) 집회 일정 안내")

        day_df = filter_by_day(df, sel_date)

        # 공백 없이 스크롤 컨테이너에 카드 HTML을 일괄 삽입
        html = [f"<div style='height:{PANEL_BODY_H}px; overflow-y:auto; padding-right:8px;'>"]

        if len(day_df) == 0:
            html.append('<div class="sub">등록된 집회가 없습니다.</div>')
        else:
            for i, (_, r) in enumerate(day_df.iterrows()):
                # 장소(관할서 있으면 접두)
                loc_line = r["_loc"]
                if r["_dist"] and str(r["_dist"]).strip() not in ["nan", "None", ""]:
                    loc_line = f"{r['_dist']}  {loc_line}"

                # 메타(신고 인원, 메모)
                metas = []
                if pd.notna(r["_head"]) and str(r["_head"]).strip() != "":
                    try:
                        metas.append(f"신고 인원 {int(r['_head'])}명")
                    except:
                        metas.append(f"신고 인원 {r['_head']}명")
                if r["_memo"] and str(r["_memo"]).strip() not in ["nan", "None", ""]:
                    metas.append(str(r["_memo"]))
                meta_text = " · ".join(metas)
                meta_html = f"<div class='meta'>{meta_text}</div>" if meta_text else ""

                href = f"?view=detail&date={sel_date.isoformat()}&idx={i}"

                html.append(textwrap.dedent(f"""
                    <a class="card-link" href="{href}">
                      <div class="card">
                        <div class="time">{r["_start"]} ~ {r["_end"]}</div>
                        <div class="sub">{loc_line}</div>
                        {meta_html}
                      </div>
                    </a>
                """).strip())

        html.append("</div>")
        st.markdown("\n".join(html), unsafe_allow_html=True)
