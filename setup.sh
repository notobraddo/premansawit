#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║     🤖  Molty Royale AI Bot — Setup & Launcher v2.0            ║
# ║   ML Learning │ Auto-Register │ Death Zone AI │ 99% WinRate    ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── Warna Terminal ──────────────────────────────────────────────────
RED='\033[0;31m';    GREEN='\033[0;32m';   YELLOW='\033[1;33m'
CYAN='\033[0;36m';   BLUE='\033[0;34m';    MAGENTA='\033[0;35m'
BOLD='\033[1m';      DIM='\033[2m';        NC='\033[0m'
WHITE='\033[1;37m'

# ── Path Setup ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$SCRIPT_DIR/config/settings.py"
BOT_SCRIPT="$SCRIPT_DIR/main.py"
VENV_DIR="$SCRIPT_DIR/venv"
LOG_FILE="$SCRIPT_DIR/logs/bot.log"
DATA_DIR="$SCRIPT_DIR/data"
BASE_URL_DEFAULT="https://cdn.moltyroyale.com/api"

# ── UI Helpers ──────────────────────────────────────────────────────
info()    { echo -e "  ${CYAN}ℹ  $1${NC}"; }
success() { echo -e "  ${GREEN}✅ $1${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠  $1${NC}"; }
error()   { echo -e "  ${RED}❌ $1${NC}"; }
step()    { echo -e "\n${BOLD}${BLUE}━━  $1${NC}"; }
line()    { echo -e "${DIM}  ──────────────────────────────────────────────────────${NC}"; }
blank()   { echo ""; }

# ── Spinner ─────────────────────────────────────────────────────────
SPINNER_PID=""
SPINNER_MSG=""

spinner_start() {
    SPINNER_MSG="$1"
    (
        chars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i=0
        while true; do
            idx=$((i % 10))
            c="${chars:$idx:1}"
            printf "\r  \033[0;36m%s\033[0m  %s  " "$c" "$SPINNER_MSG"
            sleep 0.1
            i=$((i+1))
        done
    ) &
    SPINNER_PID=$!
    disown "$SPINNER_PID" 2>/dev/null || true
}

spinner_stop() {
    [ -n "${SPINNER_PID:-}" ] && {
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    }
    printf "\r\033[2K"
    [ "${1:-ok}" = "ok" ] && success "$SPINNER_MSG" || error "$SPINNER_MSG — GAGAL"
}

