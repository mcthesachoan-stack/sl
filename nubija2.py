import math
import time
import requests
import pandas as pd
import streamlit as st
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh
 
# ----------------------------------------------------------------------------
# 0. 기본 설정
# ----------------------------------------------------------------------------
st.set_page_config(page_title="창원시 누비자 가까운 대여소 찾기", page_icon="🚲", layout="wide")
 
CHANGWON_CENTER = (35.2280, 128.6811)  # 창원시청 근처 좌표 (GPS를 못 받았을 때 기본값)
DATA_PATH = "data/nubija_stations.xlsx"  # 창원시 제공 실제 누비자 터미널 데이터(2025.12.31 기준, 372곳)
NEAREST_N = 5  # 가까운 대여소를 몇 개까지 보여줄지
 
 
# ----------------------------------------------------------------------------
# 1. 대여소 데이터 불러오기
#    - 실제 수업/서비스에서는 공공데이터포털에서 내려받은
#      "경상남도 창원시_누비자 터미널" 파일(XLSX)을 그대로 올리면 된다.
#    - 컬럼 이름이 파일마다 조금씩 다를 수 있어서, 아래 매핑표로 흡수한다.
# ----------------------------------------------------------------------------
# 행정안전부 "전국자전거대여소표준데이터" - 전국 지자체 공영자전거 대여소를 표준 형식으로 모아 제공.
# 요청주소가 고정되어 있어서, 사용자는 인증키만 발급받으면 된다.
NUBIJA_OPENAPI_BASE_URL = "https://api.data.go.kr/openapi/tn_pubr_public_bcycl_lend_api"
 
COLUMN_ALIASES = {
    "name": ["대여소명", "터미널명", "정류장명", "station_name", "name", "자전거대여소명"],
    "lat": ["위도", "lat", "latitude", "Y좌표"],
    "lon": ["경도", "lon", "lng", "longitude", "X좌표"],
    "address": ["주소", "소재지", "address", "소재지도로명주소", "소재지지번주소"],
    "capacity": ["거치대수", "보관대수", "정원", "capacity"],
    "org": ["관리기관명", "org"],  # 어느 지자체가 관리하는 대여소인지 (전국 데이터에서 창원만 걸러낼 때 사용)
    "status": ["사용유무", "status"],  # 실제 창원시 데이터의 운영 상태(사용함/사용안함)
}
 
 
def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None
 
 
def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for std_col, aliases in COLUMN_ALIASES.items():
        found = _find_column(df, aliases)
        if found:
            rename_map[found] = std_col
    df = df.rename(columns=rename_map)
 
    required = {"name", "lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing} (대여소명/위도/경도에 해당하는 열이 있는지 확인하세요)")
 
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
 
    # 창원시 실제 데이터에는 '사용유무' 컬럼이 있어서, 폐쇄된(사용안함) 대여소는 기본적으로 제외한다.
    if "status" in df.columns:
        before = len(df)
        df = df[~df["status"].astype(str).str.contains("안함|폐쇄|중지", na=False)].reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            st.caption(f"운영 중지된 대여소 {removed}곳은 목록에서 제외했습니다.")
 
    return df
 
 
