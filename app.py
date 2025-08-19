# app.py
import os
import re
import textwrap
from pathlib import Path
from datetime import date, datetime
from collections import Counter

import pandas as pd
import streamlit as st
import pydeck as pdk
from dateutil import parser
from streamlit_calendar import calendar
import base64

# ====== Chatbot deps ======
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv

# .env 로드 및 KEY 확인
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise ValueError("❌ OPENAI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

# --- optional: wordcloud ---
try:
    from wordcloud import WordCloud
    WORDCLOUD_AVAILABLE = True
except Exception:
    WORDCLOUD_AVAILABLE = False

st.set_page_config(page_title="집회/시위 알림 서비스", page_icon="📅", layout="wide")

# ====================== 스타일 ======================
def get_base64_of_image(path):
    with open(path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

logo_base64 = get_base64_of_image("data/assets/logo.png")
# ====================== 헤더 이미지 ======================
st.markdown(
    f"""
    <div style='display:flex; justify-content:left; align-items:left; padding:10px;'>
        <img src="data:image/png;base64,{logo_base64}" alt="Logo" style="height:60px;">
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("""
<style>
  .stApp, .main, [data-testid="stHeader"] { background:#ffffff !important; }

  /* 상단 타이틀 */
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
  a.card-link { display:block; text-decoration:none; color:inherit; }
  a.card-link .card:hover { border-color:#94a3b8; background:#f8fafc; }

  /* 달력 도트 전용 */
  .fc .fc-daygrid-dot-event .fc-event-time,
  .fc .fc-daygrid-dot-event .fc-event-title,
  .fc .fc-daygrid-event-harness .fc-event-time,
  .fc .fc-daygrid-event-harness .fc-event-title { display:none !important; }
  .fc-daygrid-dot-event > .fc-event-dot { width:10px; height:10px; border:0; }
            
/* FullCalendar 이전/다음 버튼 커스텀 */
/* 이전 버튼 (◀) */
.fc .fc-prev-button .fc-icon {
  display: none !important;
}
.fc .fc-prev-button:before {
  content: "◀" !important;
  font-size: 22px;   /* 크기 조정 */
  color: #000;       /* 화살표 색 */
}

/* 다음 버튼 (▶) */
.fc .fc-next-button .fc-icon {
  display: none !important;
}
.fc .fc-next-button:before {
  content: "▶" !important;
  font-size: 22px;
  color: #000;
}      
.fc-daygrid-more-link {
  font-size: 12px;
  color: #000;
}

.fc-daygrid-more-link::after {
  content: "" !important;  /* 뒤에 붙는 " more" 제거 */
}

  /* ===== Chat (테두리 프레임 없음) ===== */
  .chat-wrap { margin-top:4px; }
  .chat-scroll{
    height:100px;
    overflow-y:auto;
    padding:15px 20px 0 20px;
    background:#ffffff;
  }
  .msg-row{ display:flex; margin:10px 0; }
  .msg-row.user{ justify-content:flex-end; }
  .bubble{
    max-width:560px;
    padding:15px 20px;
    border-radius:16px;
    font-size:18px; line-height:1.5;
    word-break:break-word; white-space:pre-wrap;
  }
  .bubble.user{ background:#2A52BF; color:#fff; }
  .bubble.bot { background:#eeeeee; color:#000; }

  /* ===== 입력줄 ===== */
.chat-input-area { padding:12px 20px 8px 20px; }

/* 바깥 wrapper 완전 제거 */
div.stTextInput,
div.stTextInput > div {
    border:none;
    background: #fff;
},
div.stTextInput > div > div {
    background: transparent !important;
    border: 1px solid #000
    box-shadow: none !important;
    padding: 0 !important;
}

/* 입력창 흰색 + 둥근 테두리 */
div[data-baseweb="input"] > div {
    background: #fff !important;
    border: 1px solid #000 !important;
    border-radius: 100px !important;
    padding: 10px 15px !important;
    color: #000;
    font-size: 16px;
}

  /* 버튼 스타일 */
  div.stButton > button {
    background-color: var(--blue);
    color: #000;
    border-radius: 100px;
    border: 1px solid #000;
    font-weight: 600;
    font-size: 16px;
  }
  div.stButton > button:hover {
    background-color: #1d3e91;
    border: 1px solid #1d3e91;
    color: #fff;
  }
</style>

""", unsafe_allow_html=True)



# ====================== 데이터 로드 ======================
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
    p = Path(path)
    if not p.exists(): return pd.DataFrame()
    df = pd.read_excel(p)

    def to_date(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', s): s = s.replace(".", "-")
        try: return parser.parse(s).date()
        except: return None
    def to_time(x):
        if pd.isna(x): return None
        try:
            t = parser.parse(str(x)).time()
            return f"{t.hour:02d}:{t.minute:02d}"
        except: return None

    cols = {c: str(c).strip().lower() for c in df.columns}
    def pick(*names):
        for n in names:
            for c, lc in cols.items():
                if lc == n: return c
        return None

    c_sd = pick("start_date","시작일"); c_st = pick("start_time","시작시간")
    c_ed = pick("end_date","종료일");   c_et = pick("end_time","종료시간")
    c_ars= pick("ars_id","ars","정류장id")
    c_nm = pick("정류소명","정류장명","stop_name")
    c_x  = pick("x좌표","x","lon","lng"); c_y  = pick("y좌표","y","lat")
    if any(c is None for c in [c_sd,c_st,c_ed,c_et,c_ars,c_nm,c_x,c_y]): return pd.DataFrame()

    ars_series = df[c_ars].astype(str).map(lambda s: re.sub(r"\D", "", s)).map(lambda s: s.zfill(5))
    out = pd.DataFrame({
        "start_date": df[c_sd].apply(to_date),
        "start_time": df[c_st].apply(to_time),
        "end_date":   df[c_ed].apply(to_date),
        "end_time":   df[c_et].apply(to_time),
        "ARS_ID":     ars_series,
        "정류소명":     df[c_nm].astype(str),
        "lon":        pd.to_numeric(df[c_x], errors="coerce"),
        "lat":        pd.to_numeric(df[c_y], errors="coerce"),
    })
    return out.dropna(subset=["start_date","end_date","lon","lat"]).reset_index(drop=True)

@st.cache_data
def load_routes(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists(): return pd.DataFrame(columns=["date","ars_id","route"])
    df = pd.read_csv(p, dtype={"ars_id": str, "route": str})

    def to_date(x):
        try: return parser.parse(str(x)).date()
        except Exception: return None

    df["date"] = df["date"].apply(to_date)
    df["ars_id"] = df["ars_id"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(5)
    df["route"]  = df["route"].fillna("").astype(str).str.strip()
    return df.dropna(subset=["date","ars_id"]).reset_index(drop=True)

def color_by_headcount(h):
    try:
        n = int(h)
        if n >= 1000: return "#ef4444"
        if n >= 500:  return "#f59e0b"
        return "#3b82f6"
    except: return "#3b82f6"

def df_to_month_dots(df: pd.DataFrame):
    events=[]
    for _, r in df.iterrows():
        start_iso=f"{r['_date']}T{r['_start']}:00"
        end_iso  =f"{r['_date']}T{r['_end']}:00"
        events.append({"title":"", "start":start_iso, "end":end_iso,
                       "display":"list-item", "color":color_by_headcount(r["_head"])})
    return events

def filter_by_day(df: pd.DataFrame, d: date)->pd.DataFrame:
    return df[df["_date"]==d].sort_values(by=["_start","_end","_loc"])

def get_bus_rows_for_date(bus_df: pd.DataFrame, d: date)->pd.DataFrame:
    if bus_df is None or bus_df.empty: return pd.DataFrame()
    return bus_df[(bus_df["start_date"]<=d)&(bus_df["end_date"]>=d)].copy()

# ---------------- 텍스트 전처리 ----------------
_STOPWORDS = {
    "그리고","그러나","하지만","또는","및","때문","때문에","대한","관련","대해",
    "여러분","정도","부분","등","좀","너무","수","것","거","이것","저것","우리",
    "입니다","합니다","하는","있는","되는","됩니다","드립니다","해주시면","해주십시오",
    "해주세요","부탁드립니다","같습니다","감사합니다","감사하겠습니다","불편합니다",
    "입니다만","않습니다","않아요","않구요","됩니다만",
    "으로","로","에서","에게","에는","에","의","을","를","이","가","와","과","도","만","보다",
}
_SUFFIX_PAT = re.compile(
    r"(입니다|합니다|십시오|해주세요|해주시기|해주시길|해주시면|해주십시오|"
    r"되겠습니다|되었습|되었으면|되면|되어|되었습니다|되는데|않습니다|않아요|"
    r"같습니다|하겠습니다|부탁드립니다|감사합니다|감사하겠습니다|해요|했어요|합니다만)$"
)
def strip_suffix(tok:str)->str: return re.sub(_SUFFIX_PAT, "", tok)

def tokenize_ko(s:str):
    if not isinstance(s,str): return []
    cand = re.findall(r"[가-힣A-Za-z0-9]+", s)
    out=[]
    for t in cand:
        t=strip_suffix(t)
        if len(t)<2: continue
        if t in _STOPWORDS: continue
        out.append(t)
    return out

def make_bigrams(tokens, join_str=" "): return [join_str.join(p) for p in zip(tokens,tokens[1:])]

def build_wordcloud_image(fb_df, date_filter=None, use_bigrams=False,
                          font_path="data/Nanum_Gothic/NanumGothic-Regular.ttf"):
    if not WORDCLOUD_AVAILABLE: return None
    if fb_df is None or fb_df.empty or "feedback" not in fb_df.columns: return None
    df = fb_df.copy()
    if date_filter is not None and "date" in df.columns:
        df = df[df["date"].astype(str)==str(date_filter)]
    texts = df["feedback"].dropna().astype(str).tolist()
    if not texts: return None
    counter=Counter()
    for t in texts:
        toks = tokenize_ko(t)
        if use_bigrams: toks = make_bigrams(toks)
        counter.update(toks)
    if not counter: return None
    fp = font_path if Path(font_path).exists() else None
    wc = WordCloud(font_path=fp, width=1200, height=600, background_color="white", colormap="tab20c")
    return wc.generate_from_frequencies(counter).to_image()

def load_feedback(path="data/feedback.csv"):
    p=Path(path)
    if not p.exists(): return pd.DataFrame()
    try: return pd.read_csv(p)
    except Exception: return pd.DataFrame()

# ---------- 지식(텍스트) 로드 ----------
@st.cache_data
def load_all_txt(data_dir="data/chatbot"):
    texts=[]; p=Path(data_dir)
    if not p.exists(): return ""
    for path in p.glob("*.txt"):
        try:
            with open(path,"r",encoding="utf-8") as f: texts.append(f.read())
        except Exception as e: st.warning(f"{path} 읽기 오류: {e}")
    return "\n\n".join(texts)

all_texts = load_all_txt()

# ====================== 상세 페이지 ======================
def render_detail(df_all: pd.DataFrame, bus_df: pd.DataFrame, routes_df: pd.DataFrame, d: date, idx: int):
    day_df = filter_by_day(df_all, d)
    if len(day_df)==0 or idx<0 or idx>=len(day_df):
        st.error("상세 정보를 찾을 수 없어요.")
        if st.button("← 목록으로"):
            st.query_params.clear(); st.rerun()
        return
    if st.button("← 목록으로"):
        st.query_params.clear(); st.rerun()
    row = day_df.iloc[idx]
    WEEK_KO=["월","화","수","목","금","토","일"]
    st.markdown(f"#### {d.month}월 {d.day}일({WEEK_KO[d.weekday()]}) 상세 정보")


    st.markdown("###### 오늘의 집회/시위")
    time_str=f"{row['_start']} ~ {row['_end']}"
    loc_str = f"{(row['_dist']+' ') if row['_dist'] not in ['','nan','None'] else ''}{row['_loc']}"
    if pd.notna(row["_head"]) and str(row["_head"]).strip()!="":
        try: head_str=f"{int(row['_head'])}명"
        except: head_str=f"{row['_head']}명"
    else: head_str=""
    keywords = str(row["_memo"]).strip() if str(row["_memo"]).strip() not in ["nan","None"] else ""
    info_df = pd.DataFrame([[time_str, loc_str, head_str, keywords]],
                           columns=["집회 시간","집회 장소(행진로)","신고 인원","관련 이슈"])
    st.table(info_df)

    st.markdown("###### 버스 우회 정보")
    bus_rows = get_bus_rows_for_date(bus_df, d)
    route_slice = routes_df[routes_df["date"]==d].copy() if routes_df is not None and not routes_df.empty else pd.DataFrame()

    if bus_rows.empty:
        st.caption("※ 해당 날짜의 버스 우회 정보가 없습니다.")
    else:
        if not route_slice.empty:
            agg = (route_slice.dropna(subset=["ars_id","route"])
                   .groupby("ars_id")["route"].apply(lambda s:", ".join(sorted(set(s))))).rename("노선")
            bus_rows = bus_rows.merge(agg, left_on="ARS_ID", right_index=True, how="left")
        else:
            bus_rows["노선"]=""

        bus_view = bus_rows[["start_time","end_time","ARS_ID","정류소명","노선"]].rename(
            columns={"start_time":"시작 시간","end_time":"종료 시간","ARS_ID":"버스 정류소 번호","정류소명":"버스 정류소 명"})
        st.table(bus_view.reset_index(drop=True))

        map_df = bus_rows[["lat","lon","정류소명","ARS_ID","노선"]].copy()
        if not map_df.empty:
            view_state = pdk.ViewState(latitude=float(map_df["lat"].mean()),
                                       longitude=float(map_df["lon"].mean()), zoom=16)
            point_layer = pdk.Layer("ScatterplotLayer", data=map_df,
                                    get_position='[lon, lat]', get_radius=25,
                                    get_fill_color=[0,122,255,200], pickable=True)
            tooltip = {"html":"<b>{정류소명}</b><br/>정류소 번호: {ARS_ID}<br/>노선: {노선}",
                       "style":{"backgroundColor":"white","color":"black"}}
            st.pydeck_chart(pdk.Deck(layers=[point_layer], initial_view_state=view_state, tooltip=tooltip, map_style="road"))
    st.markdown("###### 집회/시위 관련 기사 보기")
    st.caption("※ 크롤링 연동 예정. 데이터 준비되면 이 영역에 노출됩니다.")
    st.empty()

    # --- 피드백 작성/저장 ---
    st.markdown("###### 오늘의 집회/시위에 대한 여러분의 건의사항을 남겨주세요")

    with st.form("feedback_form", clear_on_submit=True):
        fb = st.text_area("의견을 작성해주세요 (관리자에게 전달됩니다)", height=80, key="fb_detail")
        submitted = st.form_submit_button("등록")

    if submitted:
        if not fb.strip():
            st.warning("내용을 입력해주세요.")
        else:
            save_path = Path("data/feedback.csv"); save_path.parent.mkdir(parents=True, exist_ok=True)
            from hashlib import md5
            row_key = f"{str(d)}|{row.get('_start')}|{row.get('_end')}|{row.get('_loc')}|{fb.strip()}"
            dupe_key = md5(row_key.encode("utf-8")).hexdigest()

            df_now = load_feedback(str(save_path))
            if "dupe_key" not in df_now.columns: df_now["dupe_key"] = ""
            if dupe_key in set(df_now["dupe_key"].astype(str)):
                st.info("이미 같은 내용이 저장되어 있습니다.")
            else:
                row_dict = {
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                    "date": str(d), "start": row.get("_start",""), "end": row.get("_end",""),
                    "location": row.get("_loc",""), "district": row.get("_dist",""),
                    "reported_head": row.get("_head",""), "memo": row.get("_memo",""),
                    "feedback": fb.strip(), "dupe_key": dupe_key,
                }
                pd.concat([df_now, pd.DataFrame([row_dict])], ignore_index=True)\
                .to_csv(save_path, index=False, encoding="utf-8-sig")
                st.success("건의사항이 저장되었습니다. 감사합니다!")

    # --- 건의사항 키워드 요약 ---
    st.markdown("###### 건의사항 키워드 요약")
    fb_all = load_feedback("data/feedback.csv")
    if fb_all.empty:
        st.caption("아직 저장된 건의사항이 없습니다.")
    else:
        only_today  = st.toggle("이 날짜만 보기", value=True,  key="wc_today_only")
        use_bigrams = st.toggle("연결어(2단어)로 보기", value=False, key="wc_bigram_only")
        img = build_wordcloud_image(
            fb_all, date_filter=d if only_today else None,
            use_bigrams=use_bigrams, font_path="data/Nanum_Gothic/NanumGothic-Regular.ttf"
        )
        st.image(img, use_container_width=True) if img is not None else st.caption("워드클라우드 데이터가 부족합니다.")


# ====================== 메인 화면 ======================
def render_main_page(df, bus_df, routes_df):
    st.markdown("### 이달의 집회")
    st.caption("이번 달의 집회를 한눈에 확인해보세요.")
    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            events = df_to_month_dots(df)
            options = {
                "initialView": "dayGridMonth",
                "locale": "ko",
                "height": CALENDAR_H,
                "firstDay": 0,
                "headerToolbar": {
                    "left": "prev",
                    "center": "title",
                    "right": "next"
                },
                "buttonIcons": {   # 기본 아이콘 없애기
                    "prev": "",
                    "next": ""
                },
                "dayMaxEventRows": True,
            }
            calendar(events=events, options=options, custom_css="""
/* 버튼 기본 스타일 */
.fc .fc-button {
    background: #fff !important;
    border: 1px solid #000 !important;
    color: #000 !important;
    border-radius: 50% !important;
    width: 40px !important;
    height: 40px !important;
    font-size: 16px !important;
    display: flex !important;
    justify-content: center !important;
    align-items: center !important;
    padding: 0 !important;
}

/* 기존 아이콘 숨기기 */
.fc .fc-icon {
    display: none !important;
}

/* prev 버튼 */
.fc .fc-prev-button:after {
  content: "◀";
  font-size: 20px;
  color: #000;
}

/* next 버튼 */
.fc .fc-next-button:after {
  content: "▶";
  font-size: 20px;
  color: #000;
}

/* "더보기" 링크 스타일 */
.fc-daygrid-more-link {
  white-space: pre-line !important;  /* 공백을 줄바꿈으로 처리 */
  font-size: 14px !important;
  line-height: 1.2 !important;
}

/* 'more' 앞에 줄바꿈 넣기 */
.fc-daygrid-more-link::before {
  content: attr(aria-label);
  white-space: pre-line;
}
""")

    if "sel_date" not in st.session_state: st.session_state.sel_date = date.today()

    with right:
        with st.container(border=True):
            nav1, nav2, nav3 = st.columns([1, 1, 1])
            with nav1:
                if st.button("◀", use_container_width=True):
                    d=st.session_state.sel_date; st.session_state.sel_date=d.fromordinal(d.toordinal()-1)
            with nav2:
                if st.button("오늘", use_container_width=True): st.session_state.sel_date=date.today()
            with nav3:
                if st.button("▶", use_container_width=True):
                    d=st.session_state.sel_date; st.session_state.sel_date=d.fromordinal(d.toordinal()+1)

            sel_date = st.session_state.sel_date
            WEEK_KO=["월","화","수","목","금","토","일"]
            st.markdown(f"#### {sel_date.month}월 {sel_date.day}일({WEEK_KO[sel_date.weekday()]}) 집회 일정 안내")

            day_df = filter_by_day(df, sel_date)
            html=[f"<div style='height:{PANEL_BODY_H}px; overflow-y:auto; padding-right:8px;'>"]
            if len(day_df)==0:
                html.append('<div class="sub">등록된 집회가 없습니다.</div>')
            else:
                for i,(_,r) in enumerate(day_df.iterrows()):
                    loc_line = r["_loc"]
                    if r["_dist"] and str(r["_dist"]).strip() not in ["nan","None",""]:
                        loc_line = f"{r['_dist']}  {loc_line}"
                    metas=[]
                    if pd.notna(r["_head"]) and str(r["_head"]).strip()!="":
                        try: metas.append(f"신고 인원 {int(r['_head'])}명")
                        except: metas.append(f"신고 인원 {r['_head']}명")
                    if r["_memo"] and str(r["_memo"]).strip() not in ["nan","None",""]:
                        metas.append(str(r["_memo"]))
                    meta_text=" · ".join(metas)
                    meta_html=f"<div class='meta'>{meta_text}</div>" if meta_text else ""
                    href=f"?view=detail&date={sel_date.isoformat()}&idx={i}"
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

# ====================== 챗봇 (프레임 없음/정렬 반영) ======================
if "chat_history" not in st.session_state:
    st.session_state.chat_history=[]
if "input_counter" not in st.session_state:
    st.session_state.input_counter=0

def render_chatbot_page():
    # 헤드라인
    st.subheader("버스 우회 정보 확인하기")
    st.markdown("###### 챗봇에게 내가 타는 버스의 우회 정보를 물어보세요.")

    # 스크롤 되는 본문 (프레임/테두리 없음)
    st.markdown('<div class="chat-wrap"><div class="chat-scroll" id="chat-scroll">', unsafe_allow_html=True)

    if not st.session_state.chat_history:
        st.session_state.chat_history.append((
            "bot",
            "안녕하세요! 날짜와 노선을 알려주시면 우회 정보를 찾아드릴게요.\n예) 8월 15일 172번 우회 알려줘"
        ))

    # 풍선 렌더링: 사용자=오른쪽 파란색, 시스템=왼쪽 회색
    for role, msg in st.session_state.chat_history:
        row_cls = "msg-row user" if role=="user" else "msg-row"
        bub_cls = "bubble user" if role=="user" else "bubble bot"
        st.markdown(f'<div class="{row_cls}"><div class="{bub_cls}">{msg}</div></div>', unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)

    # 입력줄 (프레임 밖 하단, 테두리 없음)
    st.markdown('<div class="chat-input-area">', unsafe_allow_html=True)
    c1, c2 = st.columns([8,1])
    with c1:
        user_input = st.text_input(
            "예: 8월 15일의 172번 버스 우회 정보를 알려줘",
            key=f"chat_input_{st.session_state.input_counter}",
            label_visibility="collapsed",
        )
    with c2:
        send = st.button("전송", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # 전송
    if send and user_input.strip():
        st.session_state.chat_history.append(("user", user_input))
        if all_texts:
            llm = ChatOpenAI(model_name="gpt-4o-mini", api_key=API_KEY)
            prompt_template = PromptTemplate(
                input_variables=["context","question"],
                template="""
당신은 주어진 텍스트를 기반으로 질문에 답하는 Q&A 챗봇입니다.  
아래는 참고할 수 있는 텍스트입니다:

{context}

---

질문: {question}
답변(텍스트 기반으로만, 사실에 맞게 작성):
                """,
            )
            prompt = prompt_template.format(context=all_texts, question=user_input)
            with st.spinner("답변 작성 중..."):
                response = llm.predict(prompt)
        else:
            response = "❌ 텍스트 데이터가 없어서 답변할 수 없습니다."
        st.session_state.chat_history.append(("bot", response))
        st.session_state.input_counter += 1
        st.rerun()

# ====================== 라우팅 ======================

CALENDAR_H = 520
HEADER_OFFSET = 85
PANEL_BODY_H = CALENDAR_H - HEADER_OFFSET

# 경로
DATA_PATH   = st.sidebar.text_input("집회 데이터 경로 (xlsx/csv)", value="data/protest_data.xlsx")
BUS_PATH    = st.sidebar.text_input("버스 우회 데이터 경로 (xlsx)", value="data/bus_data.xlsx")
ROUTES_PATH = st.sidebar.text_input("버스 노선 데이터 경로 (CSV: routes_final.csv)", value="routes_final.csv")

# 로드
try:
    df        = load_events(DATA_PATH)
    bus_df    = load_bus(BUS_PATH)
    routes_df = load_routes(ROUTES_PATH)
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# 상세/목록
qp = st.query_params
if qp.get("view","") == "detail":
    try:
        d_sel = parser.parse(qp.get("date","")).date()
        idx_sel = int(qp.get("idx","0"))
        render_detail(df, bus_df, routes_df, d_sel, idx_sel)
    except Exception:
        st.warning("잘못된 링크입니다. 목록으로 돌아갑니다.")
        st.query_params.clear()
else:
    render_main_page(df, bus_df, routes_df)
    # 챗봇
    render_chatbot_page()

# ====================== 푸터 ======================
jongno_logo = get_base64_of_image("data/assets/jongno_logo.png")
kt_logo = get_base64_of_image("data/assets/kt_logo.png")

st.markdown(
    f"""
    <style>
      .site-footer {{
        margin-top: 200px;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        overflow: hidden;
      }}
      .site-footer .footer-top {{
        background: #575757;
        color: #ffffff;
        text-align: center;
        padding: 22px 16px 20px 16px;
        line-height: 1.5;
        font-size: 15px;
      }}
      .site-footer .footer-top .title {{
        font-weight: 700;
        letter-spacing: 0.2px;
        margin-bottom: 4px;
        display: block;
      }}
      .site-footer .footer-top .copy {{
        font-size: 13px;
        opacity: 0.95;
      }}
      .site-footer .footer-bottom {{
        background: #ffffff;
        padding: 18px 22px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }}
      .site-footer .bottom-left {{
        color: #111827;
        font-size: 14px;
        line-height: 1.6;
      }}
      .site-footer .bottom-left .who {{
        font-weight: 700;
        margin-bottom: 4px;
      }}
      .site-footer .bottom-right {{
        display: flex;
        align-items: center;
        gap: 22px;
      }}
      .site-footer .bottom-right img {{
        height: 40px;
        display: block;
      }}
      @media (max-width: 720px) {{
        .site-footer .footer-bottom {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
      }}
    </style>

    <div class="site-footer">
      <div class="footer-top">
        <span class="title">종로구청 × KT디지털인재장학생 5조</span>
        <span class="copy">© 2025 KT디지털인재장학생 5조 All rights reserved</span>
      </div>

      <div class="footer-bottom">
        <div class="bottom-left">
          <div class="who">서비스를 제작한 사람들</div>
          <div>KT 디지털인재장학생 | 강혜선 김민영 변예원 이은서 장진영 한태희</div>
        </div>
        <div class="bottom-right">
          <img src="data:image/png;base64,{jongno_logo}" alt="종로구 로고" />
          <img src="data:image/png;base64,{kt_logo}" alt="KT 로고" />
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)