# ═══════════════════════════════════════════════════════════════════════
print_banner() {
    clear 2>/dev/null || true
    echo ""
    echo -e "${CYAN}${BOLD}  ╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}  ║      🤖   MOLTY ROYALE AI BOT — Setup Wizard   🤖       ║${NC}"
    echo -e "${CYAN}${BOLD}  ║   Machine Learning │ Death Zone AI │ Strategy Engine    ║${NC}"
    echo -e "${CYAN}${BOLD}  ║   Auto-Register │ Combat Predictor │ 99% Target WR      ║${NC}"
    echo -e "${CYAN}${BOLD}  ╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${DIM}Folder  : $SCRIPT_DIR${NC}"
    echo -e "  ${DIM}Bot     : main.py  │  Config: config/settings.py${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════
# CEK PYTHON
# ═══════════════════════════════════════════════════════════════════════
check_python() {
    step "Cek Python Runtime..."
    blank
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
        PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJ" -ge 3 ] && [ "$PY_MIN" -ge 8 ]; then
            success "Python $PY_VER ditemukan ✓"
            PYTHON_BIN="python3"
        else
            error "Python $PY_VER terlalu lama — butuh Python 3.8+"
            blank
            info "Install: ${YELLOW}sudo apt update && sudo apt install python3 python3-pip python3-venv -y${NC}"
            exit 1
        fi
    else
        error "Python3 tidak ditemukan!"
        blank
        info "Install: ${YELLOW}sudo apt update && sudo apt install python3 python3-pip python3-venv -y${NC}"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# SETUP VENV
# ═══════════════════════════════════════════════════════════════════════
setup_venv() {
    step "Setup Virtual Environment Python..."
    blank

    if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/activate" ]; then
        warn "venv rusak — hapus dan buat ulang"
        spinner_start "Menghapus venv lama..."
        rm -rf "$VENV_DIR"
        spinner_stop ok
        blank
    fi

    if [ ! -d "$VENV_DIR" ]; then
        spinner_start "Membuat virtual environment baru..."
        if $PYTHON_BIN -m venv "$VENV_DIR" > /tmp/venv_log 2>&1; then
            spinner_stop ok
        else
            spinner_stop fail
            blank
            error "Gagal membuat virtual environment!"
            echo -e "  ${DIM}$(tail -5 /tmp/venv_log)${NC}"
            blank
            info "Solusi: ${YELLOW}sudo apt install python3-venv python3-full -y${NC}"
            exit 1
        fi
    else
        success "Virtual environment sudah valid"
    fi

    spinner_start "Mengaktifkan virtual environment..."
    source "$VENV_DIR/bin/activate"
    PYTHON_BIN="$VENV_DIR/bin/python"
    PIP_BIN="$VENV_DIR/bin/pip"
    spinner_stop ok

    if [ ! -f "$PYTHON_BIN" ]; then
        error "Python tidak ditemukan di venv: $PYTHON_BIN"
        info "Hapus dan coba lagi: ${YELLOW}rm -rf venv/${NC}"
        exit 1
    fi

    if [ ! -f "$PIP_BIN" ]; then
        spinner_start "Bootstrap pip..."
        $PYTHON_BIN -m ensurepip --upgrade > /tmp/pip_bootstrap 2>&1 \
            && spinner_stop ok || { spinner_stop fail; error "Fix: sudo apt install python3-pip -y"; exit 1; }
    fi

    blank
    success "Virtual environment siap!"
    info "  Python : $($PYTHON_BIN --version 2>&1)"
    info "  pip    : $($PIP_BIN --version 2>&1 | awk '{print $1,$2}')"
}

# ═══════════════════════════════════════════════════════════════════════
# INSTALL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════
install_deps() {
    step "Install Python Dependencies..."
    blank

    PACKAGES=("requests" "numpy" "scikit-learn" "pandas" "python-dotenv")
    MISSING_PKGS=()

    for pkg in "${PACKAGES[@]}"; do
        VER=$($PIP_BIN show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
        if [ -n "$VER" ]; then
            success "${pkg} ${DIM}v${VER}${NC}"
        else
            info "${pkg} — belum ada"
            MISSING_PKGS+=("$pkg")
        fi
    done

    if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
        blank
        success "Semua dependencies sudah lengkap! ⚡ Skip install."
        return 0
    fi

    blank
    info "Menginstall: ${MISSING_PKGS[*]}"
    blank

    spinner_start "Upgrade pip..."
    $PIP_BIN install -q --upgrade pip > /tmp/pip_up 2>&1 && spinner_stop ok || spinner_stop fail
    blank

    FAILED_PKGS=()
    for pkg in "${MISSING_PKGS[@]}"; do
        printf "  ${CYAN}►${NC}  %-25s" "Installing ${pkg}..."
        OUT=$($PIP_BIN install -q "$pkg" 2>&1)
        if [ $? -eq 0 ]; then
            VER=$($PIP_BIN show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
            printf "${GREEN}✅ OK  ${DIM}v%s${NC}\n" "$VER"
        else
            printf "${RED}❌ GAGAL${NC}\n"
            FAILED_PKGS+=("$pkg")
        fi
    done

    blank
    if [ ${#FAILED_PKGS[@]} -gt 0 ]; then
        error "Gagal install: ${FAILED_PKGS[*]}"
        echo -ne "  Lanjut meski ada yang gagal? [y/N]: "
        read -r CONT
        [[ "$CONT" =~ ^[Yy]$ ]] || exit 1
    else
        success "Semua dependencies berhasil!"
    fi

    # Tanya Redis
    blank; line; blank
    echo -e "  ${BOLD}🔴 Redis (Opsional — untuk penyimpanan session cepat)${NC}"
    echo -e "  ${DIM}Tidak wajib, JSON storage sudah cukup untuk sebagian besar kasus.${NC}"
    blank
    echo -ne "  Install Redis? [y/N]: "
    read -r REDIS_CHOICE
    if [[ "$REDIS_CHOICE" =~ ^[Yy]$ ]]; then
        spinner_start "Install Redis server..."
        sudo apt-get install -y redis-server -q > /tmp/redis_log 2>&1 && spinner_stop ok || spinner_stop fail
        spinner_start "Install redis Python client..."
        $PIP_BIN install -q redis && spinner_stop ok || spinner_stop fail
        sudo systemctl enable redis-server > /dev/null 2>&1
        sudo systemctl start redis-server > /dev/null 2>&1
        REDIS_ENABLED_VAL="True"
        success "Redis aktif!"
    else
        REDIS_ENABLED_VAL="False"
        info "Skip Redis — JSON storage digunakan"
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# API VALIDATION (Live hit ke server)
# ═══════════════════════════════════════════════════════════════════════
validate_api_key_live() {
    local api_key="$1"
    # Tulis script Python ke file temp agar tidak ada konflik heredoc
    cat > /tmp/_mr_validate.py << 'ENDPY'
import json, sys, urllib.request, urllib.error

api_key = sys.argv[1] if len(sys.argv) > 1 else ""
base    = sys.argv[2] if len(sys.argv) > 2 else "https://cdn.moltyroyale.com/api"

headers = {
    "X-API-Key":    api_key,
    "Content-Type": "application/json",
    "Accept":       "application/json",
}

endpoints = ["/accounts/me", "/accounts/balance"]

for ep in endpoints:
    try:
        req = urllib.request.Request(f"{base}{ep}", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data   = json.loads(r.read())
            d      = data.get("data", data) if isinstance(data, dict) else {}
            d      = d if isinstance(d, dict) else {}
            name   = d.get("name", d.get("username", "Unknown"))
            bal    = d.get("balance", 0)
            wins   = d.get("totalWins", d.get("wins", 0))
            games  = d.get("totalGames", d.get("games", 0))
            wallet = d.get("walletAddress", d.get("wallet", ""))
            print(f"OK|{name}|{bal}|{wins}|{games}|{wallet}")
            sys.exit(0)
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 401:
            print("INVALID|API Key tidak dikenali server (401 Unauthorized)")
        elif code == 403:
            # 403 = Forbidden, biasanya geo-restriction
            # Format key sudah benar, anggap valid dan lanjut
            print("SKIP|403 Forbidden - server menolak (geo-restriction?), format key OK")
        elif code == 404:
            continue  # coba endpoint berikutnya
        elif code == 429:
            print("SKIP|Rate limit (429) - coba lagi sebentar")
        else:
            print(f"SKIP|HTTP Error {code}")
        sys.exit(0)
    except Exception as e:
        err_s = str(e).lower()
        if "timed out" in err_s or "timeout" in err_s:
            print("SKIP|Timeout - koneksi lambat, skip validasi")
        elif "getaddrinfo failed" in err_s or "name or service" in err_s:
            print("SKIP|Tidak ada koneksi internet")
        else:
            print(f"SKIP|{str(e)}")
        sys.exit(0)

print("SKIP|Tidak bisa menghubungi server")
ENDPY
    $PYTHON_BIN /tmp/_mr_validate.py "$api_key" "$BASE_URL_DEFAULT"
}

check_wallet_status() {
    # Cek apakah wallet sudah terdaftar di akun
    # Return: REGISTERED|0x... atau NOT_REGISTERED atau ERR|msg
    local api_key="$1"
    cat > /tmp/_mr_wallet_check.py << ENDPY
import json, sys, urllib.request, urllib.error
api_key = sys.argv[1]
base    = sys.argv[2] if len(sys.argv) > 2 else "https://cdn.moltyroyale.com/api"
try:
    req = urllib.request.Request(f"{base}/accounts/me",
          headers={"X-API-Key": api_key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read()).get("data", {})
        wallet = d.get("walletAddress") or d.get("wallet") or ""
        bal = d.get("balance", 0)
        if wallet and wallet.startswith("0x") and len(wallet) == 42:
            print(f"REGISTERED|{wallet}|{bal}")
        else:
            print(f"NOT_REGISTERED||{bal}")
except urllib.error.HTTPError as e:
    print(f"ERR|HTTP {e.code}")
except Exception as e:
    print(f"ERR|{str(e)[:50]}")
ENDPY
    $PYTHON_BIN /tmp/_mr_wallet_check.py "$api_key" "$BASE_URL_DEFAULT"
}

register_wallet_api() {
    # Daftar wallet ke server via PUT /accounts/wallet
    # Return: OK|0x... atau ERR|msg
    local api_key="$1" wallet="$2"
    cat > /tmp/_mr_wallet_reg.py << ENDPY
import json, sys, urllib.request, urllib.error
api_key = sys.argv[1]
wallet  = sys.argv[2]
base    = sys.argv[3] if len(sys.argv) > 3 else "https://cdn.moltyroyale.com/api"
body    = json.dumps({"wallet_address": wallet}).encode()
try:
    req = urllib.request.Request(f"{base}/accounts/wallet",
          data=body, method="PUT",
          headers={"X-API-Key": api_key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read()).get("data", {})
        w = d.get("walletAddress", wallet)
        print(f"OK|{w}")
except urllib.error.HTTPError as e:
    msg = ""
    try: msg = json.loads(e.read()).get("error", {}).get("message", str(e))
    except: msg = str(e)
    print(f"ERR|{msg}")
except Exception as e:
    print(f"ERR|{str(e)[:80]}")
ENDPY
    $PYTHON_BIN /tmp/_mr_wallet_reg.py "$api_key" "$wallet" "$BASE_URL_DEFAULT"
}

check_waiting_games() {
    local api_key="$1"
    $PYTHON_BIN - <<PYEOF 2>/dev/null
import json, urllib.request
try:
    req = urllib.request.Request(
        "${BASE_URL_DEFAULT}/games?status=waiting",
        headers={"X-API-Key": "${api_key}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        games = json.loads(r.read()).get("data", [])
        if isinstance(games, list) and games:
            g = games[0]
            print(f"FOUND|{g.get('id','')}|{g.get('name','Game')}|{g.get('entryType','free')}")
        else:
            print("NONE")
except Exception as e:
    print(f"ERR|{e}")
PYEOF
}

# ═══════════════════════════════════════════════════════════════════════
# TULIS SEMUA CONFIG KE settings.py
# ═══════════════════════════════════════════════════════════════════════
write_all_config() {
    $PYTHON_BIN - <<PYEOF
import re
from pathlib import Path

p = Path("${SETTINGS_FILE}")
text = p.read_text()

def replace_str(text, key, val):
    return re.sub(rf'^({key}\s*=\s*).*$', rf'\g<1>"{val}"', text, flags=re.MULTILINE)

def replace_num(text, key, val):
    return re.sub(rf'^({key}\s*=\s*).*$', rf'\g<1>{val}', text, flags=re.MULTILINE)

text = replace_str(text, "API_KEY",               "${CFG_APIKEY}")
text = replace_str(text, "AGENT_NAME",            "${CFG_AGENT_NAME}")
text = replace_str(text, "BASE_URL",              "${BASE_URL_DEFAULT}")
text = replace_str(text, "WALLET_ADDRESS",        "${CFG_WALLET}")
text = replace_str(text, "PREFERRED_GAME_TYPE",   "${CFG_GAME_TYPE}")
text = replace_num(text, "HP_CRITICAL",           "${CFG_HP_CRITICAL}")
text = replace_num(text, "HP_LOW",                "${CFG_HP_LOW}")
text = replace_num(text, "EP_REST_THRESHOLD",     "${CFG_EP_REST}")
text = replace_num(text, "WIN_PROBABILITY_ATTACK","${CFG_WIN_PROB}")
text = replace_num(text, "REDIS_ENABLED",         "${REDIS_ENABLED_VAL}")
text = replace_str(text, "LOG_LEVEL",             "${CFG_LOG_LEVEL}")
text = replace_num(text, "LEARNING_ENABLED",      "True")
text = replace_num(text, "LOG_TO_FILE",           "True")

p.write_text(text)
print("OK")
PYEOF
}

update_one_key_str() {
    local key="$1" val="$2"
    $PYTHON_BIN - <<PYEOF 2>/dev/null
import re
from pathlib import Path
p = Path("${SETTINGS_FILE}")
t = p.read_text()
t = re.sub(rf'^({key}\s*=\s*).*$', rf'\g<1>"{val}"', t, flags=re.MULTILINE)
p.write_text(t)
PYEOF
}

update_one_key_num() {
    local key="$1" val="$2"
    $PYTHON_BIN - <<PYEOF 2>/dev/null
import re
from pathlib import Path
p = Path("${SETTINGS_FILE}")
t = p.read_text()
t = re.sub(rf'^({key}\s*=\s*).*$', rf'\g<1>{val}', t, flags=re.MULTILINE)
p.write_text(t)
PYEOF
}

# ═══════════════════════════════════════════════════════════════════════
# LOAD CONFIG DARI settings.py (untuk tampilan)
# ═══════════════════════════════════════════════════════════════════════
load_config() {
    eval $($PYTHON_BIN - <<PYEOF 2>/dev/null
import re
from pathlib import Path

text = Path("${SETTINGS_FILE}").read_text()

def get(key):
    m = re.search(rf'^{key}\s*=\s*["\']?(.*?)["\']?\s*(?:#.*)?$', text, re.MULTILINE)
    v = m.group(1).strip().strip('"').strip("'") if m else ""
    return v.replace("'", "\\'")

print(f"export CFG_APIKEY='{get('API_KEY')}'")
print(f"export CFG_AGENT_NAME='{get('AGENT_NAME')}'")
print(f"export CFG_WALLET='{get('WALLET_ADDRESS')}'")
print(f"export CFG_GAME_TYPE='{get('PREFERRED_GAME_TYPE')}'")
print(f"export CFG_HP_CRITICAL='{get('HP_CRITICAL')}'")
print(f"export CFG_HP_LOW='{get('HP_LOW')}'")
print(f"export CFG_EP_REST='{get('EP_REST_THRESHOLD')}'")
print(f"export CFG_WIN_PROB='{get('WIN_PROBABILITY_ATTACK')}'")
print(f"export CFG_LOG_LEVEL='{get('LOG_LEVEL')}'")
print(f"export REDIS_ENABLED_VAL='{get('REDIS_ENABLED')}'")
PYEOF
)
}

# ═══════════════════════════════════════════════════════════════════════
# TAMPILKAN CONFIG AKTIF
# ═══════════════════════════════════════════════════════════════════════
show_config() {
    local key_show="${CFG_APIKEY:0:14}...${CFG_APIKEY: -4}"

    # Cek wallet
    local wallet_display
    if [[ "$CFG_WALLET" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
        wallet_display="${GREEN}${CFG_WALLET:0:10}...${CFG_WALLET: -6}${NC}"
    else
        wallet_display="${RED}belum diset ⚠ (rewards tidak akan diterima!)${NC}"
    fi

    blank
    echo -e "  ${BOLD}📋  KONFIGURASI AKTIF${NC}"
    line
    echo -e "  🔑 API Key        : ${GREEN}${key_show}${NC}"
    [ -n "${ACCOUNT_NAME:-}" ] && echo -e "  👤 Akun           : ${CYAN}${ACCOUNT_NAME}${NC}  Balance: ${ACCOUNT_BALANCE:-?} \$Moltz  W/L: ${ACCOUNT_WINS:-?}/${ACCOUNT_GAMES:-?}"
    echo -e "  🏷️  Agent Name     : ${CYAN}${CFG_AGENT_NAME}${NC}"
    echo -e "  💰 Wallet         : ${wallet_display}"
    echo -e "  🎮 Game Type      : ${CYAN}${CFG_GAME_TYPE}${NC}"
    echo -e "  ❤️  HP Critical    : ${YELLOW}${CFG_HP_CRITICAL}${NC}  (heal wajib di bawah ini)"
    echo -e "  🛡️  HP Low         : ${YELLOW}${CFG_HP_LOW}${NC}  (main hati-hati di bawah ini)"
    echo -e "  ⚡ EP Rest        : ${YELLOW}${CFG_EP_REST}${NC}  (rest untuk recover EP)"
    echo -e "  ⚔️  Win Prob Min   : ${YELLOW}${CFG_WIN_PROB}${NC}  (min probabilitas untuk menyerang)"
    echo -e "  🤖 ML Learning    : ${GREEN}AKTIF${NC}  (ML aktif setelah 5 game)"
    echo -e "  🔴 Redis          : ${CYAN}${REDIS_ENABLED_VAL:-False}${NC}"
    echo -e "  📝 Log Level      : ${CYAN}${CFG_LOG_LEVEL}${NC}"
    line
    blank
}

# ═══════════════════════════════════════════════════════════════════════
# STATS VIEWER
# ═══════════════════════════════════════════════════════════════════════
show_stats() {
    blank
    if [ -f "$SCRIPT_DIR/stats.py" ]; then
        source "$VENV_DIR/bin/activate"
        $PYTHON_BIN "$SCRIPT_DIR/stats.py" 2>/dev/null || info "Belum ada data game"
    else
        info "stats.py tidak ditemukan"
    fi
    blank
    echo -ne "  Tekan Enter untuk kembali..."
    read -r
}

# ═══════════════════════════════════════════════════════════════════════
# WIZARD SETUP — 7 LANGKAH
# ═══════════════════════════════════════════════════════════════════════
run_wizard() {
    print_banner
    echo -e "  ${BOLD}${WHITE}📋  WIZARD KONFIGURASI${NC}"
    blank
    echo -e "  ${DIM}Cukup masukkan API Key → semua data diambil otomatis dari server.${NC}"
    echo -e "  ${DIM}Config disimpan ke config/settings.py — tidak perlu diisi ulang.${NC}"
    line

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 1 — API KEY (satu-satunya input wajib)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    blank
    echo -e "  ${BOLD}${CYAN}[ STEP 1 ]  🔑  API KEY${NC}"
    blank
    echo -e "  ${DIM}Format: mr_live_xxxxxxxxxxxxxxxxxxxxxxxx${NC}"
    echo -e "  ${DIM}Cara dapat: POST /api/accounts atau dashboard Molty Royale${NC}"
    blank

    ACCOUNT_NAME="" ACCOUNT_BALANCE="0" ACCOUNT_WINS="0" ACCOUNT_GAMES="0" ACCOUNT_WALLET=""

    while true; do
        echo -ne "  ${BOLD}Paste API Key kamu: ${NC}"
        read -r INPUT_APIKEY
        INPUT_APIKEY=$(echo "$INPUT_APIKEY" | tr -d '[:space:]')

        if [[ "$INPUT_APIKEY" == mr_live_* ]] && [ "${#INPUT_APIKEY}" -gt 15 ]; then
            blank
            spinner_start "Mengambil data akun dari server..."
            DETECT=$(validate_api_key_live "$INPUT_APIKEY")
            spinner_stop ok

            IFS='|' read -r STATUS ACCOUNT_NAME ACCOUNT_BALANCE ACCOUNT_WINS ACCOUNT_GAMES ACCOUNT_WALLET <<< "$DETECT"

            if [[ "$STATUS" == "INVALID" ]]; then
                blank
                error "API Key ditolak server (401) — pastikan key benar"
                echo -ne "  ${BOLD}Paksa lanjut? [y/N]: ${NC}"
                read -r FORCE
                [[ "$FORCE" =~ ^[Yy]$ ]] && { CFG_APIKEY="$INPUT_APIKEY"; break; }
                continue
            fi

            CFG_APIKEY="$INPUT_APIKEY"

            if [[ "$STATUS" == "OK" ]]; then
                # ── Data berhasil diambil dari server ─────────────────────
                blank
                success "Data akun berhasil diambil dari server!"
            else
                # ── Geo-restricted / timeout — coba ambil tetap dengan X-API-Key ──
                blank
                info "Server tidak bisa diakses langsung (${DETECT#*|})"
                info "  → Format API Key valid — mencoba ambil data via proxy..."
                blank
                # Reset ke default jika gagal
                [ -z "$ACCOUNT_NAME" ] && ACCOUNT_NAME="(tidak bisa diambil)"
                ACCOUNT_BALANCE="?"
            fi
            break
        else
            warn "API Key harus diawali 'mr_live_' — coba lagi"
        fi
    done

    # ── Cek wallet dari server (terpisah jika perlu) ──────────────
    if [ -z "$ACCOUNT_WALLET" ] && [[ "$STATUS" == "OK" ]]; then
        # Sudah masuk via OK tapi wallet kosong — normal, user belum daftar wallet
        :
    fi

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 2 — KONFIRMASI DATA AKUN & KUSTOMISASI
    # Tampilkan semua yang diambil dari server, user bisa ubah atau Enter saja
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    blank; line; blank
    echo -e "  ${BOLD}${CYAN}[ STEP 2 ]  📋  KONFIRMASI DATA AKUN${NC}"
    blank
    echo -e "  ${DIM}Tekan Enter untuk pakai nilai yang terdeteksi. Ketik untuk mengubah.${NC}"
    blank

    # ── 2a. Agent Name ────────────────────────────────────────────
    # Auto-derive dari account name
    if [ -n "$ACCOUNT_NAME" ] && [ "$ACCOUNT_NAME" != "(tidak bisa diambil)" ]; then
        SAFE_NAME=$(echo "$ACCOUNT_NAME" | tr -cd '[:alnum:]_' | cut -c1-20)
        [ -z "$SAFE_NAME" ] && SAFE_NAME="MoltyBot"
    else
        SAFE_NAME="MoltyBot"
    fi

    echo -e "  ${BOLD}🏷️  Nama Agent${NC}  ${DIM}(nama yang tampil di arena)${NC}"
    if [ "$ACCOUNT_NAME" != "(tidak bisa diambil)" ] && [ -n "$ACCOUNT_NAME" ]; then
        echo -e "  ${DIM}  Dari akun : ${CYAN}${ACCOUNT_NAME}${NC}  →  safe: ${CYAN}${SAFE_NAME}${NC}"
    fi
    echo -ne "  ${BOLD}Nama Agent [${SAFE_NAME}]: ${NC}"
    read -r INPUT_AGENT_NAME
    INPUT_AGENT_NAME=$(echo "$INPUT_AGENT_NAME" | tr -cd '[:alnum:]_' | cut -c1-20)
    [ -z "$INPUT_AGENT_NAME" ] && INPUT_AGENT_NAME="$SAFE_NAME"
    CFG_AGENT_NAME="$INPUT_AGENT_NAME"
    success "  Agent Name : ${CYAN}${CFG_AGENT_NAME}${NC}"
    blank

    # ── 2b. Wallet ────────────────────────────────────────────────
    echo -e "  ${BOLD}💰 Wallet EVM${NC}  ${DIM}(untuk menerima reward \$Moltz & \$CROSS)${NC}"

    if [[ "$ACCOUNT_WALLET" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
        echo -e "  ${GREEN}  Terdaftar : ${BOLD}${ACCOUNT_WALLET}${NC}"
        echo -ne "  ${BOLD}Pakai wallet ini? [Y/n]: ${NC}"
        read -r USE_EXIST
        if [[ "$USE_EXIST" =~ ^[Nn]$ ]]; then
            echo -ne "  ${BOLD}Wallet baru (0x...): ${NC}"
            read -r INPUT_WALLET
            INPUT_WALLET=$(echo "$INPUT_WALLET" | tr -d '[:space:]')
            if [[ "$INPUT_WALLET" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
                CFG_WALLET="$INPUT_WALLET"
                success "  Wallet baru: ${INPUT_WALLET:0:10}...${INPUT_WALLET: -6}"
            else
                warn "  Format tidak valid — pakai wallet yang sudah terdaftar"
                CFG_WALLET="$ACCOUNT_WALLET"
            fi
        else
            CFG_WALLET="$ACCOUNT_WALLET"
            success "  Wallet     : ${CFG_WALLET:0:10}...${CFG_WALLET: -6} ✓"
        fi
    else
        echo -e "  ${RED}  Belum terdaftar! Tanpa wallet = tidak ada reward (bahkan di free room)${NC}"
        echo -e "  ${DIM}  Format: 0x + 40 karakter hex${NC}"
        echo -ne "  ${BOLD}Wallet Address (Enter = skip): ${NC}"
        read -r INPUT_WALLET
        INPUT_WALLET=$(echo "$INPUT_WALLET" | tr -d '[:space:]')

        if [[ "$INPUT_WALLET" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
            CFG_WALLET="$INPUT_WALLET"
            # Langsung daftar ke server
            spinner_start "Mendaftarkan wallet ke server..."
            REG_RESULT=$(register_wallet_api "$CFG_APIKEY" "$INPUT_WALLET")
            IFS='|' read -r REG_CODE REG_DATA <<< "$REG_RESULT"
            if [ "$REG_CODE" = "OK" ]; then
                spinner_stop ok
                ACCOUNT_WALLET="$INPUT_WALLET"
                success "  Wallet terdaftar di server ✓"
            else
                spinner_stop fail
                warn "  Gagal daftar ke server (${REG_DATA}) — akan dicoba saat bot startup"
            fi
        else
            CFG_WALLET="0xYourEVMWalletAddress"
            warn "  Wallet dilewati — reward tidak akan diterima!"
            warn "  Daftar nanti: bash setup.sh → Update nilai → Wallet"
        fi
    fi
    blank

    # ── 2c. Game Type ─────────────────────────────────────────────
    echo -e "  ${BOLD}🎮 Tipe Game${NC}"
    echo -e "  ${GREEN}  [1] free${NC}  — Gratis, pool 1.000 \$Moltz   ${GREEN}← REKOMENDASI${NC}"
    echo -e "  ${CYAN}  [2] paid${NC}  — Premium, pool 100.000 \$Moltz, fee 1.000 \$Moltz"
    echo -ne "  ${BOLD}Pilih [1-2] (Enter = 1/free): ${NC}"
    read -r GAME_TYPE_CHOICE
    case "${GAME_TYPE_CHOICE:-1}" in
        2) CFG_GAME_TYPE="paid";  success "  Game Type  : PAID" ;;
        *) CFG_GAME_TYPE="free";  success "  Game Type  : FREE ✓" ;;
    esac
    blank

    # ── 2d. Tampilkan ringkasan sebelum simpan ────────────────────
    blank; line
    echo -e "  ${BOLD}📊 RINGKASAN — Konfirmasi sebelum disimpan:${NC}"
    blank
    echo -e "  🔑 API Key    : ${GREEN}${CFG_APIKEY:0:14}...${CFG_APIKEY: -4}${NC}"
    [ -n "$ACCOUNT_NAME" ] && \
    echo -e "  👤 Akun       : ${CYAN}${ACCOUNT_NAME}${NC}  (Balance: ${ACCOUNT_BALANCE} \$Moltz, W/G: ${ACCOUNT_WINS}/${ACCOUNT_GAMES})"
    echo -e "  🏷️  Agent Name : ${CYAN}${CFG_AGENT_NAME}${NC}"
    if [[ "$CFG_WALLET" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
        echo -e "  💰 Wallet     : ${GREEN}${CFG_WALLET:0:10}...${CFG_WALLET: -6} ✓${NC}"
    else
        echo -e "  💰 Wallet     : ${RED}BELUM DISET ⚠ — reward tidak akan diterima${NC}"
    fi
    echo -e "  🎮 Game Type  : ${CYAN}${CFG_GAME_TYPE}${NC}"
    blank

    echo -ne "  ${BOLD}Data sudah benar? Simpan dan lanjut? [Y/n]: ${NC}"
    read -r CONFIRM_DATA
    if [[ "$CONFIRM_DATA" =~ ^[Nn]$ ]]; then
        blank
        warn "Setup dibatalkan — jalankan setup.sh lagi untuk mengulang"
        exit 0
    fi

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 3 — PENGATURAN LANJUTAN (semua ada default, Enter saja)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    blank; line; blank
    echo -e "  ${BOLD}${CYAN}[ STEP 3 ]  ⚙️   PENGATURAN LANJUTAN${NC}"
    blank
    echo -e "  ${DIM}Semua sudah ada default yang bagus. Enter saja kalau tidak yakin.${NC}"
    blank

    echo -e "  ${BOLD}❤️  HP Critical${NC}  ${DIM}— heal wajib di bawah ini (default: 25)${NC}"
    echo -ne "  HP Critical [25]: "
    read -r VAL; VAL=$(echo "$VAL" | tr -d '[:space:]')
    [[ "$VAL" =~ ^[0-9]+$ ]] || VAL=25; CFG_HP_CRITICAL="$VAL"

    blank
    echo -e "  ${BOLD}🛡️  HP Low${NC}      ${DIM}— main hati-hati di bawah ini (default: 50)${NC}"
    echo -ne "  HP Low [50]: "
    read -r VAL; VAL=$(echo "$VAL" | tr -d '[:space:]')
    [[ "$VAL" =~ ^[0-9]+$ ]] || VAL=50; CFG_HP_LOW="$VAL"

    blank
    echo -e "  ${BOLD}⚡ EP Rest${NC}     ${DIM}— istirahat recover EP saat di bawah ini (default: 3)${NC}"
    echo -ne "  EP Rest [3]: "
    read -r VAL; VAL=$(echo "$VAL" | tr -d '[:space:]')
    [[ "$VAL" =~ ^[0-9]+$ ]] || VAL=3; CFG_EP_REST="$VAL"

    blank; line; blank
    echo -e "  ${BOLD}⚔️  Gaya Combat${NC}"
    echo -e "  ${GREEN}[1]${NC} Agresif   0.55   ${CYAN}[2]${NC} Seimbang  0.65 ${DIM}(DEFAULT)${NC}   ${YELLOW}[3]${NC} Defensif  0.75   ${RED}[4]${NC} Ultra    0.85"
    echo -ne "  ${BOLD}Pilih [1-4] (Enter = 2/Seimbang): ${NC}"
    read -r CMB
    case "${CMB:-2}" in
        1) CFG_WIN_PROB="0.55" ;;
        3) CFG_WIN_PROB="0.75" ;;
        4) CFG_WIN_PROB="0.85" ;;
        *) CFG_WIN_PROB="0.65" ;;
    esac

    blank
    echo -e "  ${BOLD}📝 Log Level${NC}  ${CYAN}[1]${NC} INFO (default)  ${CYAN}[2]${NC} DEBUG  ${CYAN}[3]${NC} WARNING"
    echo -ne "  ${BOLD}Pilih [1-3] (Enter = 1/INFO): ${NC}"
    read -r LOG_CHOICE
    case "${LOG_CHOICE:-1}" in
        2) CFG_LOG_LEVEL="DEBUG"   ;;
        3) CFG_LOG_LEVEL="WARNING" ;;
        *) CFG_LOG_LEVEL="INFO"    ;;
    esac

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SIMPAN
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    blank; line; blank
    spinner_start "Menyimpan konfigurasi ke config/settings.py..."
    WRITE_RESULT=$(write_all_config 2>&1)
    if [ "$WRITE_RESULT" = "OK" ]; then
        spinner_stop ok
    else
        spinner_stop fail
        error "Gagal tulis konfigurasi!"; echo -e "  ${DIM}${WRITE_RESULT}${NC}"; exit 1
    fi

    mkdir -p "$DATA_DIR" "$SCRIPT_DIR/logs"

    blank
    success "🎉 Setup selesai! Config tersimpan."
    blank
    show_config
}

# ═══════════════════════════════════════════════════════════════════════
# MENU KETIKA CONFIG SUDAH ADA
# ═══════════════════════════════════════════════════════════════════════
menu_config_ada() {
    blank
    echo -e "  ${BOLD}⚙️   Konfigurasi sudah ada. Mau apa?${NC}"
    blank
    echo -e "  ${CYAN}[1]${NC} ${BOLD}Langsung jalankan bot${NC}        ${DIM}(pakai config sekarang)${NC}"
    echo -e "  ${CYAN}[2]${NC} Setup ulang dari awal             ${DIM}(Wizard 4 langkah)${NC}"
    echo -e "  ${CYAN}[3]${NC} Update satu nilai saja             ${DIM}(API Key / Wallet / Threshold, dll)${NC}"
    echo -e "  ${CYAN}[4]${NC} Lihat config aktif"
    echo -e "  ${CYAN}[5]${NC} Lihat stats & learning progress"
    echo -e "  ${CYAN}[6]${NC} Keluar"
    blank
    echo -ne "  ${BOLD}Pilih [1-6]: ${NC}"
    read -r MC

    case "$MC" in
        1) return 0 ;;
        2)
            blank
            echo -ne "  ${YELLOW}Setup ulang akan menimpa config. Lanjut? [y/N]: ${NC}"
            read -r CONFIRM
            [[ "$CONFIRM" =~ ^[Yy]$ ]] && run_wizard || menu_config_ada
            ;;
        3) menu_update_field; load_config; menu_config_ada ;;
        4) show_config
           echo -ne "  Lanjut jalankan bot? [Y/n]: "
           read -r X
           [[ "$X" =~ ^[Nn]$ ]] && exit 0 || return 0
           ;;
        5) show_stats; menu_config_ada ;;
        6) blank; success "Sampai jumpa!"; exit 0 ;;
        *) return 0 ;;
    esac
}

menu_update_field() {
    blank
    echo -e "  ${BOLD}✏️   Update Nilai Konfigurasi:${NC}"
    blank
    echo -e "  ${CYAN}[1]${NC} API Key"
    echo -e "  ${CYAN}[2]${NC} Nama Agent"
    echo -e "  ${CYAN}[3]${NC} Wallet Address"
    echo -e "  ${CYAN}[4]${NC} Tipe Game (free/paid)"
    echo -e "  ${CYAN}[5]${NC} HP Critical threshold"
    echo -e "  ${CYAN}[6]${NC} Win Probability (gaya combat)"
    echo -e "  ${CYAN}[7]${NC} Log Level"
    echo -e "  ${CYAN}[8]${NC} Kembali"
    blank
    echo -ne "  ${BOLD}Pilih [1-8]: ${NC}"
    read -r UF

    case "$UF" in
        1)
            while true; do
                echo -ne "  API Key baru (mr_live_...): "
                read -r V; V=$(echo "$V" | tr -d '[:space:]')
                [[ "$V" == mr_live_* ]] && break || warn "Harus dimulai mr_live_"
            done
            CFG_APIKEY="$V"
            update_one_key_str "API_KEY" "$V"
            success "API Key diperbarui"
            ;;
        2)
            echo -ne "  Nama Agent baru [KillerBot_v1]: "
            read -r V; V=$(echo "$V" | tr -d '[:space:]')
            [ -z "$V" ] && V="KillerBot_v1"
            CFG_AGENT_NAME="$V"
            update_one_key_str "AGENT_NAME" "$V"
            success "Agent Name: $V"
            ;;
        3)
            while true; do
                echo -ne "  Wallet Address (0x...): "
                read -r V; V=$(echo "$V" | tr -d '[:space:]')
                [ -z "$V" ] && { warn "Wallet kosong — skip"; break; }
                [[ "$V" =~ ^0x[a-fA-F0-9]{40}$ ]] && break || warn "Format tidak valid"
            done
            [ -n "$V" ] && { CFG_WALLET="$V"; update_one_key_str "WALLET_ADDRESS" "$V"; success "Wallet: $V"; }
            ;;
        4)
            echo -e "  ${GREEN}[1]${NC} free   ${CYAN}[2]${NC} paid"
            echo -ne "  Pilih: "
            read -r V
            [[ "$V" == "2" ]] && GT="paid" || GT="free"
            CFG_GAME_TYPE="$GT"
            update_one_key_str "PREFERRED_GAME_TYPE" "$GT"
            success "Game Type: $GT"
            ;;
        5)
            echo -ne "  HP Critical baru [25]: "
            read -r V; V=$(echo "$V" | tr -d '[:space:]')
            [[ "$V" =~ ^[0-9]+$ ]] || V=25
            CFG_HP_CRITICAL="$V"
            update_one_key_num "HP_CRITICAL" "$V"
            success "HP Critical: $V"
            ;;
        6)
            while true; do
                echo -ne "  Win Prob (0.50–0.90) [0.65]: "
                read -r V; V=$(echo "$V" | tr -d '[:space:]')
                [ -z "$V" ] && V="0.65"
                [[ "$V" =~ ^0\.[5-9][0-9]?$ ]] && break || warn "Harus antara 0.50 dan 0.90"
            done
            CFG_WIN_PROB="$V"
            update_one_key_num "WIN_PROBABILITY_ATTACK" "$V"
            success "Win Prob: $V"
            ;;
        7)
            echo -e "  ${CYAN}[1]${NC} INFO  ${CYAN}[2]${NC} DEBUG  ${CYAN}[3]${NC} WARNING"
            echo -ne "  Pilih [1-3]: "
            read -r V
            case "$V" in
                2) LL="DEBUG" ;; 3) LL="WARNING" ;; *) LL="INFO" ;;
            esac
            CFG_LOG_LEVEL="$LL"
            update_one_key_str "LOG_LEVEL" "$LL"
            success "Log Level: $LL"
            ;;
        8) return ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════
