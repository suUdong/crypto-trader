# Order Book Imbalance (OBI) Strategy — Enhancement Plan

**Date**: 2026-03-29
**Priority**: P2
**Status**: Design
**Source**: strategy-playbook.md §3.1, crypto-strategy-research Cycles 11, 39; auto-invest Cycle 138

---

## 1. Current State

### What Exists

| Component | File | Status |
|-----------|------|--------|
| OBI Strategy class | `src/crypto_trader/strategy/obi.py` | ✅ Basic implementation |
| Models | `src/crypto_trader/models.py` | ✅ `OrderbookSnapshot`, `OrderbookEntry` |
| Tests | `tests/test_obi_strategy.py` | ✅ 5 tests passing |
| OrderbookProvider protocol | `strategy/obi.py:16` | ✅ Interface defined |
| Pyupbit orderbook fetch | `data/pyupbit_client.py` | ❌ Not implemented |
| WebSocket stream | — | ❌ Not implemented |
| Config in daemon.toml | `config/daemon.toml` | ❌ Not configured |
| Backtest support | — | ❌ No historical orderbook data |

### Current Strategy Logic

```
OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
Range: -1.0 (all asks) to +1.0 (all bids)

BUY:  OBI > threshold (0.45) AND RSI < overbought AND momentum >= 0
SELL: OBI < -threshold (-0.3) OR max_holding_bars exceeded OR RSI overbought
```

Fallback: when no orderbook provider is available, estimates OBI from candle
close-vs-open ratio over the last 5 bars (crude proxy).

---

## 2. Upbit Orderbook API

### 2.1 REST API (`pyupbit.get_orderbook`)

| Item | Detail |
|------|--------|
| **Endpoint** | `GET https://api.upbit.com/v1/orderbook?markets=KRW-BTC` |
| **Auth** | Not required (public) |
| **Rate Limit** | 10 req/sec per IP (shared with all REST endpoints) |
| **Response** | Top 15 bid/ask levels: `[{price, size}]` for each side |
| **pyupbit** | `pyupbit.get_orderbook(ticker="KRW-BTC")` returns dict |
| **Latency** | ~50-150ms per call |
| **Suitability** | Sufficient for 1-5 min candle intervals (polling) |

Response structure:
```json
{
  "market": "KRW-BTC",
  "timestamp": 1529910247984,
  "total_ask_size": 8.40105,
  "total_bid_size": 23.13914,
  "orderbook_units": [
    {"ask_price": 89000, "bid_price": 88900, "ask_size": 1.5, "bid_size": 3.2},
    ...
  ]
}
```

### 2.2 WebSocket API (Real-time)

| Item | Detail |
|------|--------|
| **Endpoint** | `wss://api.upbit.com/websocket/v1` |
| **Subscribe** | `[{"ticket":"obi"}, {"type":"orderbook", "codes":["KRW-BTC"]}]` |
| **Format** | Binary (MessagePack) or JSON via `"format":"DEFAULT"` |
| **Update Rate** | ~100-500ms depending on market activity |
| **Levels** | Top 15 bid/ask levels per update |
| **Connection Limit** | 5 WebSocket connections per IP |
| **Ping/Pong** | Send `PING` every 120s to keep alive |
| **Suitability** | Required for sub-minute OBI scalping |

### 2.3 Recommendation

**Phase 1: REST polling** — Use `pyupbit.get_orderbook()` within the existing
candle-interval loop. Zero architecture change. Adequate for 5-min+ strategies.

**Phase 2: WebSocket stream** — Needed only when pursuing the full OBI Scalper
(sub-second execution, P3 scope). Requires new `WebSocketDataProvider` and a
separate fast-loop runtime.

---

## 3. Enhancement Plan

### Phase 1: REST Orderbook Integration (This PR)

**Goal**: Connect real Upbit orderbook data to the existing OBI strategy.

#### 3.1 Extend `PyUpbitMarketDataClient`

Add `get_orderbook(symbol) -> OrderbookSnapshot | None` method:

```python
def get_orderbook(self, symbol: str) -> OrderbookSnapshot | None:
    module = self._module or _load_pyupbit()
    raw = module.get_orderbook(ticker=symbol)
    if not raw:
        return None
    units = raw[0]["orderbook_units"]  # pyupbit returns list
    bids = [OrderbookEntry(u["bid_price"], u["bid_size"]) for u in units]
    asks = [OrderbookEntry(u["ask_price"], u["ask_size"]) for u in units]
    return OrderbookSnapshot(
        symbol=symbol,
        bids=bids,
        asks=asks,
        timestamp=datetime.fromtimestamp(raw[0]["timestamp"] / 1000, tz=UTC),
    )
```

#### 3.2 Wire Provider into Pipeline

In `pipeline.py`, pass `PyUpbitMarketDataClient` as the `OrderbookProvider`
when the strategy is `"obi"`. The client already satisfies the protocol since
it will have the `get_orderbook(symbol)` method.

#### 3.3 Add OBI Config Parameters to TOML

```toml
[wallets.strategy_overrides]
strategy = "obi"
obi_buy_threshold = 0.45
obi_sell_threshold = -0.3
```

#### 3.4 Enhanced OBI Calculation

Improve the strategy with weighted OBI (closer price levels weighted more):

