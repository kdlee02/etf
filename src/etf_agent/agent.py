"""Upstage Solar function-calling 루프. 툴 트레이스를 뽑아서 UI 근거 패널에 넘긴다.

OpenAI 호환 API라 도구 루프를 직접 돈다. tool_call_id로 호출-응답이 명시적으로 짝지어진다.
"""
import inspect
import json
import logging
import os
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from openai import OpenAI

from .prompts import (ROUTER_INSTRUCTION, SYSTEM_INSTRUCTION,
                       UNGROUNDED_INSTRUCTION, WEB_INSTRUCTION)
from .tools import TOOLS
from .universe import COUNTRY_ETFS, SECTOR_KO_MAP

log = logging.getLogger(__name__)

MODEL = "solar-pro3"  # 병렬 tool call은 pro3 전용
BASE_URL = "https://api.upstage.ai/v1"
MAX_TOOL_ROUNDS = 5  # 폭주 방지 상한. 실제 tool-call 라운드 수는 _run_scoped가 INFO 로그로 남긴다
                     # (상한 소진 시 WARNING). 분포를 보고 이 값의 여유가 적절한지 확인.

# RFP 컴플라이언스 요건이라 모델의 기분에 맡기지 않는다. 프롬프트에도 넣지만 코드로 보장한다.
DISCLAIMER = "투자 권유가 아닙니다."


@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict | None = None


@dataclass
class Answer:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    grounded: bool = True

    @property
    def has_evidence(self) -> bool:
        return any(c.result and c.result.get("found") for c in self.tool_calls)


def _load_env() -> None:
    """.env에서 API 키를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다(override=False = 기존 setdefault 동작)."""
    from dotenv import load_dotenv  # 지연 임포트: 임포트 비용 회피
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


_cached_client: OpenAI | None = None


def _client() -> OpenAI:
    global _cached_client
    if _cached_client is None:
        _load_env()
        key = os.environ.get("UPSTAGE_API_KEY")
        if not key:
            raise RuntimeError("UPSTAGE_API_KEY가 없습니다. .env에 넣어주세요.")
        _cached_client = OpenAI(api_key=key, base_url=BASE_URL)
    client = _cached_client
    assert client is not None
    return client


def _bare_topic(question: str) -> str | None:
    """'한국'처럼 주제만 온 입력이면 되물을 문구를 돌려준다. 아니면 None.

    LLM에 맡기면 안 지킨다(측정: 0/3). 딕셔너리 조회로 끝나는 판단을 모델에 시킬 이유가 없다.
    """
    topic = question.strip().rstrip("?？ ").strip()
    if topic in set(COUNTRY_ETFS.values()):
        return (f"{topic}에 대해 ETF 목록, 주요 보유 종목, 섹터 비중 중 "
                f"어떤 것이 궁금하신가요?")
    if topic in SECTOR_KO_MAP:
        return f"{topic}에 대해 관련 ETF, 국가별 비중 중 어떤 것이 궁금하신가요?"
    return None


def _with_disclaimer(text: str) -> str:
    """고지가 없으면 붙인다. 프롬프트로 지시해도 모델이 빠뜨릴 때가 있다 (측정됨)."""
    return text if DISCLAIMER in text else f"{text.rstrip()}\n\n{DISCLAIMER}"


# 답변에서 티커로 오인되는 비-티커 대문자 토큰. 오탐 방지 스톱리스트.
_TICKER_STOPWORDS = {
    "ETF", "ETFS", "TER", "NAV", "LP", "AP", "GICS", "ESG", "AUM", "US", "USA",
    "KR", "EU", "AI", "IT", "RFP", "PDF", "MSCI", "SPDR", "REIT", "REITS", "IPO",
    "PER", "PBR", "ROE", "CEO", "TV", "GDP", "OK", "FAQ", "S&P", "NASDAQ",
}
# 경계를 \b 대신 라틴 영숫자 lookaround로: "KXI가"처럼 한글 조사가 붙어도 잡는다(\b는 한글에 안 걸림).
_TICKER_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,5}(?:-[A-Z])?(?![A-Za-z0-9])")