@st.cache_data(show_spinner="공공데이터포털 OpenAPI에서 대여소 정보를 받아오는 중...")
def load_stations_from_openapi(service_key: str, org_keyword: str = "창원", page_size: int = 1000) -> pd.DataFrame:
    """행정안전부 '전국자전거대여소표준데이터' OpenAPI를 호출해서
    관리기관명에 org_keyword(기본값 '창원')가 포함된 대여소만 걸러서 돌려준다.
    요청주소는 고정되어 있으므로 사용자는 인증키(service_key)만 입력하면 된다.
    """
    all_rows: list[dict] = []
    page_no = 1
    while True:
        params = {
            "serviceKey": service_key,
            "pageNo": page_no,
            "numOfRows": page_size,
            "type": "json",
        }
        res = requests.get(NUBIJA_OPENAPI_BASE_URL, params=params, timeout=10)
        res.raise_for_status()
        payload = res.json()
 
        # 공공데이터포털 응답 구조는 대개 response.body.items.item 형태이지만,
        # 기관마다 조금씩 달라서 여러 경로를 순서대로 시도한다.
        items = (
            payload.get("response", {}).get("body", {}).get("items", {}).get("item")
            or payload.get("body", {}).get("items")
            or payload.get("items")
        )
        if not items:
            break
        if isinstance(items, dict):
            items = [items]
 
        all_rows.extend(items)
        if len(items) < page_size:
            break
        page_no += 1
        if page_no > 30:  # 안전장치: 무한루프 방지 (전국 데이터라 페이지가 많을 수 있음)
            break
 
    if not all_rows:
        raise ValueError("OpenAPI 응답에서 데이터를 찾지 못했습니다. 인증키가 올바른지, 승인이 완료됐는지 확인해주세요.")
 
    df = pd.DataFrame(all_rows)
    df = _standardize_columns(df)
 
    if "org" in df.columns and org_keyword:
        filtered = df[df["org"].astype(str).str.contains(org_keyword, na=False)]
        if len(filtered) > 0:
            df = filtered
        else:
            st.warning(f"관리기관명에 '{org_keyword}'가 포함된 대여소를 찾지 못해 전체 데이터를 보여드립니다.")
 
    return df.reset_index(drop=True)
 
 
@st.cache_data(show_spinner=False)
def load_stations(uploaded_bytes: bytes | None, uploaded_name: str | None) -> pd.DataFrame:
    """업로드된 파일이 있으면 그것을, 없으면 샘플 데이터를 읽어서
    name / lat / lon / address / capacity 라는 표준 컬럼으로 통일해서 돌려준다."""
    if uploaded_bytes is not None:
        if uploaded_name.endswith(".xlsx"):
            df = pd.read_excel(uploaded_bytes)
        else:
            df = pd.read_csv(uploaded_bytes)
    else:
        df = pd.read_excel(DATA_PATH)
 
    return _standardize_columns(df)
 
 
# ----------------------------------------------------------------------------
# 2. 거리 계산 - 하버사인(Haversine) 공식
#    지구는 평평한 종이가 아니라 둥근 공이기 때문에,
#    두 좌표 사이의 실제 거리를 재려면 구면 위의 거리 공식을 써야 한다.
# ----------------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000  # 지구 반지름(m)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
 
 
# ----------------------------------------------------------------------------
# 3. OSRM 보행자 경로 API 호출
#    무료 공개 데모 서버라서 수업용 데모에는 충분하지만,
#    실서비스라면 자체 서버를 두거나 카카오/티맵 API로 바꾸는 것을 권장한다.
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=300)
def get_walking_route(start_lat, start_lon, end_lat, end_lon):
    url = (
        f"https://router.project-osrm.org/route/v1/foot/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=full&geometries=geojson"
    )
    res = requests.get(url, timeout=6)
    res.raise_for_status()
    data = res.json()
    if data.get("code") != "Ok":
        return None
    route = data["routes"][0]
    coords = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    return {
        "coords": coords,
        "distance_m": route["distance"],
        "duration_s": route["duration"],
    }
 
 
# ----------------------------------------------------------------------------
# 3-1. Tmap 보행자 경로안내 API - 인도/횡단보도/육교/지하보도/계단을 구분해서 안내
#    OSRM은 도로망 데이터를 그대로 따라가서 "차도를 걷는 것"처럼 보이지만,
#    Tmap 보행자 API는 실제 인도(보도) 폴리곤 데이터를 갖고 있어서
#    "인도로 걷다가, 정해진 횡단보도에서만 차도를 건너는" 형태로 경로를 만들어준다.
# ----------------------------------------------------------------------------
TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
 
