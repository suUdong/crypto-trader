# Lightsail 배포 계획 (crypto-trader 라이브 전환)

작성일: 2026-04-07
상태: Draft → 실행 대기
오너: Claude + 사용자 공동
관련 브랜치: `feature/db-introduction`

## 0. 배경

- 현재 crypto-trader는 로컬(WSL) 데몬으로만 돌아가며 paper 전용.
- 라이브 전환을 위해 안정적인 클라우드 호스트가 필요.
- 이전 세션 VPS 비교 문서 결론: **AWS Lightsail Seoul** (낮은 지연, 고정 IP, 스냅샷, 시간당 과금).
- Docker는 메모리 오버헤드가 크고 SQLite I/O에 이득이 없어 **native systemd** 로 간다.

## 1. 확정 사항

| 항목 | 결정 |
|---|---|
| 인스턴스 | Lightsail Seoul, 2 vCPU / 4 GB / 80 GB SSD (월 $20) |
| OS | Ubuntu 22.04 LTS |
| Runtime | Python 3.12 venv + systemd user/system unit (container 없음) |
| Python 설치 | `deadsnakes` PPA (`apt install python3.12 python3.12-venv`) |
| 소스 동기화 | 서버에서 `git pull` (초기), GitHub Actions SSH deploy (2단계) |
| Secrets | `/etc/crypto-trader/secrets.env` (root:crypto, 0640), systemd `EnvironmentFile` |
| 데이터 저장소 | 로컬 파일시스템 (`/var/lib/crypto-trader/artifacts/*.jsonl`, `*.db`) |
| 대시보드 노출 | 기존 Cloudflare Tunnel 재사용 |
| 모니터링 | 텔레그램 알림 (이미 통합) + `health.json` polling |
| 백업 | nightly `sqlite3 .backup` → Lightsail 스냅샷 + S3 |
| 페이퍼 → 라이브 | 2주 paper 안정 동작 검증 후 per-wallet 단계적 활성화 |

## 2. 파일시스템 레이아웃

```
/opt/crypto-trader/              # git clone 대상, owner = crypto:crypto
  .venv/                         # Python 3.12 venv
  src/crypto_trader/
  config/daemon.toml             # 배포 환경 config (git 버전 관리)
  scripts/lightsail_bootstrap.sh # 본 계획의 산출물
/var/lib/crypto-trader/          # owner = crypto:crypto, 0750
  artifacts/                     # JSONL, SQLite, checkpoints
  logs/                          # journalctl 외 추가 로그 필요 시
/etc/crypto-trader/
  secrets.env                    # 0640 root:crypto; API 키
  environment                    # 0644; TZ, PYTHONPATH, CT_CONFIG_PATH 등
/etc/systemd/system/
  crypto-trader.service          # 데몬 유닛
  crypto-trader-backup.service   # oneshot SQLite backup
  crypto-trader-backup.timer     # nightly 04:00 KST
```

`config/daemon.toml` 은 git에 있는 그대로 쓰되, 아래 경로는 빌드 타임 override:
- `paper_trade_journal_path = "/var/lib/crypto-trader/artifacts/paper-trades.jsonl"`
- `paper_trade_sqlite_path  = "/var/lib/crypto-trader/artifacts/paper-trades.db"`
- 나머지 `artifacts/*` 참조도 전부 `/var/lib/crypto-trader/artifacts/*` 로.

**결정 필요**: 별도 `config/lightsail.toml` 를 만들 것인가, 또는 기존 `daemon.toml` 에서 `CT_ARTIFACTS_ROOT` 같은 env 보간을 지원할 것인가? → **후자 권장** (환경별 config 난립 방지). `config.py` 에 `_expand_env()` 같은 얇은 레이어 추가가 필요하고, 이는 별도 작업으로 분리.

## 3. systemd 유닛 초안

### `/etc/systemd/system/crypto-trader.service`

```ini
[Unit]
Description=crypto-trader multi-wallet daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=crypto
Group=crypto
WorkingDirectory=/opt/crypto-trader
EnvironmentFile=/etc/crypto-trader/environment
EnvironmentFile=/etc/crypto-trader/secrets.env
ExecStart=/opt/crypto-trader/.venv/bin/python -m crypto_trader.cli run-daemon --config /opt/crypto-trader/config/daemon.toml
Restart=always
RestartSec=15
# 5회 연속 실패하면 일시 정지 (무한 재시작 방지)
StartLimitIntervalSec=300
StartLimitBurst=5

# 보안 하드닝
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/crypto-trader
# 메모리 상한 — 현재 운영 ~350 MB, 여유 있게 1.5 GB
MemoryMax=1536M
# CPU quota — 2 vCPU 중 75%
CPUQuota=150%

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/crypto-trader-backup.service`

```ini
[Unit]
Description=nightly SQLite + JSONL backup
After=crypto-trader.service

[Service]
Type=oneshot
User=crypto
Group=crypto
ExecStart=/opt/crypto-trader/scripts/backup.sh
```

### `/etc/systemd/system/crypto-trader-backup.timer`

```ini
[Unit]
Description=nightly crypto-trader backup

[Timer]
OnCalendar=*-*-* 19:00:00 UTC
Persistent=true
Unit=crypto-trader-backup.service

[Install]
WantedBy=timers.target
```
(04:00 KST = 19:00 UTC)

## 4. Bootstrap 스크립트 (`scripts/lightsail_bootstrap.sh`)

Idempotent, 재실행 안전. root 로 실행 (`sudo bash lightsail_bootstrap.sh`).