def _ungrounded_tickers(text: str, trace: list["ToolCall"]) -> set[str]:
    """답변의 티커 중 어떤 도구 결과에도 없는 것 = 모델이 지어낸 것. solar 부정규칙 약점을 코드로 잡는다."""
    blob = json.dumps([c.result for c in trace], ensure_ascii=False).upper()
    grounded = set(_TICKER_RE.findall(blob))
    return {t for t in _TICKER_RE.findall(text) if t not in grounded and t not in _TICKER_STOPWORDS}


def _reground(text: str, trace: list["ToolCall"], client, messages: list[dict]) -> str:
    """도구에 없는 티커가 있으면 한 번만 자가수정 재생성. 없으면 원문 그대로.

    1회로 멈추는 이유(의도된 트레이드오프): 근거 없는 티커가 남는다는 건 도구 결과에
    해당 종목이 아예 없다는 뜻이라, 재시도해도 모델이 끌어올 근거가 없어 잘 안 잡힌다.
    2회 이상은 지연·비용만 늘고 회수율은 미미 → 1회 시도 후 남으면 감수한다.
    (재검증/재재생성은 일부러 안 한다: 무한 루프·비용 방지.)
    """
    bad = _ungrounded_tickers(text, trace)
    if not bad:
        return text
    followup = messages + [
        {"role": "assistant", "content": text},
        {"role": "user", "content":
            f"방금 답변의 다음 티커는 도구가 반환하지 않은 것입니다: {', '.join(sorted(bad))}. "
            f"이 티커와 그 티커를 언급한 ETF 추천 문장을 모두 삭제하고, 도구 결과에 있는 내용만으로 다시 작성하세요."}]
    retry = client.chat.completions.create(model=MODEL, messages=followup, temperature=0)
    return retry.choices[0].message.content or text


