import streamlit as st
import google.generativeai as genai
from datetime import datetime
from io import BytesIO
import json

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

st.set_page_config(page_title="번역기", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []
if "vocab" not in st.session_state:
    st.session_state.vocab = []
if "last_source" not in st.session_state:
    st.session_state.last_source = ""
if "last_result" not in st.session_state:
    st.session_state.last_result = ""
if "last_file_name" not in st.session_state:
    st.session_state.last_file_name = ""

def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None

secret_key = get_api_key()

with st.sidebar:
    st.title("🛠️ 기능툴")

    api_key = secret_key
    if not api_key:
        api_key = st.text_input("Gemini API Key 입력(로컬용)", type="password")
    else:
        st.caption("✅ Secrets에서 API 키 로드됨")

    st.divider()
    target_lang = st.selectbox("목표 언어", ["베트남어", "일본어", "영어", "중국어"])
    mode = st.radio("모드", ["번역", "해석(의미 중심)"], horizontal=True)
    tone = st.selectbox("톤", ["기본", "정중", "캐주얼", "비즈니스"])
    keep_format = st.toggle("줄바꿈/형식 유지", value=True)

    st.divider()
    st.caption("📌 단어장")
    st.write(f"저장 개수: {len(st.session_state.vocab)}")
    with st.expander("단어장 보기"):
        q = st.text_input("검색", key="vocab_search", placeholder="단어/문장/설명 검색")
        items = st.session_state.vocab
        if q.strip():
            ql = q.strip().lower()
            items = [v for v in items if ql in (v["selection"] + " " + v["explanation"]).lower()]
        for v in items[:20]:
            st.markdown(f"**{v['selection']}**  \n{v['explanation']}\n\n_{v['ts']}_")
            st.markdown("---")

    st.download_button(
        "단어장 JSON 다운로드",
        data=json.dumps(st.session_state.vocab, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="vocab.json",
        mime="application/json",
        use_container_width=True
    )

st.title("🌐 번역기")

model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
    except Exception as e:
        st.error(f"초기화 오류: {e}")

def call_gemini(prompt: str) -> str:
    if model is None:
        raise RuntimeError("API 키/모델 초기화를 확인해 주세요.")
    res = model.generate_content(prompt)
    return (res.text or "").strip()

def read_txt(file) -> str:
    data = file.read()
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8", errors="replace")

def read_docx(file) -> str:
    if not DOCX_OK:
        raise RuntimeError("DOCX 읽기: pip install python-docx")
    d = docx.Document(BytesIO(file.read()))
    return "\n".join(p.text for p in d.paragraphs)

def read_pdf(file) -> str:
    if not PDF_OK:
        raise RuntimeError("PDF 읽기: pip install pypdf")
    reader = PdfReader(BytesIO(file.read()))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            raise RuntimeError("암호화된 PDF는 지원하지 않아요(비밀번호 제거 후 다시 업로드).")
    parts = []
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
    text = "\n\n".join(parts).strip()
    if not text:
        raise RuntimeError("PDF에서 텍스트를 추출하지 못했어요. (스캔본이면 OCR이 필요해요)")
    return text

def chunk_text(text: str, max_chars: int = 3500):
    text = text.replace("\r\n", "\n")
    chunks, buf, size = [], [], 0
    for line in text.split("\n"):
        add = len(line) + 1
        if size + add > max_chars and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += add
    if buf:
        chunks.append("\n".join(buf))
    return chunks

def build_translate_prompt(src: str) -> str:
    tone_line = "" if tone == "기본" else f"톤은 '{tone}'로 맞춰줘."
    task = f"다음 내용을 자연스러운 {target_lang}로 번역해줘." if mode == "번역" else f"다음 내용을 {target_lang}로 해석해줘(의미 중심, 이해하기 쉽게)."
    format_line = "원문의 줄바꿈과 문단 구조를 최대한 유지해줘." if keep_format else ""
    return f"""{task}
{tone_line}
{format_line}

[원문]
{src}

[결과]
"""

def translate_long(text: str) -> str:
    chunks = chunk_text(text, max_chars=3500)
    outputs = []
    for ch in chunks:
        outputs.append(call_gemini(build_translate_prompt(ch)))
    return "\n\n".join(outputs).strip()

def make_docx_bytes(title: str, content: str) -> bytes:
    if not DOCX_OK:
        raise RuntimeError("DOCX 다운로드: pip install python-docx")
    d = docx.Document()
    if title:
        d.add_heading(title, level=1)
    for para in content.split("\n"):
        d.add_paragraph(para)
    bio = BytesIO()
    d.save(bio)
    return bio.getvalue()

def safe_base_name(name: str) -> str:
    if not name:
        return "translated"
    base = name.rsplit(".", 1)[0]
    return base if base else "translated"

tab1, tab2 = st.tabs(["🧾 텍스트 입력", "📄 파일 업로드 (TXT/DOCX/PDF)"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        source = st.text_area("내용 입력", height=320)
        run = st.button("실행 🚀", type="primary", use_container_width=True)
    with col2:
        if run:
            if not api_key:
                st.warning("사이드바에 API 키를 입력해 주세요. (Cloud 배포면 Secrets에 넣으면 자동으로 인식돼요)")
            elif not source.strip():
                st.warning("내용을 입력해 주세요.")
            else:
                try:
                    with st.spinner("처리 중..."):
                        result = translate_long(source)

                    st.session_state.last_source = source
                    st.session_state.last_result = result
                    st.session_state.last_file_name = ""

                    st.session_state.history.insert(0, {
                        "ts": now_ts(),
                        "type": "text",
                        "target_lang": target_lang,
                        "mode": mode,
                        "tone": tone,
                        "source": source,
                        "result": result
                    })

                    st.success("완료")
                    st.text_area("결과", value=result, height=320)

                    base = "translated_text"
                    d1, d2 = st.columns(2)
                    with d1:
                        st.download_button(
                            "📤 TXT 다운로드",
                            data=result.encode("utf-8"),
                            file_name=f"{base}.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
                    with d2:
                        st.download_button(
                            "📤 DOCX 다운로드",
                            data=make_docx_bytes("번역 결과", result) if DOCX_OK else b"",
                            file_name=f"{base}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True,
                            disabled=not DOCX_OK
                        )
                except Exception as e:
                    st.error(f"실행 실패: {e}")

with tab2:
    col1, col2 = st.columns(2)
    with col1:
        types = ["txt"]
        if DOCX_OK:
            types.append("docx")
        if PDF_OK:
            types.append("pdf")

        up = st.file_uploader("파일 업로드", type=types)
        run_file = st.button("파일 전체 실행 🚀", type="primary", use_container_width=True)

        if not PDF_OK:
            st.caption("PDF 지원: pip install pypdf")
        if not DOCX_OK:
            st.caption("DOCX 지원: pip install python-docx")

    with col2:
        if run_file:
            if not api_key:
                st.warning("사이드바에 API 키를 입력해 주세요. (Cloud 배포면 Secrets에 넣으면 자동으로 인식돼요)")
            elif up is None:
                st.warning("파일을 업로드해 주세요.")
            else:
                try:
                    name = up.name
                    ext = name.lower().rsplit(".", 1)[-1]

                    if ext == "txt":
                        text = read_txt(up)
                    elif ext == "docx":
                        text = read_docx(up)
                    elif ext == "pdf":
                        text = read_pdf(up)
                    else:
                        raise RuntimeError("지원하지 않는 파일 형식입니다.")

                    with st.spinner("파일 전체 처리 중..."):
                        result = translate_long(text)

                    st.session_state.last_source = text
                    st.session_state.last_result = result
                    st.session_state.last_file_name = name

                    st.session_state.history.insert(0, {
                        "ts": now_ts(),
                        "type": "file",
                        "file": name,
                        "target_lang": target_lang,
                        "mode": mode,
                        "tone": tone,
                        "source": text,
                        "result": result
                    })

                    st.success(f"완료: {name}")
                    st.text_area("결과", value=result, height=320)

                    base = safe_base_name(name) + f"_{target_lang}"
                    d1, d2 = st.columns(2)
                    with d1:
                        st.download_button(
                            "📤 TXT 다운로드",
                            data=result.encode("utf-8"),
                            file_name=f"{base}.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
                    with d2:
                        st.download_button(
                            "📤 DOCX 다운로드",
                            data=make_docx_bytes(f"{name} 번역 결과", result) if DOCX_OK else b"",
                            file_name=f"{base}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True,
                            disabled=not DOCX_OK
                        )

                except Exception as e:
                    st.error(f"파일 처리 실패: {e}")

st.markdown("---")
st.subheader("🔎 빠른 설명 (자동 단어장 저장)")

sel = st.text_input("단어/문장 붙여넣기", placeholder="드래그 → Ctrl+C → 여기에 Ctrl+V")
ctx = st.selectbox("설명 기준", ["원문 기준", "번역문 기준", "둘 다 참고"], index=2)

if st.button("설명하기", use_container_width=True):
    if not api_key:
        st.warning("사이드바에 API 키를 입력해 주세요. (Cloud 배포면 Secrets에 넣으면 자동으로 인식돼요)")
    elif not sel.strip():
        st.warning("설명할 단어/문장을 입력해 주세요.")
    else:
        try:
            with st.spinner("설명 생성 중..."):
                base = ""
                if ctx in ("원문 기준", "둘 다 참고") and st.session_state.last_source:
                    base += f"[원문]\n{st.session_state.last_source[:4000]}\n\n"
                if ctx in ("번역문 기준", "둘 다 참고") and st.session_state.last_result:
                    base += f"[번역]\n{st.session_state.last_result[:4000]}\n\n"

                prompt = f"""선택한 단어/문장을 쉽게 설명해줘.

- 의미(핵심 뜻)
- 문맥에서의 뉘앙스
- 쉬운 예문 1~2개
- 대체 표현(가능하면)

선택:
{sel}

문맥:
{base}
"""
                explanation = call_gemini(prompt)

            st.info(explanation)

            st.session_state.vocab.insert(0, {
                "ts": now_ts(),
                "selection": sel.strip(),
                "explanation": explanation.strip(),
                "context_mode": ctx,
                "source_file": st.session_state.last_file_name
            })

            st.success("단어장에 자동 저장했어.")

        except Exception as e:
            st.error(f"설명 실패: {e}")
