import streamlit as st
import random
import base64
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components
 
st.set_page_config(page_title="가위바위보 대결 앱", page_icon="✂️", layout="wide")
 
st.title("✂️🪨📄 가위바위보 대결 앱")
 
CHOICES = ["가위", "바위", "보"]
EMOJI = {"가위": "✂️", "바위": "🪨", "보": "📄"}
 
# 가위바위보 승패 규칙: key가 이기는 대상은 value
BEATS = {"가위": "보", "바위": "가위", "보": "바위"}
 
 
def judge(player: str, computer: str) -> str:
    """플레이어 기준 결과 문자열 반환"""
    if player == computer:
        return "무승부"
    elif BEATS[player] == computer:
        return "승리"
    else:
        return "패배"
 
 
tab_basic, tab_ai = st.tabs(["🖐️ 기본 모드 (버튼으로 대결)", "🤖 AI 인식 모드 (Teachable Machine 연동)"])
 
# =========================================================================
# 1) 기본 모드 - 버튼 클릭으로 컴퓨터와 대결, session_state로 누적 점수 기록
# =========================================================================
with tab_basic:
    st.subheader("버튼을 눌러 컴퓨터와 대결하세요!")
 
    if "score" not in st.session_state:
        st.session_state.score = {"승리": 0, "패배": 0, "무승부": 0}
    if "history" not in st.session_state:
        st.session_state.history = []
 
    col1, col2, col3 = st.columns(3)
    player_choice = None
    if col1.button("✂️ 가위", use_container_width=True):
        player_choice = "가위"
    if col2.button("🪨 바위", use_container_width=True):
        player_choice = "바위"
    if col3.button("📄 보", use_container_width=True):
        player_choice = "보"
 
    if player_choice:
        computer_choice = random.choice(CHOICES)
        result = judge(player_choice, computer_choice)
        st.session_state.score[result] += 1
        st.session_state.history.insert(
            0, {"내 선택": f"{EMOJI[player_choice]} {player_choice}",
                "컴퓨터 선택": f"{EMOJI[computer_choice]} {computer_choice}",
                "결과": result}
        )
 
        result_msg = {"승리": "🎉 이겼습니다!", "패배": "😢 졌습니다!", "무승부": "🤝 비겼습니다!"}
        st.markdown(f"## {EMOJI[player_choice]} VS {EMOJI[computer_choice]}")
        if result == "승리":
            st.success(result_msg[result])
        elif result == "패배":
            st.error(result_msg[result])
        else:
            st.warning(result_msg[result])
 
    st.markdown("---")
    s1, s2, s3 = st.columns(3)
    s1.metric("🎉 승리", st.session_state.score["승리"])
    s2.metric("😢 패배", st.session_state.score["패배"])
    s3.metric("🤝 무승부", st.session_state.score["무승부"])
 
    if st.button("🔄 점수 초기화"):
        st.session_state.score = {"승리": 0, "패배": 0, "무승부": 0}
        st.session_state.history = []
        st.rerun()
 
    if st.session_state.history:
        with st.expander("📋 대결 기록 보기"):
            st.table(st.session_state.history)
 
