"""차트. 단일 측정값 = 단일 hue, 가로 막대, 내림차순, 직접 % 라벨. 범례 없음."""
import plotly.graph_objects as go

LIGHT = {"teal": "#0E5E53", "muted": "#AFC9C2", "ink": "#14171A", "grid": "#E4E6E3"}
DARK = {"teal": "#3CC7AC", "muted": "#2A4E48", "ink": "#E6EAE8", "grid": "#2A2D2C"}


def rank_bar(labels, values, focus_idx=None, title="", dark=False):
    """values는 백분율(61.3), 비율(0.613) 아님."""
    c = DARK if dark else LIGHT
    colors = [c["teal"] if (focus_idx is None or i == focus_idx) else c["muted"]
              for i in range(len(values))]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, line_width=0),
        text=[f"{v:.1f}%" for v in values],
        texttemplate="%{text}", textposition="outside", textfont=dict(color=c["ink"]),
        hovertemplate="%{y} · %{x:.1f}%<extra></extra>", width=0.62,
    ))
    fig.update_layout(
        title=title, bargap=0.38, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(autorange="reversed"),
        # 범위를 최대값보다 늘려 바깥 라벨 자리를 만든다 (없으면 1위 라벨이 잘린다).
        xaxis=dict(showgrid=True, gridcolor=c["grid"], ticksuffix="%", zeroline=False,
                   range=[0, max(values) * 1.18] if values else None),
        font=dict(family="Apple SD Gothic Neo, Pretendard, sans-serif", color=c["ink"]),
        margin=dict(l=8, r=48, t=48, b=8),
        height=max(220, 34 * len(labels) + 80),
    )
    return fig


def chart_for(call, dark=False):
    """툴 호출 결과 -> (fig, 표 데이터). 차트로 그릴 게 없으면 (None, 표|None).

    가중치/순위만 차트. 목록/프로필은 표.
    """
    result = call.result or {}
    if not result.get("found"):
        return None, None

    if call.name == "get_sector_weights":
        rows = result["sectors"]
        labels = [r["sector_ko"] for r in rows]
        values = [r["weight"] * 100 for r in rows]
        title = f"{result['ticker']} 섹터 비중"
        return rank_bar(labels, values, focus_idx=None, title=title, dark=dark), \
            [{"섹터": l, "비중": f"{v:.1f}%"} for l, v in zip(labels, values)]

    if call.name == "rank_countries_by_sector":
        rows = result["ranking"][:8]
        labels = [f"{i + 1}. {r['country']}({r['ticker']})" for i, r in enumerate(rows)]
        values = [r["weight"] * 100 for r in rows]
        title = f"{result.get('sector_ko', '')} 비중 상위 국가"
        return rank_bar(labels, values, focus_idx=0, title=title, dark=dark), \
            [{"국가": l, "비중": f"{v:.1f}%"} for l, v in zip(labels, values)]

    if call.name == "get_top_holdings":
        rows = result["holdings"]
        labels = [r["name"][:24] for r in rows]
        values = [r["weight"] * 100 for r in rows]
        title = f"{result['ticker']} 상위 보유 종목"
        return rank_bar(labels, values, title=title, dark=dark), \
            [{"종목": r["name"], "티커": r["symbol"], "비중": f"{r['weight'] * 100:.1f}%"} for r in rows]

    if call.name == "get_country_etfs":
        return None, [{"티커": e["ticker"], "이름": e["name"],
                       "3개월": f"{e['ret_3mo']:+.1f}%" if e["ret_3mo"] is not None else "—",
                       "1년": f"{e['ret_1y']:+.1f}%" if e["ret_1y"] is not None else "—"}
                      for e in result["etfs"]]

    if call.name == "get_sector_landscape":
        rows = result["industries"][:10]
        labels = [r["industry_name"][:24] for r in rows]
        values = [r["weight"] * 100 for r in rows]
        title = f"{result.get('sector_ko', '')} 섹터 세부 산업 비중"
        return rank_bar(labels, values, title=title, dark=dark), \
            [{"산업": r["industry_name"], "비중": f"{r['weight'] * 100:.1f}%",
              "대표종목": ", ".join(c["symbol"] for c in r["top_companies"][:3])} for r in rows]

    if call.name == "get_industry":
        table = []
        for g in result["groups"]:
            for c in g["top_companies"][:5]:
                table.append({"산업": g["industry_name"], "종목": c["name"], "티커": c["symbol"],
                              "산업내 비중": f"{c['weight'] * 100:.1f}%"})
        return None, table

    if call.name == "search_concepts":
        return None, [{"출처": c["source"], "페이지": c["page"], "유사도": f"{c['score']:.2f}",
                       "발췌": c["text"].split("]", 1)[-1].strip()[:120] + "…"}
                      for c in result["chunks"]]

    if call.name in ("get_etf_profile", "get_sector_etf"):
        e = result if call.name == "get_etf_profile" else result["etf"]
        return None, [{"티커": e["ticker"], "이름": e["name"],
                       "3개월": f"{e['ret_3mo']:+.1f}%" if e.get("ret_3mo") is not None else "—",
                       "1년": f"{e['ret_1y']:+.1f}%" if e.get("ret_1y") is not None else "—"}]

    if call.name == "web_search":
        return None, [{"제목": r.get("title", ""), "출처": r.get("url", "")}
                      for r in result.get("results", [])]

    return None, None


def as_of(call) -> str | None:
    """툴 결과에서 기준일(updated_at)을 찾는다."""
    result = call.result or {}
    for value in (result.get("updated_at"), *(e.get("updated_at") for e in result.get("etfs", [])),
                  (result.get("etf") or {}).get("updated_at")):
        if value:
            return value[:10]
    return None
