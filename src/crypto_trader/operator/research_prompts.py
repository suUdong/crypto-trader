from __future__ import annotations


def build_hypothesis_prompt(quality_summary: str, history_tail: str) -> str:
    return f"""crypto-trader 프로젝트의 백테스트 히스토리와 품질 평가를 보고
다음에 탐색할 전략 아이디어를 1개만 제안해.

== 품질 평가 요약 ==
{quality_summary if quality_summary else '(아직 없음)'}

== 최근 백테스트 히스토리 ==
{history_tail}

형식:
전략명: <이름>
가설: <한 줄 설명>
탐색 파라미터: <핵심 파라미터 3개 이내>
예상 스크립트: <scripts/ 디렉토리에 만들 파일명>
근거: <왜 이게 다음 탐색 대상인지> (유망 결과를 발전시키거나 poor를 피하는 방향으로)

중복 실험 금지. 과거에 없는 새로운 시도만."""


def build_followup_prompt(
    *,
    task_desc: str,
    sharpe: float,
    raw_tail: str,
    history_tail: str,
    python_path: str,
) -> str:
    return f"""crypto-trader 백테스트에서 유망한 결과가 나왔다.
즉시 다음 단계 스크립트를 작성해라.

== 방금 완료된 태스크 ==
전략: {task_desc}
Sharpe: {sharpe:+.3f}
결과 상세:
{raw_tail}

== 최근 히스토리 ==
{history_tail}

## 지시
이 결과를 발전시키는 후속 백테스트 스크립트 1개를 scripts/ 에 작성해라.
- 파라미터 범위 확장, 필터 추가, 복합 조건 등 다음 단계
- Python: {python_path}, 데이터: data/historical/monthly/
- 결과에 "Sharpe: X.XX", "WR: XX.X%", "trades: N" 포함

완료 후 반드시 출력:
NEW_TASK id=<snake_case_id> script=<파일명.py> desc=<한줄설명>"""


def build_replenish_prompt(
    *,
    promising_summary: str,
    done_ids: list[str],
    poor_ids: list[str],
    history_tail: str,
    python_path: str,
) -> str:
    done_text = ", ".join(done_ids) or "없음"
    poor_text = ", ".join(poor_ids) or "없음"
    return f"""crypto-trader 전략 연구 루프의 파이프라인이 소진됐다.
아래 데이터를 분석하고 새로운 백테스트 스크립트 2개를 직접 작성해서 scripts/ 디렉토리에 저장해라.

== 유망 결과 (발전시킬 것) ==
{promising_summary}

== 완료된 태스크 (중복 금지) ==
{done_text}

== 엣지 없는 전략 (재탐색 불필요) ==
{poor_text}

== 최근 백테스트 히스토리 ==
{history_tail}

## 지시사항
1. 위 유망 결과를 이어받거나, 아직 탐색 안 한 새로운 가설을 선택
2. 각 전략에 대해 scripts/backtest_XXX.py 파일을 직접 작성 (실행 가능한 완성 코드)
   - Python: {python_path}
   - 데이터: data/historical/monthly/ 경로 사용
   - 결과 출력: "Sharpe: X.XX", "WR: XX.X%", "trades: N" 형식 포함
3. 스크립트 작성 완료 후 반드시 아래 형식으로 출력:

NEW_TASK id=<snake_case_id> script=<파일명.py> desc=<한줄설명>
NEW_TASK id=<snake_case_id> script=<파일명.py> desc=<한줄설명>

규칙: Safety 상수 변경 금지. .venv/bin/python 사용. 완료 후 git commit."""


def build_quality_review_prompt(
    *,
    stats: dict[str, int],
    promising_lines: str,
    history_tail: str,
) -> str:
    return f"""crypto-trader 자율 전략 연구 루프의 품질 리뷰어 역할이야.
아래 데이터를 보고 간결하게 답해줘.

== 품질 통계 (전체 누적) ==
promising: {stats['promising']}개 | marginal: {stats['marginal']}개
poor: {stats['poor']}개 | error: {stats['error']}개

== 유망 결과 목록 ==
{promising_lines or '없음'}

== 최근 백테스트 히스토리 (최신순) ==
{history_tail}

답해야 할 것:
1. 현재 연구 방향이 올바른가? (유망한 결과가 나오고 있는가)
2. poor/error 비율이 너무 높지 않은가? 원인은?
3. 다음 1주일 탐색 우선순위 3가지
4. 즉시 daemon에 반영 가능한 파라미터 변경이 있는가?

3~5문장으로 핵심만."""