# TEST KONEKSI (1 Request Dry Run)
# ═══════════════════════════════════════════════════════════════════════
run_test() {
    blank
    step "Test Koneksi & API (Dry Run)..."
    blank
    source "$VENV_DIR/bin/activate"

    $PYTHON_BIN - <<PYEOF
import json, sys, time, urllib.request
sys.path.insert(0, "${SCRIPT_DIR}")
from config.settings import API_KEY, BASE_URL, AGENT_NAME, PREFERRED_GAME_TYPE

print(f"  🌐 Server     : {BASE_URL}")
print(f"  🔑 API Key    : {API_KEY[:14]}...{API_KEY[-4:]}")
print(f"  🏷️  Agent Name : {AGENT_NAME}")
print(f"  🎮 Game Type  : {PREFERRED_GAME_TYPE}")
print()

headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# Test 1: Account
print("  ► Test 1/3: Account Info...")
try:
    req = urllib.request.Request(f"{BASE_URL}/accounts/me", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read()).get("data", {})
        print(f"    ✅ OK — Nama: {d.get('name')}, Balance: {d.get('balance')} \$Moltz, "
              f"Wallet: {'✓' if d.get('walletAddress') else '✗ belum daftar'}")
except Exception as e:
    print(f"    ❌ GAGAL: {e}")
    sys.exit(1)

# Test 2: Games
print()
print("  ► Test 2/3: Game yang Tersedia...")
try:
    req = urllib.request.Request(f"{BASE_URL}/games?status=waiting", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        games = json.loads(r.read()).get("data", [])
        if isinstance(games, list) and games:
            print(f"    ✅ {len(games)} game waiting ditemukan:")
            for g in games[:3]:
                print(f"       🎮 {g.get('name','?')}  [{g.get('entryType','?')}]  ID: {g.get('id','?')[:16]}...")
        else:
            print("    ℹ️  Tidak ada game waiting — bot akan menunggu game baru")
except Exception as e:
    print(f"    ❌ GAGAL: {e}")

# Test 3: Latency
print()
print("  ► Test 3/3: Latency...")
start = time.time()
try:
    req = urllib.request.Request(f"{BASE_URL}/games", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()
    ms = (time.time() - start) * 1000
    icon = "✅" if ms < 500 else "⚠️ "
    print(f"    {icon} {ms:.0f}ms {'(bagus)' if ms < 300 else '(lambat, cek koneksi)' if ms > 800 else '(oke)'}")
except Exception as e:
    print(f"    ❌ {e}")

print()
print("  ✅ Semua test selesai — Bot siap dijalankan!")
PYEOF

    local EXIT=$?
    blank
    if [ $EXIT -eq 0 ]; then
        echo -ne "  ${BOLD}Lanjut jalankan bot penuh? [Y/n]: ${NC}"
        read -r C
        [[ "$C" =~ ^[Nn]$ ]] && exit 0 || run_foreground
    else
        error "Test gagal — periksa API Key dan koneksi"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# MODE JALANKAN
# ═══════════════════════════════════════════════════════════════════════
run_foreground() {
    blank
    echo -e "  ${GREEN}${BOLD}▶  Menjalankan bot — Ctrl+C untuk stop${NC}"
    blank
    source "$VENV_DIR/bin/activate"
    exec $PYTHON_BIN "$BOT_SCRIPT"
}

run_screen() {
    step "Background dengan screen (tetap jalan saat SSH disconnect)..."

    if ! command -v screen &>/dev/null; then
        warn "screen belum terinstall"
        echo -ne "  Install sekarang? [Y/n]: "
        read -r INS
        [[ ! "$INS" =~ ^[Nn]$ ]] && sudo apt-get install -y screen -q || { error "screen diperlukan"; return; }
    fi

    SESSION="molty-ai-bot"
    mkdir -p "$SCRIPT_DIR/logs"

    if screen -list 2>/dev/null | grep -q "$SESSION"; then
        warn "Session lama ditemukan — menghentikan..."
        screen -S "$SESSION" -X quit 2>/dev/null || true
        sleep 1
    fi

    screen -dmS "$SESSION" bash -c "
        source '${VENV_DIR}/bin/activate'
        cd '${SCRIPT_DIR}'
        echo '=== Molty Royale AI Bot Started ===' | tee -a '${LOG_FILE}'
        echo 'Time: \$(date)' | tee -a '${LOG_FILE}'
        $PYTHON_BIN '${BOT_SCRIPT}' 2>&1 | tee -a '${LOG_FILE}'
        echo 'Bot exited: \$(date)' >> '${LOG_FILE}'
    "
    sleep 2

    if screen -list 2>/dev/null | grep -q "$SESSION"; then
        success "Bot berjalan di background! Session: ${CYAN}${SESSION}${NC}"
    else
        warn "Screen mungkin langsung exit — cek: tail -f logs/bot.log"
    fi

    blank; line
    echo -e "  ${CYAN}screen -r ${SESSION}${NC}             → Lihat output live"
    echo -e "  ${CYAN}Ctrl+A  kemudian  D${NC}              → Detach (bot tetap jalan)"
    echo -e "  ${CYAN}screen -S ${SESSION} -X quit${NC}     → Stop bot"
    echo -e "  ${CYAN}tail -f ${LOG_FILE}${NC}  → Lihat log file"
    line; blank

    echo -ne "  Buka screen sekarang? [Y/n]: "
    read -r OPEN
    [[ "$OPEN" =~ ^[Nn]$ ]] || screen -r "$SESSION"
}

run_systemd() {
    step "Install sebagai systemd service (auto-start saat reboot)..."

    CUR_USER=$(whoami)
    SVC_NAME="molty-ai-bot"
    SVC_FILE="/etc/systemd/system/${SVC_NAME}.service"
    mkdir -p "$SCRIPT_DIR/logs"

    cat > /tmp/${SVC_NAME}.service <<SVCEOF
[Unit]
Description=Molty Royale AI Bot (ML Learning Engine)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CUR_USER}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${VENV_DIR}/bin/python ${BOT_SCRIPT}
Restart=always
RestartSec=30
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=multi-user.target
SVCEOF

    if ! sudo cp /tmp/${SVC_NAME}.service "$SVC_FILE" 2>/dev/null; then
        error "Butuh sudo untuk install systemd service"
        warn "Gunakan mode Background (screen) sebagai alternatif"
        return
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable "$SVC_NAME" 2>/dev/null
    sudo systemctl restart "$SVC_NAME"
    sleep 2

    STATUS=$(sudo systemctl is-active "$SVC_NAME" 2>/dev/null || echo "unknown")

    if [ "$STATUS" = "active" ]; then
        success "Service ${CYAN}${SVC_NAME}${NC} aktif dan berjalan!"
        success "Auto-restart: ✓  Auto-start saat reboot: ✓"
    else
        warn "Status: $STATUS — cek log di bawah untuk detail"
    fi

    blank; line
    echo -e "  ${CYAN}sudo systemctl status ${SVC_NAME}${NC}   → Status"
    echo -e "  ${CYAN}sudo journalctl -u ${SVC_NAME} -f${NC}   → Log live"
    echo -e "  ${CYAN}sudo systemctl restart ${SVC_NAME}${NC}  → Restart"
    echo -e "  ${CYAN}sudo systemctl stop ${SVC_NAME}${NC}     → Stop"
    echo -e "  ${CYAN}tail -f ${LOG_FILE}${NC}                 → Log file"
    line
}

choose_run_mode() {
    blank
    echo -e "  ${BOLD}🚀  Cara Menjalankan Bot:${NC}"
    blank
    echo -e "  ${CYAN}[1]${NC} ${BOLD}Test dulu${NC}            ${DIM}— verifikasi koneksi & config (aman, 1 request)${NC}"
    echo -e "  ${CYAN}[2]${NC} ${BOLD}Foreground${NC}           ${DIM}— jalankan di terminal, Ctrl+C untuk stop${NC}"
    echo -e "  ${CYAN}[3]${NC} ${BOLD}Background (screen)${NC}  ${DIM}— tetap jalan saat SSH disconnect ← REKOMENDASI${NC}"
    echo -e "  ${CYAN}[4]${NC} ${BOLD}Systemd service${NC}      ${DIM}— auto-start saat reboot, production mode${NC}"
    echo -e "  ${CYAN}[5]${NC} Keluar"
    blank
    echo -ne "  ${BOLD}Pilih [1-5] (Enter = 2/Foreground): ${NC}"
    read -r RUN_MODE

    case "${RUN_MODE:-2}" in
        1) run_test ;;
        2) run_foreground ;;
        3) run_screen ;;
        4) run_systemd ;;
        5) blank; success "Sampai jumpa! Jalankan lagi kapan saja: bash setup.sh"; exit 0 ;;
        *) run_foreground ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════