# 구간 종류별 표시 스타일 (지도에 그릴 때 사용)
SEGMENT_STYLE = {
    "sidewalk":   {"color": "#2ECC71", "label": "인도 · 보행로", "dash": None},
    "crosswalk":  {"color": "#E74C3C", "label": "횡단보도(차도 횡단)", "dash": "1,8"},
    "overpass":   {"color": "#7F8C8D", "label": "육교", "dash": "6,4"},
    "underpass":  {"color": "#7F8C8D", "label": "지하보도", "dash": "6,4"},
    "stairs":     {"color": "#8E44AD", "label": "계단", "dash": "2,6"},
    "bike":       {"color": "#3498DB", "label": "자전거도로", "dash": "8,4"},
}
 
 
def _classify_segment(props: dict) -> str:
    """Tmap 응답의 텍스트 속성을 보고 이 구간이 인도인지 횡단보도인지 등을 판별한다."""
    text = " ".join(str(props.get(k, "")) for k in ("facilityName", "description", "name", "roadName"))
    if "횡단보도" in text:
        return "crosswalk"
    if "지하보도" in text or "지하차도" in text:
        return "underpass"
    if "육교" in text:
        return "overpass"
    if "계단" in text:
        return "stairs"
    if "자전거" in text:
        return "bike"
    return "sidewalk"
 
 
@st.cache_data(show_spinner=False, ttl=300)
def get_walking_route_tmap(app_key: str, start_lat, start_lon, end_lat, end_lon):
    """Tmap 보행자 경로안내 API를 호출해서, 인도/횡단보도 등으로 구분된 구간 리스트를 돌려준다."""
    # 복사/붙여넣기 과정에서 앞뒤 공백이나 줄바꿈이 섞여 들어오면
    # requests가 "Invalid leading whitespace..." 에러를 내므로 여기서 한 번 더 정리한다.
    app_key = (app_key or "").strip()
    if not app_key:
        raise ValueError("Tmap appKey가 비어 있습니다.")
 
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "appKey": app_key,
    }
    body = {
        "startX": start_lon, "startY": start_lat,
        "endX": end_lon, "endY": end_lat,
        "startName": "출발", "endName": "도착",
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "searchOption": "0",  # 0: 추천(최단시간) 경로
    }
    res = requests.post(f"{TMAP_PEDESTRIAN_URL}?version=1", headers=headers, json=body, timeout=8)
    res.raise_for_status()
    data = res.json()
 
    features = data.get("features")
    if not features:
        # 인증키 오류 등으로 실패하면 Tmap이 {"error": {...}} 형태로 응답한다.
        err = data.get("error", {}).get("message", "알 수 없는 오류")
        raise ValueError(f"Tmap 응답 오류: {err}")
 
    total_distance, total_time = None, None
    segments = []
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry", {})
        if geom.get("type") == "Point" and props.get("pointIndex") == 0:
            total_distance = props.get("totalDistance")
            total_time = props.get("totalTime")
        elif geom.get("type") == "LineString":
            coords = [(lat, lon) for lon, lat in geom["coordinates"]]
            segments.append({
                "coords": coords,
                "type": _classify_segment(props),
                "distance": props.get("distance", 0) or 0,
            })
 
    if not segments:
        return None
    if total_distance is None:
        total_distance = sum(s["distance"] for s in segments)
 
    return {"segments": segments, "distance_m": total_distance, "duration_s": total_time or 0}
 
 
# ----------------------------------------------------------------------------
# 4. 화면 구성 시작
# ----------------------------------------------------------------------------
st.title("🚲 창원시 누비자 - 내 주변 가까운 대여소 찾기")
st.caption("현재 위치 기준으로 가까운 누비자 대여소를 찾고, 선택한 대여소까지 걸어가는 경로를 실시간으로 지도에 표시합니다.")
 
