"""
Alpha Watchlist → daemon.toml 반영 스크립트

artifacts/alpha-watchlist.json의 상위 종목을 읽어서
accumulation 지갑의 symbols를 업데이트합니다.
daemon 재시작 전에 수동으로 실행하거나, 자동화하세요.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import toml

WATCHLIST_PATH = Path("artifacts/alpha-watchlist.json")
DAEMON_CONFIG = Path("config/daemon.toml")
BACKUP_DIR = Path("artifacts/daemon-backups")

# Alpha 결과를 반영할 지갑 (accumulation 전략 — Lab Mode 전용)
ALPHA_WALLETS = ["accumulation_dood_wallet", "accumulation_tree_wallet"]


def load_watchlist() -> list[str]:
    if not WATCHLIST_PATH.exists():
        print(f"ERROR: {WATCHLIST_PATH} not found. Run the lab loop first.")
        sys.exit(1)
    with WATCHLIST_PATH.open() as f:
        data = json.load(f)
    symbols = [s["symbol"] for s in data.get("top_symbols", [])]
    updated_at = data.get("updated_at", "unknown")
    print(f"Watchlist loaded ({updated_at}): {symbols}")
    return symbols, data.get("cycle", 0)


def backup_daemon_config() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"daemon_{ts}.toml"
    shutil.copy2(DAEMON_CONFIG, backup_path)
    print(f"Backup saved: {backup_path}")
    return backup_path


def apply_alpha_to_daemon(symbols: list[str], cycle: int) -> None:
    if len(symbols) < 2:
        print("ERROR: Need at least 2 symbols to assign to 2 wallets.")
        sys.exit(1)

    # daemon.toml을 텍스트로 읽어서 지갑별 symbols 교체
    # toml 라이브러리로 파싱하면 주석이 날아가므로 텍스트 처리
    content = DAEMON_CONFIG.read_text()

    changes = []
    for i, wallet_name in enumerate(ALPHA_WALLETS):
        new_symbol = symbols[i] if i < len(symbols) else symbols[0]
        # 해당 지갑 섹션에서 symbols = [...] 줄 찾아서 교체
        # 패턴: name = "accumulation_xxx_wallet" 이후 symbols = [...]
        import re
        # 해당 wallet 블록 찾기
        pattern = rf'(name = "{wallet_name}".*?symbols = \[")[^"]*("\])'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            old_symbol = match.group(0)
            new_line = f'name = "{wallet_name}"'
            # symbols 줄만 교체
            symbol_pattern = r'(symbols = \[")[^"]*("\])'
            new_content_section = re.sub(
                symbol_pattern,
                lambda m: f'{m.group(1).split(chr(34))[0]}"{new_symbol}"{m.group(2).split(chr(34))[-1]}',
                old_symbol
            )
            content = content.replace(old_symbol, new_content_section)
            changes.append(f"  {wallet_name}: → {new_symbol}")
        else:
            # 더 간단한 방식: wallet 이름 이후 첫 번째 symbols 라인 교체
            lines = content.split('\n')
            in_wallet = False
            for j, line in enumerate(lines):
                if f'name = "{wallet_name}"' in line:
                    in_wallet = True
                if in_wallet and line.strip().startswith('symbols = ['):
                    old_line = line
                    lines[j] = f'symbols = ["{new_symbol}"]'
                    changes.append(f"  {wallet_name}: {old_line.strip()} → symbols = [\"{new_symbol}\"]")
                    in_wallet = False
                    break
            content = '\n'.join(lines)

    DAEMON_CONFIG.write_text(content)

    print(f"\n✅ daemon.toml updated (Cycle {cycle}):")
    for c in changes:
        print(c)
    print("\n⚠️  daemon 재시작이 필요합니다: scripts/restart_daemon.sh")


def main() -> None:
    print("=" * 60)
    print("  Alpha Watchlist → daemon.toml Applicator")
    print("=" * 60)

    symbols, cycle = load_watchlist()
    backup_daemon_config()
    apply_alpha_to_daemon(symbols, cycle)


if __name__ == "__main__":
    main()
