"""agent 회귀 테스트. 라이브 Solar 없이 OpenAI 호환 응답 모양만 흉내낸다."""
import json
from types import SimpleNamespace as NS

import pytest

from etf_agent import agent


def tool_call(call_id, name, args):
    return NS(id=call_id, type="function",
              function=NS(name=name, arguments=json.dumps(args)))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, **_):
        return {"role": "assistant", "content": self.content}


class FakeClient:
    """미리 정해둔 응답을 순서대로 뱉고, 받은 messages를 기록한다."""

    def __init__(self, *messages):
        self._queue = list(messages)
        self.seen: list[list[dict]] = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.seen.append(list(kwargs["messages"]))
        return NS(choices=[NS(message=self._queue.pop(0))])


@pytest.fixture
def fake(monkeypatch):
    def install(*messages):
        client = FakeClient(*messages)
        monkeypatch.setattr(agent, "_client", lambda: client)
        return client

    return install


def test_tool_calls_are_paired_by_id(fake, monkeypatch):
    """병렬 호출이 각자의 결과를 갖는다. (Gemini 버전에서 서로 덮어쓰던 버그.)"""
    monkeypatch.setattr(agent, "TOOLS", [
        lambda ticker: {"found": True, "who": "holdings"},
        lambda ticker: {"found": True, "who": "sectors"},
    ])
    agent.TOOLS[0].__name__ = "get_top_holdings"
    agent.TOOLS[1].__name__ = "get_sector_weights"
    fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(tool_calls=[tool_call("c1", "get_top_holdings", {"ticker": "EWY"}),
                                tool_call("c2", "get_sector_weights", {"ticker": "EWY"})]),
        FakeMessage(content="완료"),
    )
    answer = agent.ask("EWY 알려줘")
    assert [c.name for c in answer.tool_calls] == ["get_top_holdings", "get_sector_weights"]
    assert [c.result["who"] for c in answer.tool_calls] == ["holdings", "sectors"]


def test_tool_results_are_sent_back_with_matching_id(fake, monkeypatch):
    """tool 메시지가 tool_call_id를 달고 돌아가야 모델이 짝을 맞춘다."""
    monkeypatch.setattr(agent, "TOOLS", [lambda ticker: {"found": True}])
    agent.TOOLS[0].__name__ = "get_sector_weights"
    client = fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(tool_calls=[tool_call("abc123", "get_sector_weights", {"ticker": "EWY"})]),
        FakeMessage(content="완료"),
    )
    agent.ask("EWY 섹터")
    tool_msgs = [m for m in client.seen[-1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["abc123"]


def test_bare_topic_reasks_without_calling_the_model(fake):
    """'한국'은 질문이 아니라 주제다. 모델을 부르지 않고 되묻는다 (LLM은 0/3으로 못 지켰다)."""
    client = fake()  # 응답을 하나도 안 넣었다 — 모델을 부르면 IndexError로 터진다
    answer = agent.ask("한국")
    assert answer.tool_calls == []
    assert "?" in answer.text
    assert agent.DISCLAIMER in answer.text
    assert client.seen == [], "주제만 왔는데 모델을 호출했다"


@pytest.mark.parametrize("question", ["한국", "  대만 ", "반도체", "금융?"])
def test_bare_topics_are_detected(question):
    assert agent._bare_topic(question) is not None


@pytest.mark.parametrize("question", ["한국 ETF 알려줘", "비트코인 살까?", "반도체 비중 높은 나라"])
def test_real_questions_are_not_treated_as_topics(question):
    assert agent._bare_topic(question) is None


def test_no_tool_calls_returns_empty_trace(fake):
    """거절/재질의는 도구를 안 부른다 — 근거 패널이 '근거 없음'을 보여줄 수 있어야 한다."""
    fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(content="제공된 데이터에 없습니다. 투자 권유가 아닙니다."),
    )
    answer = agent.ask("비트코인 살까?")
    assert answer.tool_calls == []
    assert "제공된 데이터에 없습니다" in answer.text


def test_unknown_tool_name_does_not_crash(fake, monkeypatch):
    """모델이 없는 도구를 지어내도 루프가 깨지면 안 된다."""
    monkeypatch.setattr(agent, "TOOLS", [])
    fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(tool_calls=[tool_call("c1", "get_bitcoin_price", {})]),
        FakeMessage(content="그건 없습니다"),
    )
    answer = agent.ask("비트코인")
    assert answer.tool_calls[0].result["found"] is False


def test_bad_arguments_do_not_crash(fake, monkeypatch):
    """모델이 잘못된 인자를 줘도 TypeError로 루프가 죽으면 안 된다."""
    monkeypatch.setattr(agent, "TOOLS", [lambda ticker: {"found": True}])
    agent.TOOLS[0].__name__ = "get_sector_weights"
    fake(
        FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
        FakeMessage(tool_calls=[tool_call("c1", "get_sector_weights", {"wrong_arg": "x"})]),
        FakeMessage(content="오류"),
    )
    answer = agent.ask("뭔가")
    assert answer.tool_calls[0].result["found"] is False
    assert "잘못된 인자" in answer.tool_calls[0].result["reason"]


def test_malformed_json_arguments_do_not_crash(fake, monkeypatch):
    """arguments가 깨진 JSON이어도 죽지 않는다 (문서가 경고하는 케이스)."""
    monkeypatch.setattr(agent, "TOOLS", [lambda **kw: {"found": True}])
    agent.TOOLS[0].__name__ = "get_sector_weights"
    bad = NS(id="c1", type="function",
             function=NS(name="get_sector_weights", arguments="{not json"))
    fake(FakeMessage(content="scoped"),  # ← 추가: 분류기 응답
         FakeMessage(tool_calls=[bad]), FakeMessage(content="완료"))
    assert agent.ask("뭔가").tool_calls[0].args == {}


def test_ungrounded_mode_sends_no_tools(fake):
    """일반 LLM 비교 모드는 도구를 전달하지 않는다."""
    client = fake(FakeMessage(content="아마 삼성이 30%쯤?"))
    answer = agent.ask("한국 ETF", grounded=False)
    assert answer.grounded is False
    assert answer.tool_calls == []
    assert agent.UNGROUNDED_INSTRUCTION in client.seen[0][0]["content"]


def test_schema_generation_marks_optional_params():
    """기본값 있는 인자는 required에서 빠져야 한다."""
    from etf_agent.tools import get_top_holdings

    schema = agent._schema(get_top_holdings)["function"]
    assert schema["parameters"]["required"] == ["ticker"]
    assert set(schema["parameters"]["properties"]) == {"ticker", "n"}
    assert schema["parameters"]["properties"]["n"]["type"] == "integer"