# session_state 초기값 준비
# - target: 사용자가 "경로 보기"로 확정한 목적지(대여소). 목록 정렬이 바뀌어도 유지된다.
# - tracking: 실시간 위치 추적 on/off
# - trail: 지금까지 실제로 이동한 GPS 좌표 기록 (걸어온 길을 보여주기 위함)
if "target" not in st.session_state:
    st.session_state.target = None
if "tracking" not in st.session_state:
    st.session_state.tracking = False
if "trail" not in st.session_state:
    st.session_state.trail = []
 
with st.sidebar:
    st.header("⚙️ 설정")
 
    data_source = st.radio(
        "대여소 데이터를 어떻게 불러올까요?",
        ["창원시 실제 데이터 (기본 제공, 342곳)", "파일 업로드 (최신 XLSX/CSV로 교체)", "공공데이터포털 OpenAPI 자동 연동"],
    )
 
    uploaded = None
    api_service_key, api_org_filter = "", "창원"
 
    if data_source == "파일 업로드 (최신 XLSX/CSV로 교체)":
        uploaded = st.file_uploader(
            "누비자 대여소 XLSX/CSV 업로드",
            type=["xlsx", "csv"],
        )
    elif data_source == "공공데이터포털 OpenAPI 자동 연동":
        st.caption(
            "행정안전부 '전국자전거대여소표준데이터'를 사용합니다. "
            "요청주소는 이미 앱에 내장되어 있으니, 인증키만 입력하면 됩니다.\n\n"
            "1) data.go.kr 회원가입 → '전국자전거대여소표준데이터' 검색 → 활용신청\n"
            "2) 마이페이지 > API 키 발급/관리 에서 '인증키(디코딩)' 복사 → 아래에 붙여넣기"
        )
        # secrets.toml에 저장해두면 자동으로 채워지고, 없으면 직접 입력한다.
        default_key = st.secrets.get("DATA_GO_KR_SERVICE_KEY", "")
        api_service_key = st.text_input(
            "서비스 인증키 (디코딩 키)", value=default_key, type="password"
        ).strip()
        api_org_filter = st.text_input("관리기관명 필터", value="창원", help="전국 데이터 중 이 글자가 포함된 기관만 보여줍니다.")
        fetch_clicked = st.button("🔄 OpenAPI에서 불러오기", use_container_width=True)
 
    n_show = st.slider("가까운 대여소 몇 개를 볼까요?", 3, 10, NEAREST_N)
 
    st.markdown("---")
    st.subheader("🚏 경로 안내 방식")
    routing_engine = st.radio(
        "인도/차도를 구분해서 보고 싶다면 Tmap을 선택하세요",
        ["OSRM (기본, 무료, 인도·차도 구분 없음)", "Tmap 보행자 API (인도·횡단보도·계단 등 구분)"],
    )
    tmap_app_key = ""
    if routing_engine.startswith("Tmap"):
        st.caption(
            "Tmap 보행자 API는 실제 인도(보도) 데이터를 사용해서, 인도로 걷다가 "
            "지정된 횡단보도에서만 차도를 건너는 형태로 경로를 안내합니다.\n\n"
            "1) https://tmapapi.tmapmobility.com 가입 → 앱 등록(무료)\n"
            "2) 마이페이지 > 앱 관리에서 발급된 appKey 복사 → 아래에 붙여넣기"
        )
        default_tmap_key = st.secrets.get("TMAP_APP_KEY", "")
        tmap_app_key = st.text_input(
            "Tmap appKey", value=default_tmap_key, type="password"
        ).strip()
 
    st.markdown("---")
    st.subheader("📡 실시간 위치 추적")
    st.session_state.tracking = st.toggle(
        "실시간 추적 켜기 (걸어가면서 확인)",
        value=st.session_state.tracking,
        help="켜두면 5초마다 GPS를 다시 읽어와서 내 위치와 남은 경로를 자동으로 갱신합니다.",
    )
    if st.session_state.tracking:
        refresh_interval = st.slider("갱신 주기(초)", 3, 15, 5)
    st.markdown("---")
    st.markdown(
        "데이터 출처: [공공데이터포털 - 경상남도 창원시_누비자 터미널]"
        "(https://www.data.go.kr/data/15000545/fileData.do)"
    )
 
