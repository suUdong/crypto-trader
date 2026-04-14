# 데몬 버그: positions.json의 market_price가 entry_price로 고정되는 문제

발견 시각: 2026-04-07 23:45 KST
조사자: Claude (위임 작업)
**상태: 진단만 완료 — 수정 보류 (사용자 지시)**

## 증상

dashboard "현재 포지션"의 미실현 손익이 항상 0으로 표시되고, 새로고침해도 변하지 않음.

## 직접 확인

`artifacts/positions.json`:
```
KRW-ZBT  entry=158.1185      market=158.1185      upnl=0.0
KRW-ATH  entry=10.20765      market=10.20765      upnl=0.0
KRW-TAO  entry=481160.6      market=481160.6      upnl=0.0
KRW-ZBT  entry=151.0755      market=151.0755      upnl=0.0
```

→ 4개 포지션 전부 `market_price == entry_price` → unrealized_pnl=0

(daemon 재시작 전에는 TAO market=466800으로 정상이었음 — 재시작 후 깨짐)

## 코드 추적

### 1) `src/crypto_trader/wallet.py:412-430` — `position_metrics()`

```python
def position_metrics(self, latest_prices: Mapping[str, float]) -> list[...]:
    metrics: list = []
    for symbol, position in self.broker.positions.items():
        market_price = float(latest_prices.get(symbol, position.entry_price))
        # ↑ latest_prices에 symbol 없으면 entry_price를 fallback으로 사용
        metrics.append({
            "market_price": market_price,
            "unrealized_pnl": position.unrealized_pnl(market_price),
            ...
        })
```

### 2) `src/crypto_trader/multi_runtime.py:2029-2054` — `_refresh_position_snapshot()`

```python
latest_prices = self._latest_prices    # ← self._latest_prices 사용
positions = [
    metric
    for wallet in self._wallets
    for metric in wallet.position_metrics(latest_prices)
]
```

### 3) `_latest_prices`는 `_run_tick`에서 set됨 (line 465-469)

```python
latest_prices = {
    cached_symbol: symbol_candles[-1].close
    for cached_symbol, symbol_candles in candle_cache.items()
    if symbol_candles
}
```

`candle_cache`는 `_run_tick(symbols)`의 `symbols` 인자에 해당하는 종목만 fetch.
- `symbols = self._active_symbols = list(self._config.trading.symbols)` (line 360)

### 4) `config/daemon.toml:10` `trading.symbols`

```
symbols = ["KRW-ETH", "KRW-SOL", "KRW-BTC", "KRW-DOOD", "KRW-TREE",
           "KRW-XRP", "KRW-DOGE", "KRW-LINK", "KRW-ONDO", "KRW-AVAX",
           "KRW-APT", "KRW-ADA", "KRW-DOT", "KRW-ATOM", "KRW-ASTR",
           "KRW-CELO", "KRW-PEPE", "KRW-THETA"]
```

→ **ZBT, ATH, TAO, RED, ONG 같은 accumulation rotation 종목은 trading.symbols에 없음.**
이 종목들은 wallet 단위의 `[[wallets]] symbols = [...]`에만 등록돼서 wallet 자체적으로는 인지하지만, 글로벌 fetch loop는 안 돌림.

## 결론 (root cause)

market_scan_loop이 wallet rotation으로 채워 넣는 종목(accumulation_dood/tree wallet의 알트들)이 글로벌 `trading.symbols`에 없어서:

1. `_run_tick`이 그 종목 fetch를 안 함
2. `_latest_prices`에 해당 종목 가격이 들어가지 않음
3. `position_metrics`가 fallback으로 `entry_price`를 사용
4. positions.json에 `market_price == entry_price`로 기록
5. → unrealized_pnl 항상 0

재시작 전에는 (재시작 직전 tick에서 어쩌다 fetch된 적 있었으면) 일부 종목 살아 있었을 수 있음. 재시작 후엔 새 in-memory `_latest_prices`가 비어 있으니 전부 깨짐.

## 영향 범위

- dashboard 미실현 손익 부정확 (0으로 표시)
- daemon의 risk 평가, 트레일링 스톱, 포지션 리밸런싱 등이 모두 `_latest_prices` 기반이라면 동일하게 영향. 즉 **심볼이 trading.symbols 밖이면 daemon도 그 포지션의 시장가를 모름** → 손절·익절 트리거가 작동하지 않을 가능성.

## 수정 방향 (보류 — 작업 X)

다음 중 하나:

**A. 글로벌 symbols에 wallet allowed_symbols을 자동 union**
```python
self._active_symbols = sorted({
    *self._config.trading.symbols,
    *(s for w in self._wallets for s in w.allowed_symbols),
})
```
→ rotation으로 들어온 종목도 자동 포함. 가장 안전.

**B. position_metrics의 fallback에서 직접 fetch**
- snapshot 작성 시 빠진 종목만 단건 fetch
- 페이싱·rate limit 고려 필요

**C. SIGHUP hot-reload 시 active_symbols도 동기화**
- 이미 hot-reload 핸들러에 trading.symbols 갱신은 들어감 (multi_runtime 새 코드)
- 단, daemon.toml 글로벌 symbols가 안 바뀌면 의미 없음 → 결국 A안과 결합 필요

**권장: A안.** 한 줄 변경, 부작용 적음, 정확한 fix.

## 검증 방법

수정 후 daemon 재시작 → positions.json에서 market_price ≠ entry_price 확인 → dashboard에서 미실현 손익 변동 확인.