```python
def _calculate_weighted_obi(self, snapshot: OrderbookSnapshot) -> float:
    """Weight by inverse distance from mid-price for top N levels."""
    mid = (snapshot.bids[0].price + snapshot.asks[0].price) / 2
    bid_weighted = sum(e.size / max(1, mid - e.price) for e in snapshot.bids[:10])
    ask_weighted = sum(e.size / max(1, e.price - mid) for e in snapshot.asks[:10])
    total = bid_weighted + ask_weighted
    return (bid_weighted - ask_weighted) / total if total > 0 else 0.0
```

#### 3.5 Additional Filters

| Filter | Logic | Why |
|--------|-------|-----|
| **Spread filter** | Skip if spread > 0.3% | Wide spread = low liquidity, unreliable OBI |
| **Volume filter** | Require total book size > threshold | Thin books produce noisy OBI |
| **Depth imbalance** | Compare top-3 vs top-15 levels | Spoofing detection: surface vs deep imbalance divergence |

### Phase 2: WebSocket Stream (Future — P3)

Not in scope for this PR. Documented for reference.

| Component | Description |
|-----------|-------------|
| `WebSocketOrderbookProvider` | asyncio WebSocket client, auto-reconnect, MessagePack decode |
| `FastLoopRuntime` | Sub-second evaluation loop (separate from candle-interval runtime) |
| Orderbook snapshot buffer | Ring buffer of last N snapshots for rate-of-change analysis |
| OBI delta signal | `d(OBI)/dt` — acceleration of imbalance shift |

---

## 4. Backtest Considerations

### Problem

Upbit does not provide historical orderbook data. REST/WebSocket only gives
current snapshots. This makes traditional backtesting impossible for real OBI.

### Solutions

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| **Candle proxy (current)** | Already implemented, works with existing backtest | Low accuracy (~40% correlation with real OBI) | Done |
| **Forward-collect then backtest** | Real data, high accuracy | Needs weeks of collection before backtest | Medium |
| **Volume-tick reconstruction** | Better than candle proxy | Still an approximation | Medium |
| **Paper trading validation** | Real-world signal quality | No historical performance curve | Low |

### Recommendation

1. **Immediate**: Use candle proxy for backtest parameter tuning (thresholds, holding bars)
2. **Parallel**: Start collecting real orderbook snapshots (1-min intervals) to a local DB
3. **Week 2+**: Backtest on collected data, compare with candle proxy results
4. **Validation**: 2-week paper trading with real orderbook data before live

#### Orderbook Data Collector (for future backtest)

Simple cron job or daemon thread that polls `get_orderbook()` every 60s
and appends to a SQLite/Parquet file:

```
timestamp | symbol | bid_1_price | bid_1_size | ... | ask_15_price | ask_15_size | obi
```

---

## 5. Expected Performance

From strategy-playbook.md research:

| Metric | Value | Notes |
|--------|-------|-------|
| Win Rate | 62% | OBI > 0.75, 30s window (scalper mode) |
| Monthly Return | 3-5% | Compounded, scalper mode |
| MDD | -8% | With 0.5% per-trade stop |
| OBI Price Prediction | 70-80% | Short-term price discovery correlation |
| Fee Hurdle | 0.15% | Gross profit must exceed Upbit 0.05% × 2 + slippage |

**REST polling mode (Phase 1) expectations are lower:**

| Metric | Estimate | Why |
|--------|----------|-----|
| Win Rate | 50-55% | 5-min interval misses fast imbalance signals |
| Monthly Return | 1-2% | Fewer trades, wider stops needed |
| MDD | -10% | Slower reaction to reversals |

---

## 6. Implementation Checklist

### Phase 1 (This PR)

- [ ] Add `get_orderbook()` to `PyUpbitMarketDataClient`
- [ ] Add `get_orderbook()` to paper broker mock (return None or simulated)
- [ ] Wire `OrderbookProvider` into pipeline for OBI strategy
- [ ] Add spread filter and volume filter to `OBIStrategy`
- [ ] Add weighted OBI calculation option
- [ ] Add OBI config parameters to `StrategyConfig` dataclass
- [ ] Add sample OBI wallet config to `daemon.toml` (commented out)
- [ ] Tests: mock orderbook provider integration test
- [ ] Tests: spread/volume filter edge cases
- [ ] Paper trading validation (manual, post-merge)

### Phase 2 (Future)

- [ ] Orderbook snapshot collector (SQLite/Parquet)
- [ ] Historical OBI backtest engine
- [ ] WebSocket `OrderbookProvider`
- [ ] Fast-loop runtime for sub-second evaluation
- [ ] OBI delta (rate-of-change) signal
- [ ] Spoofing detection heuristic

---

## 7. Risk & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| REST rate limit exhaustion | OBI data unavailable | Graceful fallback to candle proxy (already implemented) |
| Orderbook spoofing | False OBI signals | Depth imbalance filter (top-3 vs top-15 divergence) |
| Low liquidity altcoins | Noisy OBI, wide spreads | Spread > 0.3% filter, minimum book size threshold |
| API downtime | No orderbook data | Existing candle proxy fallback, monitoring alert |
| Overfitting thresholds | Poor live performance | Walk-forward validation on collected real data |

---

## 8. Dependencies

- `pyupbit` >= 0.2.33 (already installed, has `get_orderbook()`)
- No new packages required for Phase 1
- Phase 2 requires: `websockets`, `msgpack` (for WebSocket MessagePack decoding)