# 추적이 켜져 있으면 지정한 주기마다 스크립트를 자동으로 다시 실행시킨다.
# (이 tick 값이 바뀔 때마다 아래 get_geolocation()의 key도 바뀌어서, 캐시된 옛 위치가 아니라
#  브라우저에게 "GPS 다시 읽어줘"라고 매번 새로 요청하게 된다.)
if st.session_state.tracking:
    tick = st_autorefresh(interval=refresh_interval * 1000, key="gps_autorefresh")
else:
    tick = 0
 
try:
    if data_source == "공공데이터포털 OpenAPI 자동 연동":
        if not api_service_key:
            st.info("왼쪽에 인증키를 입력하고 '불러오기'를 눌러주세요. 입력 전까지는 기본 데이터로 보여드립니다.")
            stations_df = load_stations(None, None)
        elif fetch_clicked or "openapi_df" in st.session_state:
            if fetch_clicked:
                st.session_state["openapi_df"] = load_stations_from_openapi(api_service_key, api_org_filter)
            stations_df = st.session_state["openapi_df"]
        else:
            stations_df = load_stations(None, None)
    else:
        stations_df = load_stations(
            uploaded.getvalue() if uploaded else None,
            uploaded.name if uploaded else None,
        )
except Exception as e:
    st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
    st.stop()
 
st.info(f"불러온 대여소 개수: {len(stations_df)}개", icon="📍")
 
# ----------------------------------------------------------------------------
# 5. 현재 위치 가져오기 (브라우저 GPS)
#    tick 값을 key에 섞어주면, 추적이 켜져 있는 동안 자동새로고침 때마다
#    "새 위치를 다시 물어봐" 라는 의미가 되어 실시간처럼 동작한다.
# ----------------------------------------------------------------------------
loc = get_geolocation(component_key=f"geo_{tick}")
 
if loc is None:
    st.warning("브라우저에 위치 접근 권한을 허용해주세요. 권한 창이 뜨지 않으면 새로고침(F5) 해보세요.")
    st.stop()
 
if "error" in loc:
    st.error(f"위치를 가져오지 못했습니다: {loc['error'].get('message', '알 수 없는 오류')}")
    st.stop()
 
my_lat = loc["coords"]["latitude"]
my_lon = loc["coords"]["longitude"]
 
# 실제로 걸어온 흔적(trail) 기록 - 직전 위치와 눈에 띄게 다를 때만 追加해서 GPS 흔들림 노이즈를 줄인다.
if not st.session_state.trail or haversine_m(*st.session_state.trail[-1], my_lat, my_lon) > 3:
    st.session_state.trail.append((my_lat, my_lon))
 
st.success(f"현재 위치: 위도 {my_lat:.5f}, 경도 {my_lon:.5f}" + (f"  🔴 실시간 추적 중 (tick {tick})" if st.session_state.tracking else ""))
 
# ----------------------------------------------------------------------------
# 6. 가까운 대여소 N개 계산
# ----------------------------------------------------------------------------
stations_df = stations_df.copy()
stations_df["distance_m"] = stations_df.apply(
    lambda r: haversine_m(my_lat, my_lon, r["lat"], r["lon"]), axis=1
)
nearest = stations_df.sort_values("distance_m").head(n_show).reset_index(drop=True)
 
col_list, col_map = st.columns([1, 2])
 
