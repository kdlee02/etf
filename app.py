"""Streamlit UI. `uv run streamlit run app.py`"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))  # 배포 시 editable 설치 없이도 임포트

import streamlit as st

from etf_agent.agent import ask
from etf_agent.charts import as_of, chart_for

STALE_DAYS = 7  # 이보다 오래된 스냅샷이면 UI에 갱신 경고

EXAMPLES = [
    "중국에 투자하고 싶은데 이 나라의 종목과 섹터 비율을 알려줘",
    "환헤지 ETF의 (H)가 무슨 뜻이야?",
    "비트코인 살까?",
]

st.set_page_config(page_title="ETF 리서치 어시스턴트", page_icon="📊", layout="wide")
st.title("📊 ETF 투자 리서치 어시스턴트")
st.caption("국가·섹터별 ETF를 실제 데이터로 조회합니다. 답변의 모든 수치는 도구 호출 결과입니다.")

if "history" not in st.session_state:
    st.session_state.history = []

grounded = st.sidebar.radio(
    "답변 방식", [True, False],
    format_func=lambda g: "근거 기반 (도구 호출)" if g else "일반 LLM (도구 없음)",
    help="'일반 LLM'은 도구 없이 답합니다 — 환각을 비교해 보세요.",
)
dark = st.sidebar.toggle("다크 모드 차트", value=False)
if st.sidebar.button("대화 지우기"):
    st.session_state.history = []
    st.rerun()


def render(entry):
    answer = entry["answer"]
    left, right = st.columns([2, 1])
    with left:
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            if entry.get("error"):
                st.error(answer.text, icon="⚠️")
                return
            if not answer.grounded:
                st.warning("도구 없이 생성된 답변입니다 — 수치는 검증되지 않았습니다.", icon="🎲")
            st.markdown(answer.text)
            for call in answer.tool_calls:
                fig, table = chart_for(call, dark=dark)
                if fig is not None:
                    st.plotly_chart(fig, width="stretch")
                    with st.expander("표로 보기"):
                        st.dataframe(table, width="stretch", hide_index=True)
                elif table:
                    st.dataframe(table, width="stretch", hide_index=True)
            dates = [d for d in (as_of(c) for c in answer.tool_calls) if d]
            if dates:
                latest = max(dates)
                note = f"기준일 {latest} · 캐시된 스냅샷이며 실시간 시세가 아닙니다."
                age = (date.today() - date.fromisoformat(latest)).days
                if age > STALE_DAYS:  # 갱신 정책: 일 1회 ingest 재실행
                    st.warning(f"{note} 데이터가 {age}일 전 기준입니다 — 갱신이 필요합니다.", icon="🕒")
                else:
                    st.caption(note)
    with right:
        st.markdown("**근거**")
        if not answer.tool_calls:
            st.info("호출된 도구 없음 — 근거 없음", icon="🚫")
        for call in answer.tool_calls:
            found = (call.result or {}).get("found")
            with st.expander(f"{'✅' if found else '❌'} `{call.name}`", expanded=True):
                st.caption("인자")
                st.json(call.args, expanded=False)
                st.caption("원본 결과")
                st.json(call.result, expanded=False)


for entry in st.session_state.history:
    render(entry)

if not st.session_state.history:
    st.info("국가나 섹터로 ETF를 찾아보세요. 아래 예시를 눌러 시작할 수 있습니다.", icon="👋")
    cols = st.columns(len(EXAMPLES))
    for col, example in zip(cols, EXAMPLES):
        if col.button(example, width="stretch"):
            st.session_state.pending = example
            st.rerun()

question = st.chat_input("예: 대만 ETF의 섹터 비중은?") or st.session_state.pop("pending", None)

if question:
    with st.status("답변 생성 중…", expanded=False) as status:
        try:
            status.update(label="도구 호출 중…")
            answer = ask(question, grounded=grounded)
            status.update(label="답변 생성 중…")
            entry = {"question": question, "answer": answer}
        except Exception as e:  # 카메라 앞에서 트레이스백 금지
            from etf_agent.agent import Answer

            entry = {"question": question, "error": True,
                     "answer": Answer(text=f"답변 중 문제가 생겼습니다. 다시 시도해 주세요.\n\n`{type(e).__name__}: {e}`")}
        status.update(label="완료", state="complete")
    st.session_state.history.append(entry)
    st.rerun()
