import jsonㅇ
from datetime import datetime
from io import BytesIO

import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
from PIL import Image

try:
    import docx
    DOCX_OK = True
except Exception:
    DOCX_OK = False

try:
    from pypdf import PdfReader
    PDF_OK = True
except Exception:
    PDF_OK = False


st.set_page_config(page_title="hwahwago_translator", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []
if "vocab" not in st.session_state:
    st.session_state.vocab = []
if "last_source" not in st.session_state:
    st.session_state.last_source = ""
if "last_output" not in st.session_state:
    st.session_state.last_output = ""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_vocab_item(kind: str, text: str, note: str = ""):
    text = (text or "").strip()
    if not text:
        return
    item = {
        "time": now_str(),
        "kind": kind,
        "text": text,
        "note": (note or "").strip(),
    }
    st.session_state.vocab.append(item)


def download_bytes(filename: str, data: bytes, mime: str):
    st.download_button(
        label=f"📥 {filename} 다운로드",
        data=data,
        file_name=filename,
        mime=mime,
        use_container_width=True,
    )


def safe_decode(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr", "latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", errors="ignore")


def read_txt(uploaded) -> str:
    return safe_decode(uploaded.getvalue())


def read_docx(uploaded) -> str:
    if not DOCX_OK:
        raise RuntimeError("python-docx가 설치되어 있지 않습니다.")
    f = BytesIO(uploaded.getvalue())
    d = docx.Document(f)
    parts = []
    for p in d.paragraphs:
        parts.append(p.text)
    return "\n".join(parts).strip()


def read_pdf(uploaded) -> str:
    if not PDF_OK:
        raise RuntimeError("pypdf가 설치되어 있지 않습니다.")
    f = BytesIO(uploaded.getvalue())
    reader = PdfReader(f)
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def chunk_text(text: str, max_chars: int = 8000):
    text = text or ""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    cur = []
    cur_len = 0
    for line in text.splitlines(True):
        if cur_len + len(line) > max_chars and cur:
            chunks.append("".join(cur))
            cur = []
            cur_len = 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def get_api_key():
    if "GEMINI_API_KEY" in st.secrets and str(st.secrets.get("GEMINI_API_KEY")).strip():
        return str(st.secrets.get("GEMINI_API_KEY")).strip(), True
    return "", False


def init_model(api_key: str, model_name: str):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def gemini_text(model, prompt: str) -> str:
    res = model.generate_content(prompt)
    return getattr(res, "text", "") or ""


def gemini_image(model, prompt: str, image: Image.Image) -> str:
    res = model.generate_content([prompt, image])
    return getattr(res, "text", "") or ""


with st.sidebar:
    st.title("🛠️ 기능툴")

    secret_key, loaded_from_secrets = get_api_key()
    if loaded_from_secrets:
        st.success("API로드 됨")
        api_key = secret_key
    else:
        api_key = st.text_input("Gemini API Key 입력", type="password")

    st.divider()

    TARGET_LANGS = ["한국어", "베트남어", "일본어", "영어", "중국어"]
    lang = st.selectbox("목표 언어", TARGET_LANGS, index=0)

    mode = st.radio("모드", ["번역", "해석(의미 중심)"], horizontal=True)

    tone = st.selectbox("톤", ["기본", "공손", "캐주얼", "비즈니스", "학술"], index=0)

    keep_format = st.toggle("줄바꿈/형식 유지", value=True)

    st.divider()
    st.subheader("📚 단어장")
    st.caption(f"저장 개수: {len(st.session_state.vocab)}")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        if st.button("단어장 보기", use_container_width=True):
            st.session_state._show_vocab = True
    with col_v2:
        vocab_json = json.dumps(st.session_state.vocab, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "단어장 JSON 다운로드",
            data=vocab_json,
            file_name="vocab.json",
            mime="application/json",
            use_container_width=True,
        )

st.title("🌐 번역기")



if not api_key:
    st.warning("사이드바에 Gemini API 키를 입력해 주세요. (Streamlit Cloud에서는 Secrets에 넣으면 입력 없이 동작)")
    st.stop()

try:
    model = init_model(api_key, "gemini-2.5-flash-lite")
except Exception as e:
    st.error(f"모델 초기화 실패: {e}")
    st.stop()


def build_prompt(target_lang: str, user_text: str) -> str:
    base = []
    if mode == "번역":
        base.append(f"다음 내용을 자연스러운 {target_lang}로 번역해줘.")
    else:
        base.append(f"다음 내용을 {target_lang}로 이해하기 쉽게 해석해줘. 직역보다 의미 전달에 집중해줘.")
    if tone != "기본":
        base.append(f"톤은 '{tone}'로 맞춰줘.")
    if keep_format:
        base.append("원문의 줄바꿈/목록/형식을 최대한 유지해줘.")
    base.append("")
    base.append(user_text)
    return "\n".join(base).strip()


def run_text_job(text: str) -> str:
    chunks = chunk_text(text, max_chars=8000)
    outs = []
    for i, ch in enumerate(chunks, start=1):
        prompt = build_prompt(lang, ch)
        out = gemini_text(model, prompt)
        if len(chunks) > 1:
            outs.append(f"[파트 {i}/{len(chunks)}]\n{out}".strip())
        else:
            outs.append(out.strip())
    return "\n\n".join([o for o in outs if o]).strip()


tab_text, tab_file, tab_img, tab_voice = st.tabs(
    ["📝 텍스트 입력", "📁 파일 업로드(TXT/DOCX/PDF)", "📷 사진 번역", "🎙️ 음성 인식"]
)

with tab_text:
    source = st.text_area("내용 입력", height=280)
    col_a, col_b = st.columns([1, 1])
    with col_a:
        run_btn = st.button("실행 🚀", use_container_width=True)
    with col_b:
        save_btn = st.button("📌 결과를 단어장에 저장", use_container_width=True)

    if run_btn and source.strip():
        with st.spinner("처리 중..."):
            try:
                out = run_text_job(source)
                st.session_state.last_source = source
                st.session_state.last_output = out
                st.session_state.history.append(
                    {"time": now_str(), "type": "text", "lang": lang, "mode": mode, "tone": tone, "source": source, "output": out}
                )
                st.success(out)
            except Exception as e:
                st.error(f"실행 실패: {e}")

    if save_btn:
        if st.session_state.last_output.strip():
            add_vocab_item("result", st.session_state.last_output, note=f"{lang} / {mode} / {tone}")
            st.success("단어장에 저장했어요.")
        else:
            st.info("저장할 결과가 없어요. 먼저 실행해 주세요.")

    if st.session_state.last_output.strip():
        st.divider()
        out_txt = st.session_state.last_output
        if st.button("📤 번역 결과 TXT로 다운로드", use_container_width=True):
            download_bytes("translation.txt", out_txt.encode("utf-8"), "text/plain")

with tab_file:
    st.caption("TXT/DOCX/PDF 파일을 올리면 내용을 추출해서 번역/해석합니다.")
    uploaded = st.file_uploader("파일 업로드", type=["txt", "docx", "pdf"])
    col_f1, col_f2 = st.columns([1, 1])
    with col_f1:
        run_file = st.button("파일 실행 🚀", use_container_width=True)
    with col_f2:
        save_file_result = st.button("📌 파일 결과 단어장 저장", use_container_width=True)

    file_text = ""
    file_name = ""
    if uploaded:
        file_name = uploaded.name
        try:
            if file_name.lower().endswith(".txt"):
                file_text = read_txt(uploaded)
            elif file_name.lower().endswith(".docx"):
                file_text = read_docx(uploaded)
            elif file_name.lower().endswith(".pdf"):
                file_text = read_pdf(uploaded)
            else:
                st.warning("지원하지 않는 파일 형식입니다.")
        except Exception as e:
            st.error(f"파일 읽기 실패: {e}")

    if uploaded and file_text:
        with st.expander("추출된 텍스트 미리보기", expanded=False):
            st.text_area("미리보기", file_text[:20000], height=220)

    if run_file and uploaded and file_text:
        with st.spinner("파일 번역 중..."):
            try:
                out = run_text_job(file_text)
                st.session_state.last_source = f"[FILE:{file_name}]\n\n{file_text}"
                st.session_state.last_output = out
                st.session_state.history.append(
                    {"time": now_str(), "type": "file", "file": file_name, "lang": lang, "mode": mode, "tone": tone, "source": file_text, "output": out}
                )
                st.success(out)
            except Exception as e:
                st.error(f"파일 실행 실패: {e}")

    if save_file_result:
        if st.session_state.last_output.strip():
            add_vocab_item("file_result", st.session_state.last_output, note=f"{lang} / {mode} / {tone}")
            st.success("단어장에 저장했어요.")
        else:
            st.info("저장할 결과가 없어요. 먼저 파일 실행을 해 주세요.")

    if st.session_state.last_output.strip():
        st.divider()
        out_txt = st.session_state.last_output
        st.caption("다운로드 형식")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            download_bytes("translation.txt", out_txt.encode("utf-8"), "text/plain")
        with dl_col2:
            download_bytes("translation.json", json.dumps({"output": out_txt}, ensure_ascii=False, indent=2).encode("utf-8"), "application/json")

with tab_img:
    st.subheader("📷 사진 번역 (OCR + 번역)")
    img_file = st.file_uploader("이미지 업로드", type=["png", "jpg", "jpeg", "webp"])
    run_img = st.button("사진 번역 실행 📷", use_container_width=True)

    if img_file:
        image = Image.open(img_file).convert("RGB")
        st.image(image, use_container_width=True)

        if run_img:
            with st.spinner("이미지 처리 중..."):
                try:
                    prompt = f"""
You are an OCR + Translation Assistant.

Extract the text within the image as accurately as possible.
Translate the extracted text into natural {lang} {'translation' if mode=='translation' else 'interpretation (meaning-focused)'}.
Match the tone to '{tone}'.
Output in the following format:

[추출 텍스트]
...

[결과]
...
"""
                    out = gemini_image(model, prompt.strip(), image)
                    st.session_state.last_source = f"[IMAGE:{img_file.name}]"
                    st.session_state.last_output = out
                    st.session_state.history.append(
                        {"time": now_str(), "type": "image", "file": img_file.name, "lang": lang, "mode": mode, "tone": tone, "source": "(image)", "output": out}
                    )
                    st.success(out)
                except Exception as e:
                    st.error(f"사진 번역 실패: {e}")

    if st.session_state.last_output.strip():
        st.divider()
        out_txt = st.session_state.last_output
        download_bytes("image_translation.txt", out_txt.encode("utf-8"), "text/plain")

# ✅ tab_voice 블록을 아래 코드로 "통째로 교체"하면 돼
with tab_voice:
    st.subheader("🎙️ 음성 인식")
    st.caption("🔴 듣는 중 표시 + 10초 무음 경고 + 1분 무음 자동 정지")

    components.html(
        """
        <div style="font-family: sans-serif; display:flex; flex-direction:column; gap:10px;">
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button id="start" style="padding:8px 12px;">🎙️ 시작</button>
            <button id="stop" style="padding:8px 12px;" disabled>⏹️ 중지</button>

            <select id="lang" style="padding:8px 12px;">
              <option value="ko-KR" selected>한국어</option>
              <option value="en-US">영어</option>
              <option value="ja-JP">일본어</option>
              <option value="vi-VN">베트남어</option>
              <option value="zh-CN">중국어</option>
            </select>
          </div>

          <div id="status"
               style="padding:10px 12px; border-radius:10px; background:#f3f4f6; border:1px solid #e5e7eb;">
            ⚪️ 대기 중
          </div>

          <textarea id="out" style="width:100%; height:220px; padding:10px;" placeholder="여기에 인식 텍스트가 표시됩니다..."></textarea>

          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button id="copy" style="padding:8px 12px;">📋 복사</button>
            <button id="clear" style="padding:8px 12px;">🧹 지우기</button>
          </div>

          <div style="opacity:.75; font-size:12px;">
            * 10초 동안 결과가 안 들어오면 “소리가 들리지 않아요” 표시<br/>
            * 1분 동안 결과가 없으면 자동으로 중지됩니다
          </div>
        </div>

        <script>
          const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

          const startBtn = document.getElementById("start");
          const stopBtn  = document.getElementById("stop");
          const copyBtn  = document.getElementById("copy");
          const clearBtn = document.getElementById("clear");
          const langSel  = document.getElementById("lang");
          const out      = document.getElementById("out");
          const statusEl = document.getElementById("status");

          let rec = null;
          let listening = false;

          // 마지막으로 "인식 결과"가 들어온 시간 (무음 판단 기준)
          let lastHeardMs = 0;

          // 타이머(상태 업데이트)
          let tickId = null;

          function setStatus(text, kind){
            // kind: idle | listening | warn | stopped | error
            let bg = "#f3f4f6", bd="#e5e7eb";
            if(kind === "listening"){ bg="#ecfeff"; bd="#a5f3fc"; }
            if(kind === "warn"){ bg="#fffbeb"; bd="#fde68a"; }
            if(kind === "stopped"){ bg="#f3f4f6"; bd="#e5e7eb"; }
            if(kind === "error"){ bg="#fef2f2"; bd="#fecaca"; }
            statusEl.style.background = bg;
            statusEl.style.borderColor = bd;
            statusEl.textContent = text;
          }

          function setButtons(){
            startBtn.disabled = listening;
            stopBtn.disabled  = !listening;
          }

          function stopListening(auto=false){
            if(rec){
              try { rec.stop(); } catch(e) {}
            }
            listening = false;
            setButtons();
            if(auto){
              setStatus("⏹️ 1분 동안 소리가 감지되지 않아 자동으로 정지되었습니다.", "stopped");
            } else {
              setStatus("⚫️ 중지됨", "stopped");
            }
            if(tickId){
              clearInterval(tickId);
              tickId = null;
            }
          }

          function startListening(){
            if(!rec) return;

            listening = true;
            lastHeardMs = Date.now(); // 시작 시점 기준으로 타이머 시작
            setButtons();
            setStatus("🔴 듣는 중…", "listening");

            try { rec.start(); } catch(e) {}

            // 0.5초마다 무음 체크
            tickId = setInterval(() => {
              if(!listening) return;

              const elapsed = Date.now() - lastHeardMs;

              // 10초 무음 경고
              if(elapsed >= 10000 && elapsed < 60000){
                setStatus("⚠️ 소리가 들리지 않아요 (마이크/주변 소음/권한을 확인해 주세요)", "warn");
              }

              // 1분 무음 자동 정지
              if(elapsed >= 60000){
                stopListening(true);
              }
            }, 500);
          }

          if(!SpeechRecognition){
            setStatus("❌ 이 브라우저는 음성 인식을 지원하지 않습니다. 크롬/엣지로 시도해 주세요.", "error");
            startBtn.disabled = true;
            stopBtn.disabled = true;
          } else {
            rec = new SpeechRecognition();
            rec.lang = langSel.value;
            rec.interimResults = true;
            rec.continuous = true;

            langSel.onchange = () => {
              if(rec) rec.lang = langSel.value;
            };

            // 인식 결과가 들어오면 "소리가 들렸다"로 판단하고 타이머 리셋
            rec.onresult = (e) => {
              let text = "";
              for(let i=0; i<e.results.length; i++){
                text += e.results[i][0].transcript;
              }
              out.value = text;

              // ✅ 여기서 마지막 입력 시간을 갱신 → 무음 타이머 리셋
              lastHeardMs = Date.now();

              // 듣는 중 표시로 복귀
              if(listening){
                setStatus("🔴 듣는 중…", "listening");
              }
            };

            // 사용자가 권한을 막았거나 오류가 나면 상태 표시
            rec.onerror = (e) => {
              // e.error: "not-allowed", "service-not-allowed", "no-speech" 등
              listening = false;
              setButtons();
              if(tickId){
                clearInterval(tickId);
                tickId = null;
              }
              if(e && e.error === "not-allowed"){
                setStatus("❌ 마이크 권한이 차단되어 있어요. 주소창 왼쪽 자물쇠에서 마이크 허용 후 다시 시도해 주세요.", "error");
              } else if(e && e.error === "no-speech"){
                setStatus("⚠️ 음성이 감지되지 않았어요. 마이크를 확인해 주세요.", "warn");
              } else {
                setStatus("❌ 음성 인식 오류: " + (e && e.error ? e.error : "unknown"), "error");
              }
            };

            rec.onend = () => {
              // 사용자가 stop을 눌렀거나 브라우저가 종료했을 때
              // listening이 true인 상태로 end가 오면(일시적 종료)도 있을 수 있어서
              // 여기서는 버튼 상태만 안전하게 맞춰줌
              if(listening){
                // 일부 브라우저에서 연속 인식 중간에 end가 발생하기도 함
                // 너무 공격적으로 재시작하면 UX가 이상해져서, 사용자가 다시 시작하도록 둠
                listening = false;
                setButtons();
                if(tickId){
                  clearInterval(tickId);
                  tickId = null;
                }
                setStatus("⚫️ 중지됨 (브라우저가 인식을 종료했어요. 다시 시작을 눌러주세요)", "stopped");
              }
            };

            startBtn.onclick = () => startListening();
            stopBtn.onclick  = () => stopListening(false);

            copyBtn.onclick = async () => {
              try { await navigator.clipboard.writeText(out.value || ""); } catch(e) {}
            };

            clearBtn.onclick = () => {
              out.value = "";
              // 텍스트를 지우는 건 "무음"이랑 별개라서 타이머는 그대로 둠
            };

            setButtons();
            setStatus("⚪️ 대기 중", "idle");
          }
        </script>
        """,
        height=420,
    )

