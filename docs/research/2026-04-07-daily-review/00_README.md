# 2026-04-07 Daily Review (KST)

## 한 줄 요약
오늘 30거래 / WR 3.3% / 손익 ₩−18,196 / 포트폴리오 ₩20.53M (−0.056%).

## 상세 표

| wallet | 거래 | WR | 평균손익 | PnL | 주요 exit |
|---|---:|---:|---:|---:|---|
| vpin_doge_wallet | 6 | 0% | −0.962% | **−5,835** | atr_stop_loss × 6 |
| stealth_3gate_wallet_1 | 10 | 0% | −1.129% | **−4,799** | atr_stop_loss × 8, breakeven_stop × 2 |
| vpin_eth_wallet | 4 | 0% | −0.248% | **−3,079** | ratchet_stop × 4 |
| vpin_ondo_wallet | 2 | 0% | −1.995% | **−2,660** | atr_stop_loss × 2 |
| accumulation_tree_wallet | 3 | 0% | −2.373% | −2,038 | atr_stop_loss × 2, breakeven × 1 |
| vpin_xrp_wallet | 1 | 0% | −0.497% | −143 | atr_stop_loss × 1 |
| **accumulation_dood_wallet** | 4 | **50%** | +0.158% | **+359** | atr_stop_loss × 2, profit_lock_trailing × 2 |
| **TOTAL** | **30** | **3.3%** | — | **−18,196** | — |

## 핵심 발견

### 1. vpin_doge SL 완화는 효과 없음
- 10:14 KST에 `atr_sl_multiplier 0.3 → 1.0` 적용 (`config/daemon.toml`)
- 적용 후 새 거래 6건 모두 atr_stop_loss
- **결론: SL 거리 문제가 아니라 진입 신호 자체가 박스권에서 잘못 작동**
- 조치: 비활성화 (이 문서 §행동 로그 참조)

### 2. vpin_eth ratchet_stop 4회 또 발생
- 1a 진단(어제)과 정확히 동일 패턴 반복
- ratchet 트리거가 익절 도달 전에 발동
- 가설 2 (래칫 완화) 검증 대기 중. **paper 30거래 룰 때문에 손도 못 대는 상태**

### 3. vpin_ondo 어제 흑자 → 오늘 −2.0%
- 어제 7거래 WR 71% +0.589% (유일 흑자)
- 오늘 2거래 WR 0% −1.995%
- **표본 7건 운빨 가설 강화** — Stage 2 가설 3 (ONDO 출구 SOL에 복제) 보류 권장

### 4. stealth_3gate 환경 미스매치 입증
- BTC bull regime + stealth gate fail (cycle 164)
- 10거래 WR 0%, 어제 누적 25→35 거래 WR ~14%
- stealth는 정의상 **조용한 매집** 환경 전략 → 명시 불장에 부적합
- 조치: 다음 세션에 active_regimes에서 "bull" 제거 검토

### 5. **🐛 신규 vpin 월렛 4개 "유령 상태"**
- vpin_mana_wallet, vpin_bat_wallet, vpin_pundix_wallet, vpin_orbs_wallet
- 14:17 KST 배포, daemon startup 메시지에 분명히 로드됨
- daemon.log 47k 라인에서 **tick 출력 0건**
- pyupbit으로 직접 캔들 fetch는 정상 작동 (KRW-MANA 등)
- bb_mr_doge/xrp/avax는 같이 배포됐지만 정상 ticking
- **multi_runtime 또는 candle dispatcher가 이 4개를 건너뛰는 미확인 버그**
- 별도 디버그 세션 필요

## 행동 로그

| 시각 KST | 행동 | 파일/명령 | 결과 |
|---|---|---|---|
| 15:35 | 일일 리뷰 분석 (paper-trades.jsonl 30건) | python ad-hoc | 위 표 산출 |
| 15:40 | 신규 월렛 OHLCV 진단 | journalctl + pyupbit | 4개 유령 월렛 발견 (vpin_mana/bat/pundix/orbs) |
| 15:45 | **vpin_doge_wallet 비활성화** | `config/daemon.toml:444-490` 주석 처리 + DISABLED 사유 블록 추가 | TOML 파싱 통과 |
| 15:46 | daemon 재시작 | `systemctl --user restart crypto-trader.service` | 새 PID 1013373, active |
| 15:46 | bb_mr 정상 ticking 확인 | journalctl | OK |
| 15:46 | vpin_mana 등 4개 유령 월렛 상태 변화 없음 | journalctl | 별도 디버그 필요 |

## 미해결 (다음 세션)
- [ ] vpin_mana/bat/pundix/orbs 유령 월렛 디버그
- [ ] vpin_eth ratchet trigger 임계 검토 (paper 30거래 후)
- [ ] stealth_3gate active_regimes에서 "bull" 제거
- [ ] Stage 2 가설 3 (ONDO 복제) 무효화 결정
- [ ] DB 마이그레이션 worktree(`feature/db-introduction`) 머지 또는 추가 step
