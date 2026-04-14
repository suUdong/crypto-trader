# Research 디렉터리 — 사용 규칙

연구·분석 작업 결과물을 **날짜+주제** 기준으로 누적한다.

## 폴더 구조

```
docs/research/
├── README.md                       # 이 파일 — 사용 규칙
├── INDEX.md                        # 모든 연구 항목 시간순 인덱스
├── ACTIVITY_LOG.md                 # 매일 한 줄씩 작업 로그 (세션 무관 누적)
└── YYYY-MM-DD-{topic}/             # 개별 연구 단위
    ├── 00_README.md                # 이 연구의 목적·범위·결론·다음 액션
    ├── 01_stage1a_*.md             # 단계별 산출물 (번호 prefix로 정렬)
    ├── 02_stage1b_*.md
    └── ...
```

## 명명 규칙

- 폴더: `YYYY-MM-DD-{topic-kebab-case}` (예: `2026-04-07-strategy`, `2026-04-07-infra`)
- 단계 파일: `{NN}_{stage}_{slug}.md` — 두 자리 prefix로 정렬
- 한 연구 안에서 단계가 5개 넘으면 sub-stage(`01a`, `01b`)로 분할
- 새 주제는 새 폴더. 기존 폴더에 추가하지 말 것 (히스토리 추적성)

## 필수 규칙

1. **모든 연구 폴더는 `00_README.md`를 가져야 한다.**
2. 연구 시작 시 `INDEX.md`에 한 줄 추가, 종료 시 결론 한 줄 갱신
3. `ACTIVITY_LOG.md`에는 세션마다 무엇을 했는지 1~3줄로 누적 (날짜 prefix)
4. 데이터 출처 파일·라인 명시. 추측은 `[추정]` 태그
5. 단계별 산출물은 다음 단계가 입력으로 쓸 수 있게 자급자족
6. **세션 종료 전 ACTIVITY_LOG와 INDEX 갱신** — 다음 세션이 끊김 없이 이어가도록

## 다른 docs 디렉터리와의 구분

| 위치 | 용도 |
|---|---|
| `docs/research/` | 일회성 연구 결과·진단·가설 (이 디렉터리) |
| `docs/backtest_history.md` | 백테스트 누적 결과 (별도 — 기존 컨벤션 유지) |
| `docs/superpowers/plans/` | 구현 plan (코드 변경 동반) |
| `docs/operations.md` 등 | 항구적 운영 문서 |
| `docs/session-handoff-*.md` | 세션 인수인계 (이 폴더 안 들어옴) |