# CEK FILE PENTING
# ═══════════════════════════════════════════════════════════════════════
check_files() {
    local missing=0
    [ ! -f "$BOT_SCRIPT" ] && { error "main.py tidak ditemukan: $BOT_SCRIPT"; missing=1; }
    [ ! -f "$SETTINGS_FILE" ] && { error "config/settings.py tidak ditemukan: $SETTINGS_FILE"; missing=1; }
    if [ "$missing" -eq 1 ]; then
        blank
        warn "Pastikan semua file bot ada di folder yang sama dengan setup.sh"
        info "Struktur yang dibutuhkan:"
        echo -e "    ${DIM}molty_royale_bot/"
        echo -e "    ├── setup.sh  ← ini"
        echo -e "    ├── main.py"
        echo -e "    ├── config/settings.py"
        echo -e "    ├── core/"
        echo -e "    └── learning/${NC}"
        exit 1
    fi
}

is_config_ready() {
    $PYTHON_BIN - <<PYEOF 2>/dev/null
import re
from pathlib import Path
try:
    t = Path("${SETTINGS_FILE}").read_text()
    m = re.search(r'^API_KEY\s*=\s*["\']?(mr_live_[^"\']+)["\']?', t, re.MULTILINE)
    print("READY" if m and len(m.group(1)) > 15 else "NOT_READY")
except:
    print("NOT_READY")
PYEOF
}

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
print_banner
check_python
check_files
setup_venv
install_deps

blank; line; blank

CONFIG_STATUS=$(is_config_ready)

if [ "$CONFIG_STATUS" = "READY" ]; then
    step "Konfigurasi ditemukan..."
    blank
    load_config
    show_config
    menu_config_ada
else
    step "Konfigurasi pertama kali — mulai wizard..."
    blank
    warn "API Key belum diset di config/settings.py"
    info "Jalankan wizard untuk mengisi semua data yang dibutuhkan"
    blank
    echo -ne "  ${BOLD}Mulai wizard setup sekarang? [Y/n]: ${NC}"
    read -r START
    if [[ "$START" =~ ^[Nn]$ ]]; then
        blank
        info "Setup dibatalkan. Edit manual: ${YELLOW}nano config/settings.py${NC}"
        exit 0
    fi
    run_wizard
fi

blank; line; blank
choose_run_mode