책임 범위:
1. `deadsnakes` PPA 추가 → `python3.12`, `python3.12-venv`, `sqlite3`, `git`, `tmux`, `jq` 설치
2. `crypto` 시스템 유저 생성 (`/opt/crypto-trader` 홈)
3. `/var/lib/crypto-trader/artifacts` + `/etc/crypto-trader` 디렉터리 + 퍼미션
4. `/opt/crypto-trader` git clone (이미 있으면 `git fetch && git reset --hard origin/master`? → **금지**, `git pull --ff-only`) 
5. venv 생성 + `pip install -e .` (setuptools 기반 설치)
6. `/etc/crypto-trader/environment` 초기화 (TZ=Asia/Seoul 등)
7. `/etc/crypto-trader/secrets.env` 가 없으면 템플릿 복사 + 수동 채우기 안내 후 **중단** (자동 키 쓰기 금지)
8. systemd 유닛 3종 설치 + `daemon-reload` + enable (start 는 사용자 확인 후)
9. 첫 실행 전 `scripts/migrate_paper_trades_to_sqlite.py` 를 `/var/lib/crypto-trader/artifacts/` 에 수행

스크립트 자체는 계획 승인 후 별도 PR 로 커밋.

## 5. 배포 절차 (Runbook)

### 5.1. 인스턴스 프로비저닝
1. Lightsail 콘솔 → Seoul → Ubuntu 22.04, 2 vCPU/4 GB, $20
2. Static IP 할당
3. SSH 키 등록 (`~/.ssh/lightsail_crypto.pub`)
4. 방화벽: 22 (SSH, 내 IP only), 나머지 전부 deny. 대시보드는 Cloudflare Tunnel 이 아웃바운드로만 연결하므로 incoming 공개 불필요.

### 5.2. 초기 동기화
```bash
scp scripts/lightsail_bootstrap.sh ubuntu@<ip>:/tmp/
ssh ubuntu@<ip> 'sudo bash /tmp/lightsail_bootstrap.sh'
```

### 5.3. Secrets 주입 (한 번만)
```bash
ssh ubuntu@<ip>
sudo -e /etc/crypto-trader/secrets.env
# UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
sudo chown root:crypto /etc/crypto-trader/secrets.env
sudo chmod 0640 /etc/crypto-trader/secrets.env
```

### 5.4. 첫 기동
```bash
sudo systemctl start crypto-trader
sudo systemctl status crypto-trader
journalctl -u crypto-trader -f
```
**검증 체크리스트** (최소 15분):
- [ ] `health.json` 생성 + 30초마다 갱신
- [ ] 최소 1 wallet 이 tick 정상 수행 (hold 신호라도)
- [ ] macro-intelligence 서버 연결 (또는 fallback 로그 `macro_bonus=0.0`)
- [ ] 메모리 < 500 MB
- [ ] paper-trades.db 파일 생성 (첫 거래 발생 후)

### 5.5. Cloudflare Tunnel 재연결
- 기존 tunnel config 재사용
- `cloudflared.service` 는 crypto-trader 와 독립 유닛
- 대시보드 `streamlit run dashboard/app.py` 는 별도 unit `crypto-dashboard.service` 로 (이 계획 범위 외)

### 5.6. 백업 검증
```bash
sudo systemctl start crypto-trader-backup.service
ls -la /var/lib/crypto-trader/backups/
```

## 6. 2주 Paper 검증 게이트

라이브 전환 전 요구:
- 일일 tick 성공률 > 99 %
- 메모리 leak 없음 (rss trend 평탄)
- 14일간 `failed_ticks` 누적 < 10
- SQLite 파일 사이즈 증가 선형 (dual-write 정상)
- 대시보드 edge_analysis 가 SQLite 에서 정상 렌더

모든 조건 만족 후, wallet 단위로 `paper_trading=false` 단계적 전환 (한 번에 1 월렛씩).

## 7. 롤백

- daemon 이 무한 재시작 루프에 빠지면 → `systemctl stop crypto-trader`
- 최근 스냅샷으로 Lightsail 인스턴스 롤백
- SQLite 손상 의심 → JSONL 로 재마이그레이션 (`migrate_paper_trades_to_sqlite.py`)
- Config 회귀 → `git checkout <prev> config/daemon.toml && systemctl restart crypto-trader`

## 8. 아웃스탠딩 결정 사항

- [ ] config path 환경 변수 보간 레이어 (`$ARTIFACTS_ROOT`) 를 추가할지, 별도 `lightsail.toml` 쓸지
- [ ] 라이브 전환 첫 월렛 선정 (현재 후보: `vpin_eth_wallet` — 유일한 검증 완료 래칫)
- [ ] 백업 S3 버킷 이름/리전
- [ ] GitHub Actions deploy workflow (2단계 작업)
- [ ] Cloudflare Access 적용 여부 (현재 우회 중)

## 9. 작업 분할 (후속 PR)

1. **P0** `config.py` 에 `$ARTIFACTS_ROOT` env 보간 + 테스트 *(코드 작업, ~150 LoC)*
2. **P0** `scripts/lightsail_bootstrap.sh` 작성 + 로컬 dry-run
3. **P0** `scripts/backup.sh` + systemd 유닛 파일 커밋
4. **P1** GitHub Actions `.github/workflows/deploy.yml`
5. **P1** 대시보드 unit 분리 + Cloudflare Access 구성
6. **P2** 멀티 리전 standby (YAGNI, 일단 보류)

---

본 계획은 `feature/db-introduction` 머지 후 별도 브랜치 `feature/lightsail-deploy` 에서 실행한다.