_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _schema(fn) -> dict:
    """파이썬 함수 -> OpenAI tool 스키마.

    시그니처에서 생성한다: 손으로 쓴 스키마는 인자를 고칠 때 조용히 어긋난다.
    설명은 docstring에서 가져온다 (첫 문단 = 함수 설명, 'Args:' 줄 = 인자 설명).
    """
    doc = inspect.getdoc(fn) or ""
    head, _, args_block = doc.partition("Args:")
    arg_docs = {}
    for line in args_block.splitlines():
        name, sep, desc = line.strip().partition(":")
        if sep and name.isidentifier():
            arg_docs[name] = desc.strip()

    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        hint = typing.get_type_hints(fn).get(name, str)
        props[name] = {"type": _JSON_TYPES.get(hint, "string"),
                       "description": arg_docs.get(name, name)}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {"type": "function", "function": {
        "name": fn.__name__,
        "description": head.strip().split("\n\n")[0],
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


def _stream_text(client, messages, on_token) -> str:
    """도구 없는 생성을 스트리밍하며 델타를 on_token으로 흘리고 전체 텍스트를 모아 반환."""
    text = ""
    for chunk in client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0, stream=True):
        delta = chunk.choices[0].delta.content or ""
        if delta:
            text += delta
            on_token(delta)
    return text


def _round(client, messages, tools=None, on_token=None):
    """툴루프 한 라운드. 반환: (content, tool_calls, assistant_msg_dict).

    on_token이 있으면 stream=True로 content 토큰을 흘리고, 스트림된 tool_call 델타를 재조립한다.
    tool_calls는 .id / .function.name / .function.arguments 인터페이스를 갖는다(비스트림과 동일).
    """
    kw = {"model": MODEL, "messages": messages, "temperature": 0}
    if tools:
        kw.update(tools=tools, tool_choice="auto", parallel_tool_calls=True)
    if on_token is None:
        msg = client.chat.completions.create(**kw).choices[0].message
        return msg.content or "", list(msg.tool_calls or []), msg.model_dump(exclude_none=True)

    content = ""
    slots: dict = {}  # index -> {id, name, args}. 델타가 조각조각 와서 index로 누적한다.
    for chunk in client.chat.completions.create(stream=True, **kw):
        delta = chunk.choices[0].delta
        if delta.content:
            content += delta.content
            on_token(delta.content)  # ponytail: 이 툴들은 content와 tool_call을 같이 안 뱉어 최종 답변만 흐른다
        for tc in (delta.tool_calls or []):
            s = slots.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if tc.id:
                s["id"] = tc.id
            if tc.function and tc.function.name:
                s["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                s["args"] += tc.function.arguments
    ordered = [slots[i] for i in sorted(slots)]
    calls = [SimpleNamespace(id=s["id"],
                             function=SimpleNamespace(name=s["name"], arguments=s["args"]))
             for s in ordered]
    assistant = {"role": "assistant", "content": content or None}
    if ordered:
        assistant["tool_calls"] = [{"id": s["id"], "type": "function",
                                    "function": {"name": s["name"], "arguments": s["args"]}}
                                   for s in ordered]
    return content, calls, assistant


def _run_ungrounded(question: str, on_token=None) -> Answer:
    """도구 없이 답한다 — 일반 LLM 비교용(환각 시연)."""
    client = _client()
    messages = [{"role": "system", "content": UNGROUNDED_INSTRUCTION},
                {"role": "user", "content": question}]
    if on_token is None:
        body = client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0).choices[0].message.content or ""
    else:
        body = _stream_text(client, messages, on_token)
    return Answer(text=_with_disclaimer(body), grounded=False)


def _run_scoped(question: str, on_token=None) -> Answer:
    """스코프 내 질문을 function-calling tool 루프로 답한다. (bare_topic은 ask에서 걸러진다.)

    on_token이 있으면 최종 답변 생성을 스트리밍한다. 단, 스트림된 텍스트는 _reground 이전 미리보기다 —
    근거 없는 티커가 있으면 _reground가 재작성하므로 최종 Answer.text가 권위를 갖는다(호출자가 최종 렌더).
    """
    client = _client()
    registry = {fn.__name__: fn for fn in TOOLS}
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": question},
    ]
    trace: list[ToolCall] = []
    schemas = [_schema(fn) for fn in TOOLS]
    for turn in range(1, MAX_TOOL_ROUNDS + 1):
        content, tool_calls, assistant = _round(client, messages, tools=schemas, on_token=on_token)
        if not tool_calls:
            log.info("tool-call rounds: %d/%d", turn - 1, MAX_TOOL_ROUNDS)  # 마지막 turn은 답변만
            text = _reground(content or "답변을 생성하지 못했습니다.", trace, client, messages)
            return Answer(text=_with_disclaimer(text), tool_calls=trace)

        messages.append(assistant)
        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = registry.get(call.function.name)
            if fn is None:
                result = {"found": False, "reason": f"알 수 없는 도구: {call.function.name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"found": False, "reason": f"잘못된 인자: {e}"}
            trace.append(ToolCall(call.function.name, args, result))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "name": call.function.name,
                             "content": json.dumps(result, ensure_ascii=False)})

    log.warning("MAX_TOOL_ROUNDS(%d) 소진 — 상한이 낮을 수 있음", MAX_TOOL_ROUNDS)
    content, _, _ = _round(client, messages, on_token=on_token)
    text = _reground(content or "답변을 생성하지 못했습니다.", trace, client, messages)
    return Answer(text=_with_disclaimer(text), tool_calls=trace)


def _classify(question: str) -> str:
    """질문을 'scoped'/'web'/'reject'로 분류. 애매하면 scoped(안전 쪽 = 기존 동작 유지)."""
    client = _client()
    resp = client.chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": ROUTER_INSTRUCTION},
                  {"role": "user", "content": question}])
    label = (resp.choices[0].message.content or "").strip().lower()
    if "reject" in label:
        return "reject"
    return "web" if "web" in label else "scoped"