with col_list:
    st.subheader("가까운 대여소 목록")
    # 라디오 버튼의 key를 station name(고유값)으로 고정해서, 거리 숫자가 바뀌어도
    # 매번 새로운 위젯으로 취급되어 선택이 풀리는 문제를 막는다.
    name_list = nearest["name"].tolist()
    dist_map = dict(zip(nearest["name"], nearest["distance_m"]))
    choice_name = st.radio(
        "대여소를 선택하세요",
        name_list,
        format_func=lambda n: f"{n}  ({dist_map[n]:.0f}m)",
        key="station_radio",
    )
    selected = nearest[nearest["name"] == choice_name].iloc[0]
 
    st.metric("직선 거리", f"{selected['distance_m']:.0f} m")
    if "address" in selected and pd.notna(selected.get("address")):
        st.write(f"📮 주소: {selected['address']}")
    if "capacity" in selected and pd.notna(selected.get("capacity")):
        st.write(f"🚲 거치대수: {int(selected['capacity'])}대")
 
    col_a, col_b = st.columns(2)
    if col_a.button("🗺️ 이 대여소로 경로 시작", use_container_width=True):
        # 목적지를 session_state에 "고정"해둔다. 이렇게 해야 다음 자동새로고침/재실행에서도
        # 경로가 사라지지 않고 계속 표시된다. (이전 버전의 '깜빡였다 사라지는' 문제의 원인 수정)
        st.session_state.target = {
            "name": selected["name"],
            "lat": float(selected["lat"]),
            "lon": float(selected["lon"]),
        }
        st.session_state.trail = [(my_lat, my_lon)]  # 새 목적지를 정하면 이동 흔적도 새로 시작
    if col_b.button("⏹️ 경로 그만 보기", use_container_width=True):
        st.session_state.target = None
        st.session_state.tracking = False
 
