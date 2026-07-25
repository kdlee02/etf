"""Upstage Solar function-calling 루프. 툴 트레이스를 뽑아서 UI 근거 패널에 넘긴다.

OpenAI 호환 API라 도구 루프를 직접 돈다. tool_call_id로 호출-응답이 명시적으로 짝지어진다.
"""
import inspect
import json
import os
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from .prompts import SYSTEM_INSTRUCTION, UNGROUNDED_INSTRUCTION
from .tools import TOOLS
from .universe import COUNTRY_ETFS, SECTOR_KO_MAP

MODEL = "solar-pro3"  # 병렬 tool call은 pro3 전용
BASE_URL = "https://api.upstage.ai/v1"
MAX_TOOL_ROUNDS = 5  # 폭주 방지. 실제로는 1~2회면 끝난다.

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
    """.env에서 API 키를 읽는다. python-dotenv 없이 (ponytail: 두 줄이면 된다)."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


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
    """도구에 없는 티커가 있으면 한 번만 자가수정 재생성. 없으면 원문 그대로 (재발해도 루프 안 돈다)."""
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


def ask(question: str, grounded: bool = True) -> Answer:
    """질문에 답한다. grounded=False면 도구 없이 — 일반 LLM 비교용(환각 시연)."""
    if grounded and (reask := _bare_topic(question)):
        return Answer(text=_with_disclaimer(reask))  # 도구 없이 되묻는다 — 근거도 없다

    client = _client()
    registry = {fn.__name__: fn for fn in TOOLS}
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_INSTRUCTION if grounded else UNGROUNDED_INSTRUCTION},
        {"role": "user", "content": question},
    ]

    if not grounded:
        response = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
        return Answer(text=_with_disclaimer(response.choices[0].message.content or ""),
                      grounded=False)

    trace: list[ToolCall] = []
    schemas = [_schema(fn) for fn in TOOLS]
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=schemas,
            tool_choice="auto", parallel_tool_calls=True, temperature=0,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            text = _reground(message.content or "답변을 생성하지 못했습니다.", trace, client, messages)
            return Answer(text=_with_disclaimer(text), tool_calls=trace)

        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = registry.get(call.function.name)
            # 툴은 raise 하지 않지만, 모델이 없는 이름이나 이상한 인자를 줄 수 있다.
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

    # 라운드를 다 썼다 — 도구 결과는 있으니 마지막으로 도구 없이 정리시킨다.
    final = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    text = _reground(final.choices[0].message.content or "답변을 생성하지 못했습니다.", trace, client, messages)
    return Answer(text=_with_disclaimer(text), tool_calls=trace)


if __name__ == "__main__":
    import sys

    answer = ask(" ".join(sys.argv[1:]) or "한국에 투자하는 ETF랑 주요 종목/섹터 알려줘")
    print(answer.text)
    print("\n--- 호출된 도구 ---")
    for call in answer.tool_calls:
        print(f"{call.name}({call.args}) -> found={(call.result or {}).get('found')}")
    if not answer.tool_calls:
        print("호출된 도구 없음 — 근거 없음")