def _run_reject(question: str) -> Answer:
    """범위 밖 질문. 검색·도구 없이 거절만 한다 (근거 0회 → 근거 패널도 비어야 함)."""
    text = ("이 어시스턴트는 ETF·국가·섹터 리서치 범위의 질문에만 답합니다. "
            "해당 범위 밖이라 답변을 지어내지 않고 거절합니다.")
    return Answer(text=_with_disclaimer(text), grounded=False)


def _run_web(question: str, on_token=None) -> Answer:
    """오프토픽 질문을 웹검색 결과로 답한다. 사실만 + 고지, 매수/매도 조언 금지."""
    from .websearch import web_search  # 지연 임포트: 순환 회피
    hits = web_search(question)
    trace = [ToolCall("web_search", {"query": question}, hits)]
    if not hits.get("found"):
        text = _with_disclaimer("제공된 데이터에 없어 웹에서 찾아봤지만 신뢰할 만한 결과를 얻지 못했습니다.")
        if on_token:
            on_token(text)
        return Answer(text=text, tool_calls=trace)
    client = _client()
    ctx = json.dumps(hits["results"], ensure_ascii=False)
    messages = [{"role": "system", "content": WEB_INSTRUCTION},
                {"role": "user", "content": f"질문: {question}\n\n웹 검색 결과:\n{ctx}"}]
    prefix = "🔎 웹에서 검색한 결과입니다.\n\n"
    if on_token is None:
        body = client.chat.completions.create(
            model=MODEL, temperature=0, messages=messages).choices[0].message.content
    else:
        on_token(prefix)
        body = _stream_text(client, messages, on_token)
    text = f"{prefix}{body or '검색 결과를 정리하지 못했습니다.'}"
    return Answer(text=_with_disclaimer(text), tool_calls=trace)


def ask(question: str, grounded: bool = True) -> Answer:
    """질문에 답한다. grounded=False면 도구 없이 — 일반 LLM 비교용(환각 시연)."""
    if not grounded:
        return _run_ungrounded(question)
    if reask := _bare_topic(question):
        return Answer(text=_with_disclaimer(reask))  # 도구 없이 되묻는다 — 근거도 없다
    from .graph import route  # 지연 임포트: agent <-> graph 순환 회피
    return route(question)


def ask_stream(question: str, grounded: bool = True, on_token=None) -> Answer:
    """스트리밍 답변. on_token(델타 문자열)로 토큰을 흘리고 최종 Answer를 반환한다.

    반환 Answer.text가 권위 있음 — _reground 재작성이나 CRAG 웹 폴백이 스트림 미리보기를
    대체할 수 있으므로, 호출자(UI)는 스트림이 끝나면 반드시 Answer.text로 최종 렌더해야 한다.
    라우팅은 graph.py의 route와 동일한 순서(bare_topic → classify → reject/web/scoped + CRAG)."""
    emit = on_token or (lambda _t: None)
    if not grounded:
        return _run_ungrounded(question, on_token=on_token)
    if reask := _bare_topic(question):
        ans = Answer(text=_with_disclaimer(reask))
        emit(ans.text)
        return ans
    route = _classify(question)
    if route == "reject":
        ans = _run_reject(question)
        emit(ans.text)
        return ans
    if route == "web":
        return _run_web(question, on_token=on_token)
    ans = _run_scoped(question, on_token=on_token)
    if not ans.has_evidence:  # CRAG: 스코프가 근거 0건이면 web으로 보정(미리보기는 최종 렌더가 대체)
        return _run_web(question, on_token=on_token)
    return ans


if __name__ == "__main__":
    import sys

    answer = ask(" ".join(sys.argv[1:]) or "한국에 투자하는 ETF랑 주요 종목/섹터 알려줘")
    print(answer.text)
    print("\n--- 호출된 도구 ---")
    for call in answer.tool_calls:
        print(f"{call.name}({call.args}) -> found={(call.result or {}).get('found')}")
    if not answer.tool_calls:
        print("호출된 도구 없음 — 근거 없음")