# ----------------------------------------------------------------------------
# 7. 지도 그리기
# ----------------------------------------------------------------------------
with col_map:
    m = folium.Map(location=[my_lat, my_lon], zoom_start=15)
 
    folium.Marker(
        [my_lat, my_lon],
        tooltip="내 현재 위치",
        icon=folium.Icon(color="blue", icon="user", prefix="fa"),
    ).add_to(m)
 
    for i, row in nearest.iterrows():
        is_target = st.session_state.target is not None and row["name"] == st.session_state.target["name"]
        folium.Marker(
            [row["lat"], row["lon"]],
            tooltip=f"{row['name']} ({row['distance_m']:.0f}m)",
            icon=folium.Icon(
                color="red" if is_target else "green",
                icon="bicycle",
                prefix="fa",
            ),
        ).add_to(m)
 
    # 지금까지 실제로 걸어온 흔적 - 옅은 파란 선으로 표시
    if len(st.session_state.trail) >= 2:
        folium.PolyLine(
            st.session_state.trail, color="#3388FF", weight=4, opacity=0.5, dash_array="4"
        ).add_to(m)
 
    target = st.session_state.target
    if target is not None:
        use_tmap = routing_engine.startswith("Tmap") and bool(tmap_app_key)
 
        with st.spinner("보행자 경로를 계산하는 중..."):
            if use_tmap:
                try:
                    tmap_result = get_walking_route_tmap(tmap_app_key, my_lat, my_lon, target["lat"], target["lon"])
                except Exception as e:
                    st.warning(f"Tmap 경로 요청에 실패해서 OSRM으로 대신 안내합니다: {e}")
                    tmap_result = None
                route = None if tmap_result else get_walking_route(my_lat, my_lon, target["lat"], target["lon"])
            else:
                tmap_result = None
                route = get_walking_route(my_lat, my_lon, target["lat"], target["lon"])
                if routing_engine.startswith("Tmap") and not tmap_app_key:
                    st.info("Tmap appKey를 입력하면 인도/횡단보도를 구분해서 보여드립니다. 지금은 OSRM으로 안내합니다.")
 
        if tmap_result is not None:
            # 구간(인도/횡단보도/계단 등)마다 색을 다르게 그려서 실제로 걷는 길을 구분해서 보여준다.
            used_types = set()
            for seg in tmap_result["segments"]:
                style = SEGMENT_STYLE[seg["type"]]
                used_types.add(seg["type"])
                if seg["type"] == "sidewalk":
                    # 인도 구간만 "흐르는" 애니메이션으로 강조해서 진행 방향을 보여준다.
                    AntPath(seg["coords"], color=style["color"], weight=6, opacity=0.9, delay=800, dash_array=[10, 20]).add_to(m)
                else:
                    folium.PolyLine(
                        seg["coords"], color=style["color"], weight=6, opacity=0.9,
                        dash_array=style["dash"],
                        tooltip=style["label"],
                    ).add_to(m)
                    if seg["type"] == "crosswalk":
                        mid = seg["coords"][len(seg["coords"]) // 2]
                        folium.Marker(
                            mid, tooltip="🚦 횡단보도",
                            icon=folium.DivIcon(html="<div style='font-size:18px'>🚦</div>"),
                        ).add_to(m)
 
            legend_html = "  ".join(
                f"<span style='color:{SEGMENT_STYLE[t]['color']}'>●</span> {SEGMENT_STYLE[t]['label']}"
                for t in used_types
            )
            st.markdown(f"**범례:** {legend_html}", unsafe_allow_html=True)
 
            minutes = tmap_result["duration_s"] / 60
            st.success(
                f"🎯 목적지: {target['name']} · 남은 거리 약 {tmap_result['distance_m']:.0f}m · "
                f"예상 소요시간 약 {minutes:.1f}분 (Tmap 보행자 경로 · 인도/차도 구분)"
            )
            if tmap_result["distance_m"] < 15:
                st.balloons()
                st.success("🎉 목적지에 도착했습니다!")
            bounds = [[my_lat, my_lon], [target["lat"], target["lon"]]]
            m.fit_bounds(bounds, padding=(30, 30))
 
        elif route is None:
            st.error("경로를 찾지 못했습니다. 잠시 후 다시 시도해주세요.")
        else:
            # AntPath는 선을 따라 점들이 흐르듯 움직이는 애니메이션 효과를 준다.
            # -> "실시간으로 경로를 따라 이동하는 느낌"을 시각적으로 표현
            AntPath(
                route["coords"],
                color="#FF5733",
                weight=6,
                opacity=0.9,
                delay=800,
                dash_array=[10, 20],
            ).add_to(m)
 
            minutes = route["duration_s"] / 60
            st.success(
                f"🎯 목적지: {target['name']} · 남은 거리 약 {route['distance_m']:.0f}m · "
                f"예상 소요시간 약 {minutes:.1f}분 (OSRM · 도로망 기준)"
            )
            if route["distance_m"] < 15:
                st.balloons()
                st.success("🎉 목적지에 도착했습니다!")
 
            bounds = [[my_lat, my_lon], [target["lat"], target["lon"]]]
            m.fit_bounds(bounds, padding=(30, 30))
    else:
        st.info("왼쪽에서 대여소를 고르고 '이 대여소로 경로 시작'을 누르면 경로가 여기 표시됩니다.")
 
    # key를 고정해두면 streamlit-folium이 지도 확대/이동 상태를 매 새로고침마다 유지해준다.
    st_folium(m, height=560, use_container_width=True, key="main_map")
 
 
st.markdown("---")
st.caption(
    "⚠️ OSRM은 무료 공개 데모 서버라서 도로망(차도)을 그대로 따라가는 경로를 줍니다. "
    "인도·횡단보도·계단까지 구분해서 보고 싶다면 사이드바에서 'Tmap 보행자 API'를 선택하고 "
    "무료 appKey를 입력하세요.\n\n"
    "📡 실시간 추적을 켜면 설정한 주기마다 GPS를 다시 읽고 경로를 재계산합니다. "
    "무료 API 정책상 너무 짧은 주기(1~2초)는 피하고 5초 이상을 권장합니다."
)