# =========================================================================
# 2) AI 인식 모드 - Teachable Machine 모델로 손 모양 사진을 인식해서 대결
# =========================================================================
with tab_ai:
    st.subheader("손 모양 사진을 올리면 AI가 가위/바위/보를 인식해서 대결합니다")
    st.write(
        "먼저 Teachable Machine에서 **가위 / 바위 / 보** 3개 클래스로 직접 학습시킨 모델을 "
        "`Export Model → Upload(Shareable link)`로 게시하고, 그 URL을 아래에 입력하세요."
    )
 
    model_url = st.text_input(
        "Teachable Machine 모델 URL",
        value="https://teachablemachine.withgoogle.com/models/pc8DpzFoM/",
        placeholder="https://teachablemachine.withgoogle.com/models/xxxxxxxx/",
        key="rps_model_url",
    )
 
    input_method = st.radio(
        "손 모양을 어떻게 입력할까요?",
        ["📸 카메라로 바로 찍기 (폰 추천)", "📁 파일 업로드"],
        horizontal=True,
        key="rps_input_method",
    )
 
    if input_method.startswith("📸"):
        st.caption("폰이라면 버튼을 누르는 순간 카메라가 열리고, 촬영하자마자 바로 아래에 결과가 나타나요.")
        uploaded_hand = st.camera_input("가위/바위/보 손 모양을 촬영하세요", key="rps_camera")
    else:
        uploaded_hand = st.file_uploader("손 모양 사진 업로드", type=["png", "jpg", "jpeg"], key="rps_upload")
 
    if model_url and uploaded_hand:
        if not model_url.endswith("/"):
            model_url += "/"
 
        image = Image.open(uploaded_hand).convert("RGB")
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_data_url = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()
 
        # 컴퓨터의 선택을 미리 정해서 JS 쪽에 함께 넘겨줍니다.
        computer_choice_ai = random.choice(CHOICES)
 
        col_left, col_right = st.columns([1, 1.4])
        with col_left:
            st.image(image, caption="업로드한 손 모양", use_container_width=True)
            st.info(f"컴퓨터의 선택: {EMOJI[computer_choice_ai]} {computer_choice_ai} (공개는 결과와 함께!)")
 
        with col_right:
            html_code = """
            <div style="font-family:-apple-system, sans-serif;">
              <div id="status" style="color:#555; margin-bottom:10px;">AI가 손 모양을 분석 중입니다... ⏳</div>
              <img id="predict-image" src="__IMG_DATA_URL__" style="display:none;" crossorigin="anonymous" />
              <div id="result-box" style="font-size:18px;"></div>
              <div id="label-container" style="margin-top:14px;"></div>
            </div>
 
            <script src="https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.20.0/dist/tf.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/@teachablemachine/image@0.8.5/dist/teachablemachine-image.min.js"></script>
            <script type="text/javascript">
              const URL_BASE = "__MODEL_URL__";
              const COMPUTER_CHOICE = "__COMPUTER_CHOICE__";
              const BEATS = { "가위": "보", "바위": "가위", "보": "바위",
                               "scissors": "paper", "rock": "scissors", "paper": "rock" };
              const KOR = { "scissors": "가위", "rock": "바위", "paper": "보" };
              const EMOJI = { "가위": "✂️", "바위": "🪨", "보": "📄",
                               "scissors": "✂️", "rock": "🪨", "paper": "📄" };
 
              function normalize(label) {
                const trimmed = label.trim();
                return KOR[trimmed.toLowerCase()] || trimmed;
              }
 
              function renderBar(className, prob) {
                const pct = (prob * 100).toFixed(1);
                return `<div style="margin-bottom:6px;">
                          <div style="display:flex; justify-content:space-between; font-size:13px;">
                            <span>${className}</span><span>${pct}%</span>
                          </div>
                          <div style="background:#eee; border-radius:6px; height:10px;">
                            <div style="background:#4C8BF5; width:${pct}%; height:10px; border-radius:6px;"></div>
                          </div>
                        </div>`;
              }
 
              async function init() {
                const statusEl = document.getElementById("status");
                try {
                  const model = await tmImage.load(URL_BASE + "model.json", URL_BASE + "metadata.json");
                  statusEl.innerText = "분석 중입니다... 🔍";
 
                  const imgEl = document.getElementById("predict-image");
                  imgEl.onload = async () => {
                    const predictions = await model.predict(imgEl);
                    predictions.sort((a, b) => b.probability - a.probability);
 
                    let html = "";
                    predictions.forEach((p) => { html += renderBar(p.className, p.probability); });
                    document.getElementById("label-container").innerHTML = html;
 
                    const rawTop = predictions[0].className;
                    const player = normalize(rawTop);
                    statusEl.innerHTML = `✅ AI가 인식한 내 손 모양: <b>${EMOJI[player] || ""} ${player}</b>`;
 
                    const resultBox = document.getElementById("result-box");
                    if (BEATS[player] === undefined) {
                      resultBox.innerHTML =
                        "⚠️ 클래스 이름이 '가위/바위/보' 또는 'scissors/rock/paper'와 일치하지 않아 승패를 판정할 수 없어요.";
                      return;
                    }
 
                    let outcome;
                    if (player === COMPUTER_CHOICE) outcome = "🤝 무승부입니다!";
                    else if (BEATS[player] === COMPUTER_CHOICE) outcome = "🎉 승리했습니다!";
                    else outcome = "😢 패배했습니다!";
 
                    resultBox.innerHTML =
                      `<h3>${EMOJI[player] || ""} VS ${EMOJI[COMPUTER_CHOICE]} ${COMPUTER_CHOICE}</h3>` +
                      `<p style="font-size:20px;">${outcome}</p>`;
                  };
                  if (imgEl.complete) imgEl.onload();
                } catch (err) {
                  statusEl.innerHTML =
                    "❌ 모델을 불러오지 못했습니다. 모델 URL과 클래스 이름을 확인해주세요.<br><small>" + err + "</small>";
                }
              }
              init();
            </script>
            """
            html_code = (
                html_code
                .replace("__IMG_DATA_URL__", img_data_url)
                .replace("__MODEL_URL__", model_url)
                .replace("__COMPUTER_CHOICE__", computer_choice_ai)
            )
            components.html(html_code, height=430, scrolling=True)
    else:
        st.info("모델 URL과 손 모양 사진을 모두 입력하면 여기에서 AI 대결 결과가 표시됩니다.")