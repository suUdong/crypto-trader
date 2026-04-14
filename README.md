# Crypto Trader

Upbit 기반 다중 전략 자동매매 시스템. 멀티 월렛 데몬, 백테스트, 페이퍼 트레이딩, 실시간 대시보드를 지원합니다.

## 전략 목록

| 전략 | 설명 | 주요 파라미터 |
|------|------|--------------|
| **Momentum** | RSI + MACD + ADX 기반 모멘텀 추종 | `momentum_lookback`, `rsi_period`, `adx_threshold` |
| **Momentum Pullback** | 추세 유지 종목의 눌림목 재진입 하이브리드 | `momentum_lookback`, `bollinger_window`, `rsi_recovery_ceiling` |
| **VPIN** | Volume-Synchronized Probability of Informed Trading. 주문 흐름 독성도 측정 | `vpin_low/high_threshold`, `bucket_count` |
| **Volatility Breakout** | Larry Williams 변동성 돌파 (price > prev_close + k * range) | `k_base`, `noise_lookback`, `ma_filter_period` |
| **Kimchi Premium** | Upbit/Binance 가격 차이(김프) 기반 역발상 매매 | `cooldown_hours`, `min_trade_interval_bars` |
| **Volume Spike** | 비정상 거래량 급증 감지 + 방향성 확인 | `spike_mult`, `volume_window`, `min_body_ratio` |
| **Consensus** | 다중 전략 투표 시스템 (momentum + vpin + volume_spike) | `sub_strategies`, `weights`, `min_agree` |
| **EMA Crossover** | EMA 9/21 골든크로스/데드크로스 추세 추종 | `ema_fast`, `ema_slow` |
| **Mean Reversion** | 볼린저밴드 하단 매수, 상단 매도 | `bollinger_window`, `bollinger_stddev` |
| **OBI** | 호가창 매수/매도 불균형 기반 | `obi_threshold`, `max_holding_bars` |

모든 전략은 레짐(bull/bear/sideways) 자동 감지 및 파라미터 동적 조정을 지원합니다.

## 현재 운용 월렛 (config/daemon.toml)

총 13개 월렛, 자본금 13,000,000 KRW (페이퍼), 대상 심볼: BTC, ETH, XRP, SOL

| 월렛 | 전략 | 심볼 | Sharpe |
|------|------|------|--------|
| momentum_btc | Momentum | BTC | 2.51 |
| momentum_eth | Momentum | ETH | 4.86 |
| kimchi_premium | Kimchi Premium | BTC/ETH/XRP/SOL | 1.22 |
| vpin_btc | VPIN | BTC | 3.40 |
| vpin_eth | VPIN | ETH | 2.05 |
| vpin_sol | VPIN | SOL | 2.55 |
| vbreak_btc | Volatility Breakout | BTC | — |
| vbreak_eth | Volatility Breakout | ETH | — |
| volspike_btc | Volume Spike | BTC | — |
| volspike_eth | Volume Spike | ETH | — |
| consensus_btc | Consensus | BTC | — |
| ema_cross_btc | EMA Crossover | BTC | — |
| mean_rev_eth | Mean Reversion | ETH | — |

## 퀵스타트

```bash
# 의존성 설치
pip install -e ".[dev]"

# 백테스트
python -m crypto_trader.cli backtest --config config/example.toml

# 전체 전략 백테스트
python -m crypto_trader.cli backtest-all --config config/daemon.toml

# 데몬 시작 (페이퍼 트레이딩, 내부 auto-restart 포함)
scripts/restart_daemon.sh config/daemon.toml

# 대시보드
streamlit run dashboard/app.py
```

## 프로젝트 구조

```
src/crypto_trader/
├── cli.py              # 28개 CLI 명령어
├── config.py           # TOML 설정 파서
├── multi_runtime.py    # 멀티 심볼 데몬 런타임
├── strategy/           # 전략 모듈 (10개)
├── risk/               # 리스크 관리 (kill switch, correlation guard)
├── execution/          # 주문 실행 (paper broker)
├── notifications/      # Telegram, Slack 알림
├── monitoring/         # 성과 리포터, 구조화 로깅
├── operator/           # 드리프트, 프로모션 게이트, 저널
├── backtest/           # 백테스트 엔진, walk-forward
├── data/               # Upbit/Binance/FX 클라이언트
└── macro/              # 매크로 레짐 어댑터

config/                 # TOML 설정 파일
dashboard/              # Streamlit 대시보드
scripts/                # 운영 진입점 + 연구 유틸 + 역사적 실험 스크립트
artifacts/              # 런타임 아티팩트 (heartbeat, health, checkpoint, 리포트)
```

운영/연구 스크립트 표면 분류는 [scripts/README.md](scripts/README.md)를 기준으로 관리합니다.

## 개발

```bash
python3 -m unittest discover -s tests -t . -v   # 테스트
ruff check src/ tests/                            # CI 기준 린트
mypy src                                          # 애플리케이션 패키지 타입 체크
```

참고:
- 현재 레포는 전역 정적검사 적체가 있어, 대규모 정리 전까지는 changed-file 기준 `ruff`/`mypy` 검사를 병행합니다.
- `scripts/`는 운영 표면과 역사적 실험 자산이 섞여 있으므로, 변경 시 [scripts/README.md](scripts/README.md)의 분류를 먼저 확인합니다.

자세한 운영 가이드는 [docs/operations.md](docs/operations.md)를 참조하세요.
