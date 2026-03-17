"""
==============================================================================
MOLTY ROYALE BOT - MAIN GAME LOOP
==============================================================================
Orchestrates: account setup → game finding → registration → game loop →
              post-game learning → next game
"""

import time
import logging
import sys
from typing import Optional, Dict

from core.api_client import APIClient, APIError
from core.analyzer import StateAnalyzer
from core.strategy import StrategyEngine
from learning.memory import GameMemory
from learning.ml_engine import LearningEngine
from config.settings import (
    API_KEY, BASE_URL, WALLET_ADDRESS,
    HP_CRITICAL, HP_LOW, EP_MIN_ATTACK, EP_REST_THRESHOLD,
    PREFERRED_GAME_TYPE, AUTO_CREATE_GAME, GAME_MAP_SIZE,
    WIN_PROBABILITY_ATTACK, WIN_PROBABILITY_AGGRESSIVE,
    LEARNING_ENABLED, DATA_DIR, MIN_GAMES_FOR_ML,
    REDIS_ENABLED, REDIS_HOST, REDIS_PORT, REDIS_DB,
    TURN_INTERVAL, POLL_INTERVAL_WAITING, POLL_INTERVAL_DEAD,
    LOG_LEVEL, LOG_TO_FILE, LOG_FILE
)

# =============================================================================
# LOGGING SETUP
# =============================================================================

class ColorFormatter(logging.Formatter):
    """
    Custom formatter: warna berdasarkan log level untuk terminal.
    File log tetap plain text tanpa ANSI codes.
    """
    # ANSI escape codes
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"

    # Level colors
    LEVEL_COLORS = {
        "DEBUG"   : "\033[0;36m",    # Cyan
        "INFO"    : "\033[0;37m",    # White
        "WARNING" : "\033[1;33m",    # Yellow bold
        "ERROR"   : "\033[0;31m",    # Red
        "CRITICAL": "\033[1;31m",    # Red bold
    }

    # Module name colors
    MODULE_COLORS = {
        "MoltyBot.GameLoop" : "\033[1;34m",   # Blue bold
        "MoltyBot.API"      : "\033[0;35m",   # Magenta
        "MoltyBot.Analyzer" : "\033[0;36m",   # Cyan
        "MoltyBot.Strategy" : "\033[0;33m",   # Orange
        "MoltyBot.Memory"   : "\033[2;37m",   # Dim white
        "MoltyBot.ML"       : "\033[0;32m",   # Green
    }

    def format(self, record):
        # Waktu — dim
        ts   = self.formatTime(record, "%H:%M:%S")
        ts_s = f"{self.DIM}{ts}{self.RESET}"

        # Level
        lvl      = record.levelname
        lvl_col  = self.LEVEL_COLORS.get(lvl, "")
        lvl_s    = f"{lvl_col}{lvl:<7}{self.RESET}"

        # Nama modul — potong prefix "MoltyBot."
        mod_full = record.name
        mod_col  = self.MODULE_COLORS.get(mod_full, self.DIM)
        mod_short = mod_full.replace("MoltyBot.", "")
        mod_s    = f"{mod_col}[{mod_short:<9}]{self.RESET}"

        # Pesan — biarkan sudah mengandung ANSI dari _log_turn
        msg = record.getMessage()

        return f"{ts_s}  {lvl_s}  {mod_s}  {msg}"


def setup_logging():
    import os
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # Terminal handler — dengan warna
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColorFormatter())

    # File handler — plain text tanpa ANSI
    plain_fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-7s  [%(name)s]  %(message)s",
        datefmt="%H:%M:%S"
    )
    file_h = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_h.setFormatter(plain_fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    if LOG_TO_FILE:
        root.addHandler(file_h)

    # ── Suppress library spam ─────────────────────────────────────
    for noisy in [
        "urllib3", "urllib3.connectionpool",
        "requests", "requests.packages.urllib3",
        "redis", "charset_normalizer",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("MoltyBot.GameLoop")


# =============================================================================
# REDIS SETUP (OPTIONAL)
# =============================================================================

def setup_redis():
    if not REDIS_ENABLED:
        return None
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                        decode_responses=True)
        r.ping()
        logger.info("Redis connected")
        return r
    except Exception as e:
        logger.warning(f"Redis unavailable: {e} - using JSON storage")
        return None


# =============================================================================
# GAME LOOP RUNNER
# =============================================================================

class GameLoop:
    """Runs the full lifecycle: find game → play → learn → repeat."""

    def __init__(self):
        setup_logging()
        logger.info("=" * 60)
        logger.info("  MOLTY ROYALE BOT - STARTING UP")
        logger.info("=" * 60)
        logger.info(f"  Server  : {BASE_URL}")
        logger.info(f"  Game    : {PREFERRED_GAME_TYPE.upper()} rooms")

        # Initialize all components
        redis = setup_redis()
        self.api    = APIClient(BASE_URL, API_KEY)
        self.memory = GameMemory(data_dir=DATA_DIR, redis_client=redis)
        self.learning = LearningEngine(self.memory, min_games_for_ml=MIN_GAMES_FOR_ML)
        self.analyzer = StateAnalyzer(
            hp_critical=HP_CRITICAL, hp_low=HP_LOW,
            ep_min_attack=EP_MIN_ATTACK, ep_rest_threshold=EP_REST_THRESHOLD
        )
        self.strategy = StrategyEngine(self.analyzer, self.memory, self.learning)

        # Game session state
        self.game_id:  Optional[str] = None
        self.agent_id: Optional[str] = None
        self.agent_name: str = "Unknown"

    # -------------------------------------------------------------------------
    # ACCOUNT SETUP
    # -------------------------------------------------------------------------

    def ensure_account(self):
        """
        Verify account exists, wallet is set, and detect if already in a game.

        Returns:
          "resume"  — already in running game, should resume playing
          "waiting" — already registered in a waiting/running game but dead/spectating
                      must wait for game to finish before joining next
          False     — not in any game, proceed to find_and_join_game
        """
        try:
            account = self.api.get_account()
            self.agent_name = account.get("name", "UnknownAgent")
            
            logger.info(f"Account: {self.agent_name} | "
                        f"Balance: {account.get('balance')} $Moltz | "
                        f"Wins: {account.get('totalWins')}/{account.get('totalGames')}")

            # ── Wallet Registration & Status Check ────────────────────
            wallet_on_server = account.get("walletAddress") or account.get("wallet")
            wallet_configured = (
                WALLET_ADDRESS
                and not WALLET_ADDRESS.startswith("0xYour")
                and len(WALLET_ADDRESS) == 42
            )

            if wallet_on_server:
                logger.info(
                    f"Wallet: {wallet_on_server[:10]}...{wallet_on_server[-6:]} ✓"
                )
            elif wallet_configured:
                # Wallet ada di config tapi belum di server — daftarkan sekarang
                try:
                    self.api.set_wallet(WALLET_ADDRESS)
                    logger.info(
                        f"Wallet didaftarkan: {WALLET_ADDRESS[:10]}...{WALLET_ADDRESS[-6:]} ✓"
                    )
                except Exception as e:
                    logger.warning(f"Gagal daftar wallet: {e}")
            else:
                logger.warning(
                    "⚠ WALLET BELUM TERDAFTAR — reward tidak akan diterima! "
                    "Isi WALLET_ADDRESS di config/settings.py"
                )

            # Check currentGames — API mungkin return field berbeda
            # Cek berbagai field yang mungkin ada
            current_games = (
                account.get("currentGames") or
                account.get("activeGames") or
                account.get("currentGame") or
                []
            )
            # Normalize: jika single dict, wrap ke list
            if isinstance(current_games, dict):
                current_games = [current_games]

            for game in current_games:
                game_id    = game.get("gameId") or game.get("id") or game.get("game_id", "")
                agent_id   = game.get("agentId") or game.get("agent_id", "")
                status     = game.get("gameStatus") or game.get("status", "")
                is_alive   = game.get("isAlive", game.get("alive", True))
                entry_type = game.get("entryType") or game.get("entry_type", PREFERRED_GAME_TYPE)

                if not game_id:
                    continue

                if status == "finished":
                    # Game sudah selesai, abaikan
                    continue

                if status in ("running", "waiting"):
                    if is_alive and entry_type == PREFERRED_GAME_TYPE:
                        logger.info(f"Resuming active game: {game_id} (alive={is_alive})")
                        self.game_id  = game_id
                        self.agent_id = agent_id
                        return "resume"
                    else:
                        # Sudah mati tapi game masih running — harus tunggu game selesai
                        logger.info(
                            f"Already in game {game_id[:8]}... (status={status}, alive={is_alive})"
                        )
                        self._active_game_id = game_id  # simpan untuk polling
                        return "waiting"

        except APIError as e:
            logger.error(f"Account error: {e}")
            logger.error("Check your API_KEY in config/settings.py")
            sys.exit(1)

        return False

    def wait_for_current_game_to_finish(self, game_id: str):
        """
        Bot sudah mati tapi game masih berjalan.
        Tunggu sampai game status = finished sebelum join game baru.
        Server tidak mengizinkan 1 akun di 2 game sekaligus.
        """
        logger.info(
            f"Waiting for current game {game_id[:8]}... to finish "
            f"(cannot join new game while in active game)"
        )
        poll = 0
        while True:
            try:
                game = self.api.get_game(game_id)
                status = game.get("status", "running")
                alive  = game.get("aliveCount", game.get("alive_count", "?"))

                if status == "finished":
                    logger.info(f"Game {game_id[:8]}... finished! Ready to join new game.")
                    return

                poll += 1
                # Log setiap 5 poll agar tidak spam
                if poll % 5 == 1:
                    logger.info(
                        f"Game still {status} | {alive} players alive | "
                        f"Checking again in {POLL_INTERVAL_DEAD}s..."
                    )
                time.sleep(POLL_INTERVAL_DEAD)

            except APIError as e:
                if e.code == "GAME_NOT_FOUND":
                    logger.info("Game not found (may have ended). Proceeding.")
                    return
                logger.warning(f"Error checking game status: {e} — retrying...")
                time.sleep(15)
            except Exception as e:
                logger.warning(f"Unexpected error waiting for game: {e}")
                time.sleep(15)

    # -------------------------------------------------------------------------
    # GAME FINDING & REGISTRATION
    # -------------------------------------------------------------------------

    def find_and_join_game(self) -> bool:
        """
        Find a waiting game and register.
        Uses aggressive polling (every ROOM_HUNT_INTERVAL seconds) for speed.
        Returns True on success.
        """
        from config.settings import ROOM_HUNT_INTERVAL
        import time as _time

        hunt_start = _time.time()
        attempt = 0

        logger.info("🎯 Room hunting started — aggressive mode (every %ds)", ROOM_HUNT_INTERVAL)

        while True:
            attempt += 1

            # ── PHASE 1: Fast scan for waiting games ──────────────────
            games = self.api.list_games_fast(status="waiting")
            matching = [g for g in games if g.get("entryType") == PREFERRED_GAME_TYPE]

            if matching:
                # ── PHASE 2: Instant registration (no delay!) ─────────
                game = matching[0]
                game_id = game["id"]
                elapsed = _time.time() - hunt_start
                logger.info(
                    f"⚡ Found room: {game.get('name')} (ID: {game_id}) "
                    f"after {elapsed:.1f}s / {attempt} attempts"
                )

                try:
                    agent = self.api.register_agent_fast(game_id, self.agent_name)
                    self.game_id  = game_id
                    self.agent_id = agent["id"]
                    join_time = _time.time() - hunt_start
                    logger.info(
                        f"✅ Registered as '{self.agent_name}' | "
                        f"Agent ID: {self.agent_id} | "
                        f"Join time: {join_time:.1f}s"
                    )
                    return True

                except APIError as e:
                    if e.code == "GAME_ALREADY_STARTED":
                        logger.warning("Room started before join — retrying instantly")
                        continue  # No sleep, try immediately
                    elif e.code == "ACCOUNT_ALREADY_IN_GAME":
                        errmsg  = str(e)
                        game_id = None
                        import re
                        m = re.search(
                            r"[Cc]urrent game[: ]+([0-9a-f-]{36})",
                            errmsg
                        )
                        if m:
                            game_id = m.group(1)
                            logger.warning(
                                f"Account still in game {game_id[:8]}... — waiting for it to end"
                            )
                            self.wait_for_current_game_to_finish(game_id)
                        else:
                            logger.warning(
                                "Account already in a game — checking account for active game..."
                            )
                            status = self.ensure_account()
                            if status == "waiting":
                                gid = getattr(self, "_active_game_id", None)
                                if gid:
                                    self.wait_for_current_game_to_finish(gid)
                                else:
                                    logger.warning("Unknown active game — waiting 60s")
                                    _time.sleep(60)
                        continue
                    elif e.code == "ONE_AGENT_PER_API_KEY":
                        logger.warning("Already have an agent in this game type, skipping")
                        return False
                    elif e.code == "MAX_AGENTS_REACHED":
                        logger.warning("Room full — retrying instantly")
                        continue  # No sleep, snipe next room
                    else:
                        logger.error(f"Registration failed: {e}")
                        continue  # Retry immediately

            elif AUTO_CREATE_GAME:
                logger.info("No waiting game found — creating one")
                try:
                    game = self.api.create_game(
                        host_name=f"{self.agent_name}_Room",
                        map_size=GAME_MAP_SIZE,
                        entry_type=PREFERRED_GAME_TYPE
                    )
                    logger.info(f"Created game: {game['id']}")
                    continue  # Immediately scan for the new game
                except APIError as e:
                    if e.code == "WAITING_GAME_EXISTS":
                        logger.warning("Waiting game already exists, re-scanning")
                        continue
                    logger.error(f"Create game failed: {e}")

            else:
                if attempt % 10 == 1:
                    logger.info(
                        f"🔍 Hunting for {PREFERRED_GAME_TYPE} rooms... "
                        f"(attempt #{attempt}, {_time.time() - hunt_start:.0f}s elapsed)"
                    )

            # ── Aggressive polling interval ───────────────────────────
            _time.sleep(ROOM_HUNT_INTERVAL)

    # -------------------------------------------------------------------------
    # GAME START WAIT
    # -------------------------------------------------------------------------

    def wait_for_game_start(self):
        """Poll until game status = 'running'."""
        logger.info("Waiting for game to start...")
        while True:
            try:
                game = self.api.get_game(self.game_id)
                status = game.get("status")
                agents = game.get("currentAgents", game.get("agentCount", "?"))

                if status == "running":
                    logger.info(f"GAME STARTED! ({agents} agents)")
                    return
                elif status == "finished":
                    logger.warning("Game finished before we could play")
                    self.game_id = None
                    self.agent_id = None
                    return

                logger.debug(f"Waiting... status={status}, agents={agents}")
                time.sleep(POLL_INTERVAL_WAITING)

            except APIError as e:
                logger.error(f"Error checking game status: {e}")
                time.sleep(10)

    # -------------------------------------------------------------------------
    # MAIN GAME TURN LOOP
    # -------------------------------------------------------------------------

    def run_game(self):
        """Execute the main game loop. Handles one full game."""
        logger.info(f"Starting game loop | Game: {self.game_id} | Agent: {self.agent_id}")

        # Initialize memory tracking for this game
        self.memory.start_game(self.game_id, self.agent_id, self.agent_name)
        self.strategy.reset_for_new_game()

        turn_count = 0
        last_action_time = 0
        death_cause = None

        # Combat tracking state
        prev_kills       = 0          # kills turn sebelumnya
        prev_hp          = 100.0      # HP kita turn sebelumnya
        prev_action_type = ""         # action turn sebelumnya
        prev_target      = {}         # target saat attack sebelumnya
        prev_target_type = ""         # "agent" or "monster"
        prev_my_stats    = {}         # snapshot my_stats saat attack (incl. heal)

        # Initial learning load
        if LEARNING_ENABLED and self.memory.games_played() >= MIN_GAMES_FOR_ML:
            self.learning.retrain(self.memory.get_recent_games(50))
            status = self.learning.get_learning_status()
            logger.info(f"Learning status: ML_active={status['ml_active']}, "
                        f"games={status['games_played']}")

        while True:
            loop_start = time.time()

            # ---- GET STATE ----
            try:
                state = self.api.get_state(self.game_id, self.agent_id)
            except APIError as e:
                if e.code in ("GAME_NOT_FOUND", "AGENT_NOT_FOUND"):
                    logger.info(
                        f"Game gone ({e.code}) — exiting loop after T{turn_count}"
                    )
                    self.memory.end_game(
                        is_winner=False, final_rank=99, final_hp=0,
                        moltz_earned=0, death_cause="game_not_found"
                    )
                    self.game_id  = None
                    self.agent_id = None
                    return False, 99
                logger.error(f"Failed to get state: {e}")
                time.sleep(10)
                continue

            # ---- CHECK GAME OVER ----
            game_status = state.get("gameStatus")
            self_data   = state.get("self", {})
            is_alive    = self_data.get("isAlive", True)

            if game_status == "finished" or not is_alive:
                result     = state.get("result") or {}
                is_winner  = result.get("isWinner", False)
                final_rank = result.get("finalRank") or result.get("rank")
                rewards    = result.get("rewards", 0)
                final_hp   = self_data.get("hp", 0)

                # ── Rank belum ada saat bot mati di game yang masih running ──
                # Server hanya isi finalRank ketika gameStatus="finished"
                # Poll sampai game selesai untuk dapat rank sesungguhnya
                if not final_rank and not is_alive and game_status != "finished":
                    logger.info(
                        "Bot eliminated T%d — waiting for game to end to get real rank...",
                        turn_count
                    )
                    final_rank = self._poll_for_final_rank(turn_count)
                    # Re-fetch result setelah game selesai
                    try:
                        s2 = self.api.get_state(self.game_id, self.agent_id)
                        r2 = s2.get("result") or {}
                        rewards    = r2.get("rewards", rewards)
                        is_winner  = r2.get("isWinner", is_winner)
                        final_rank = r2.get("finalRank") or final_rank
                    except Exception:
                        pass

                if not final_rank:
                    final_rank = 99

                self._log_game_end(is_winner, final_rank, rewards, turn_count)

                # End game and trigger learning
                game_record = self.memory.end_game(
                    is_winner=is_winner,
                    final_rank=final_rank,
                    final_hp=final_hp,
                    moltz_earned=rewards,
                    death_cause=death_cause
                )

                if LEARNING_ENABLED and game_record:
                    self.learning.post_game_update(game_record)

                self.game_id  = None
                self.agent_id = None
                return is_winner, final_rank

            # ---- PARSE INTEL ----
            intel = self.analyzer.parse(state)

            # ---- TURN TIMING: Wait until 60s since last action ----
            elapsed = time.time() - last_action_time
            wait_time = max(0, TURN_INTERVAL - elapsed - 1)  # 1s buffer
            if last_action_time > 0 and wait_time > 0:
                logger.debug(f"Waiting {wait_time:.1f}s for next turn...")
                time.sleep(wait_time)

            # ---- EXECUTE FREE ACTIONS FIRST ----
            main_action, reasoning, free_actions = self.strategy.decide(intel)

            for free_action in free_actions:
                try:
                    result = self.api.take_action(self.game_id, self.agent_id, free_action)
                    if result.get("success"):
                        atype = free_action.get("type")
                        logger.debug(f"Free action: {atype} ✓")
                        # Track item pickups
                        if atype == "pickup":
                            item_id = free_action.get("itemId")
                            for entry in intel["local_items"]:
                                if entry.get("item", {}).get("id") == item_id:
                                    self.memory.record_item_collected(entry["item"])
                except APIError as e:
                    logger.debug(f"Free action failed ({e.code}): {e}")

            # ---- EXECUTE MAIN TURN ACTION ----
            thought = {
                "reasoning": reasoning,
                "plannedAction": main_action.get("type"),
            }

            try:
                result = self.api.take_action(
                    self.game_id, self.agent_id, main_action, thought
                )
                last_action_time = time.time()
                turn_count += 1

                if result.get("success"):
                    # Definisikan atype di awal blok — dipakai di beberapa tempat di bawah
                    atype = main_action.get("type", "")
                    self._log_turn(turn_count, intel, main_action, reasoning)
                    self.memory.record_turn(turn_count, intel, main_action, result)

                    # Simpan region intel ke memory (DZ history lintas game)
                    self.memory.update_region_intel(
                        region_id=intel["region_id"],
                        region_name=intel["region_name"],
                        is_dz=intel["is_death_zone"],
                        terrain=intel.get("terrain", ""),
                    )

                    # ── Track item usage dengan konteks ───────────
                    if atype == "use_item":
                        item_id  = main_action.get("itemId", "")
                        # Cari tipe item dari inventory
                        inv = intel.get("inventory", []) or []
                        used_item = next(
                            (i for i in inv if i.get("id") == item_id), {}
                        )
                        type_id  = used_item.get("typeId", "unknown")
                        hp_now   = intel["hp"]
                        # Tentukan konteks: combat, critical, atau passive
                        has_enemies = bool(intel["local_agents"]
                                          or intel["local_monsters"])
                        if hp_now < 25:
                            ctx = "critical"
                        elif has_enemies:
                            ctx = "combat"
                        else:
                            ctx = "passive"
                        self.memory.record_item_used(
                            item_id=item_id, type_id=type_id,
                            hp_before=hp_now, hp_after=hp_now,
                            context=ctx
                        )

                    # Track death zone escape & death cause
                    if intel["is_death_zone"]:
                        death_cause = "death_zone"
                        if main_action.get("type") == "move":
                            self.memory.record_death_zone_escape()
                    elif intel["hp"] < 20 and intel["local_agents"]:
                        death_cause = "battle"  # kemungkinan mati karena battle

                    # ── Combat Outcome Tracking ────────────────────
                    current_kills = intel.get("kills", 0)
                    new_kills = current_kills - prev_kills

                    # Evaluasi hasil dari serangan SEBELUMNYA
                    # (setelah 1 turn kita tahu hasilnya: HP berubah? Kill baru?)
                    if prev_action_type == "attack" and prev_target:
                        damage_taken = max(0, prev_hp - intel["hp"])
                        # Menang jika: kill baru OR target agent sudah tidak ada
                        target_still_here = any(
                            a.get("id") == prev_target.get("id")
                            for a in (intel["local_agents"] + intel["local_monsters"])
                        )
                        we_won = (new_kills > 0) or \
                                 (not target_still_here and prev_target.get("id"))

                        # Hanya catat agent profile (bukan monster)
                        # karena enemy_profiles untuk tracking lawan manusia
                        # damage_dealt: ATK + weapon_bonus - enemy_DEF * 0.5
                        e_def      = prev_target.get("def", 5)
                        my_wpn_bon = prev_my_stats.get("weapon_bonus", 0)
                        my_atk_val = prev_my_stats.get("atk", intel.get("atk", 10))
                        dd = self.analyzer.calc_damage(my_atk_val, my_wpn_bon, e_def)

                        self.memory.record_combat(
                            target_id   = prev_target.get("id", "unknown"),
                            target_type = prev_target_type,
                            target_data = prev_target,
                            won         = we_won,
                            damage_dealt= dd,
                            damage_taken= int(damage_taken),
                            my_stats    = prev_my_stats,  # ← inventory heal data
                        )

                    # Update state untuk evaluasi turn berikutnya
                    prev_hp    = intel["hp"]
                    prev_kills = current_kills
                    prev_action_type = atype

                    if atype == "attack":
                        tid   = main_action.get("targetId")
                        ttype = main_action.get("targetType", "agent")
                        prev_target_type = ttype
                        # Snapshot data target SEKARANG (sebelum mereka bergerak)
                        all_targets = intel["local_agents"] + intel["local_monsters"]
                        found = next((t for t in all_targets
                                      if t.get("id") == tid), None)
                        if found:
                            prev_target = {
                                "id"           : found.get("id", ""),
                                "hp"           : found.get("hp", 50),
                                "atk"          : found.get("atk", 10),
                                "def"          : found.get("def", 5),
                                "name"         : found.get("name", "?"),
                                "equippedWeapon": found.get("equippedWeapon"),
                            }
                        else:
                            prev_target = {"id": tid}

                        # Snapshot kondisi KITA saat attack (incl. heal inventory)
                        # Ini yang akan di-log ke ML untuk training
                        prev_my_stats = self.strategy._my_combat_stats(intel)
                    else:
                        prev_target      = {}
                        prev_target_type = ""
                        prev_my_stats    = {}

                elif result.get("error", {}).get("code") == "ALREADY_ACTED":
                    # Already acted this window — wait for next
                    logger.debug("Already acted this turn, waiting...")
                    time.sleep(5)

            except APIError as e:
                if e.code == "INSUFFICIENT_EP":
                    logger.warning("Insufficient EP — forcing rest next decision")
                elif e.code == "GAME_NOT_RUNNING":
                    logger.info("Game is not running anymore, checking state...")
                    time.sleep(5)
                else:
                    logger.error(f"Action failed: {e}")

            # ---- HEARTBEAT STATUS ----
            if turn_count % 5 == 0:
                self._print_status("playing", intel, turn_count)

            # ---- PREVENT BURNING TURNS ----
            loop_elapsed = time.time() - loop_start
            min_loop_time = 2.0
            if loop_elapsed < min_loop_time:
                time.sleep(min_loop_time - loop_elapsed)

    # -------------------------------------------------------------------------
    # LOGGING HELPERS
    # -------------------------------------------------------------------------

    def _log_turn(self, turn: int, intel: Dict, action: Dict, reasoning: str):
        R  = "\033[0m"       # Reset
        B  = "\033[1m"       # Bold
        D  = "\033[2m"       # Dim

        # ── Hitung Day / Hour dari turn number ───────────────────────
        # 1 turn = 6 game hours, 4 turns = 1 day
        # Turn 1 = Day 1 06:00, Turn 2 = Day 1 12:00, dst
        HOURS = ["06:00", "12:00", "18:00", "00:00"]
        day   = ((turn - 1) // 4) + 1
        hour  = HOURS[(turn - 1) % 4]
        turns_left = max(0, 56 - turn)
        days_left  = turns_left // 4

        # Phase label berdasarkan Day
        if day >= 12:
            phase_s = f"\033[1;31m{B}ENDGAME{R}"   # Merah bold
        elif day >= 7:
            phase_s = f"\033[1;33mMIDGAME{R}"       # Kuning
        else:
            phase_s = f"\033[0;36mEARLY  {R}"        # Cyan

        # ── Action colors ────────────────────────────────────────────
        ACTION_COLORS = {
            "ATTACK"  : "\033[1;31m",   # Merah bold
            "MOVE"    : "\033[1;34m",   # Biru bold
            "EXPLORE" : "\033[1;32m",   # Hijau bold
            "REST"    : "\033[0;36m",   # Cyan
            "USE_ITEM": "\033[1;35m",   # Magenta bold
            "INTERACT": "\033[0;33m",   # Orange
            "PICKUP"  : "\033[0;32m",   # Hijau
            "EQUIP"   : "\033[0;35m",   # Magenta
        }
        atype     = action.get("type", "?").upper()
        act_color = ACTION_COLORS.get(atype, "\033[0;37m")

        # ── HP bar ───────────────────────────────────────────────────
        hp      = intel["hp"]
        hp_fill = int((hp / 100) * 10)
        hp_bar  = "█" * hp_fill + "░" * (10 - hp_fill)
        if hp < 25:
            hp_color = "\033[1;31m"; hp_icon = "💀"
        elif hp < 50:
            hp_color = "\033[0;31m"; hp_icon = "❤ "
        elif hp < 75:
            hp_color = "\033[1;33m"; hp_icon = "🟡"
        else:
            hp_color = "\033[0;32m"; hp_icon = "💚"

        # ── EP bar ───────────────────────────────────────────────────
        ep     = intel["ep"]
        ep_max = intel.get("max_ep", 10)
        ep_fill = int((ep / ep_max) * 8)
        ep_bar  = "▪" * ep_fill + "▫" * (8 - ep_fill)
        if ep <= 1:
            ep_color = "\033[0;31m"
        elif ep <= 3:
            ep_color = "\033[1;33m"
        else:
            ep_color = "\033[0;36m"

        # ── Kills ────────────────────────────────────────────────────
        kills = self.memory._current_game.get("kills", 0) if self.memory._current_game else 0
        if kills == 0:
            kills_s = f"{D}K:0 {R}"
        elif kills < 3:
            kills_s = f"\033[1;33mK:{kills} {R}"
        else:
            kills_s = f"\033[1;31m{B}K:{kills}🔥{R}"

        # ── Region — 1 warna tetap (cyan) untuk semua region ─────────
        reg_name = intel["region_name"][:14]
        reg_s    = f"\033[0;36m{reg_name:<14}{R}"   # Cyan, semua region

        # ── Senjata ──────────────────────────────────────────────────
        wpn_s = ""
        if intel.get("equipped_weapon"):
            wname = intel["equipped_weapon"].get("typeId", "?").lower()
            WPN_COLORS = {
                "katana": "\033[1;31m", "sniper": "\033[1;35m",
                "sword" : "\033[1;33m", "pistol": "\033[1;34m",
                "knife" : "\033[0;33m", "bow"   : "\033[0;32m",
            }
            wc    = WPN_COLORS.get(wname, "\033[2;37m")
            wpn_s = f" {D}[{R}{wc}{wname}{R}{D}]{R}"

        # ── Death zone & ancaman ─────────────────────────────────────
        dz_s   = f" \033[1;31m{B}⚡DZ!{R}" if intel["is_death_zone"] else ""
        pend_s = f" \033[0;33m⚠DZ{R}"     if intel["region_id"] in intel.get("pending_death_zones", []) else ""
        ene_s  = f" \033[1;31m👤×{len(intel['local_agents'])}{R}"  if intel["local_agents"]  else ""
        mob_s  = f" \033[0;33m🐺×{len(intel['local_monsters'])}{R}" if intel["local_monsters"] else ""

        # ── Weather ──────────────────────────────────────────────────
        WEATHER = {"clear": "", "rain": "🌧", "fog": "🌫", "storm": "⛈"}
        wx = WEATHER.get(intel.get("weather", "clear"), "")

        # ── Assemble ─────────────────────────────────────────────────
        sep = f"{D}│{R}"

        # Baris 1: Turn info + Day + Phase
        day_s  = f"\033[1;37mD{day:02d}{R}{D}/{hour}{R}"
        left_s = f"{D}({turns_left}t/{days_left}d left){R}"
        turn_s = f"{D}T{turn:03d}{R}"

        line = (
            f"{turn_s} {day_s} {left_s} {sep} "
            f"{phase_s} {sep} "
            f"{act_color}{B}{atype:<8}{R} {sep} "
            f"{hp_icon}{hp_color}{hp:>3.0f}[{hp_bar}]{R} {sep} "
            f"⚡{ep_color}{ep}/{ep_max}[{ep_bar}]{R} {sep} "
            f"{kills_s}{sep} "
            f"{reg_s}{wpn_s}{wx}"
            f"{dz_s}{pend_s}{ene_s}{mob_s}"
        )

        logger.info(line)

        if reasoning:
            logger.debug(f"  {D}└─ {reasoning[:110]}{R}")

    def _poll_for_final_rank(self, turn_count: int, timeout: int = 400) -> int:
        """
        Bot sudah mati tapi game masih jalan.
        Poll state sampai gameStatus='finished' dan server mengisi finalRank.

        Server hanya return finalRank ketika gameStatus='finished'.
        Saat bot mati (isAlive=False) tapi game masih 'running',
        result.finalRank = null → kita dapat default 99 yang salah.
        """
        import time as _time
        start = _time.time()
        poll_interval = 30

        logger.info(f"Waiting for game to end to get real rank "
                    f"(eliminated at T{turn_count})...")

        while _time.time() - start < timeout:
            try:
                state = self.api.get_state(self.game_id, self.agent_id)
                gs    = state.get("gameStatus")
                res   = state.get("result") or {}

                rank = res.get("finalRank") or res.get("rank")
                if rank:
                    logger.info(f"Real rank received: #{rank}")
                    return int(rank)

                if gs == "finished":
                    # Game selesai, coba sekali lagi
                    rank = res.get("finalRank") or res.get("rank")
                    if rank:
                        return int(rank)
                    logger.warning("Game finished but finalRank still null")
                    break

                # Hitung berapa pemain yang masih hidup (visible only)
                alive = [a for a in state.get("visibleAgents", [])
                         if a.get("isAlive", True)]
                elapsed = int(_time.time() - start)
                logger.info(
                    f"Game still running | {len(alive)} visible alive agents | "
                    f"elapsed {elapsed}s | next check in {poll_interval}s..."
                )
                _time.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Poll rank error: {e}")
                _time.sleep(15)

        logger.warning(f"Rank poll timeout after {timeout}s — rank unknown")
        return None

    def _log_game_end(self, is_winner: bool, rank: int, rewards: int, turns: int):
        R = "\033[0m"; B = "\033[1m"; D = "\033[2m"

        if is_winner:
            banner_col = "\033[1;33m"   # Gold
            banner     = "🏆  VICTORY!  🏆"
        elif rank <= 5:
            banner_col = "\033[1;36m"   # Cyan
            banner     = f"🥈  RANK #{rank} — GREAT GAME!"
        elif rank <= 10:
            banner_col = "\033[0;36m"
            banner     = f"🎖  RANK #{rank} — TOP 10!"
        else:
            banner_col = "\033[0;31m"   # Red
            banner     = f"💀  ELIMINATED — Rank #{rank}"

        stats = self.memory.get_stats()
        wr    = stats.get("win_rate", 0)
        rwr   = stats.get("recent_win_rate", 0)
        games = stats.get("games", 0)
        wins  = stats.get("wins", 0)

        wr_color  = "\033[1;32m" if wr >= 0.5 else "\033[1;33m" if wr >= 0.3 else "\033[0;31m"
        ml_status = "\033[1;32mAKTIF✓{R}" if self.learning.is_ml_active() else f"\033[1;33mBelum{R} {D}(butuh {max(0,5-games)} game lagi){R}"

        logger.info(f"\033[1m{'═'*58}{R}")
        logger.info(f"  {banner_col}{B}{banner}{R}")
        logger.info(f"  {'─'*54}")
        logger.info(f"  📊 Rank   : {banner_col}{B}#{rank}{R}  │  "
                    f"Rewards: \033[1;33m{rewards} $Moltz{R}  │  "
                    f"Turns: {D}{turns}{R}")
        logger.info(f"  ⚔️  Kills  : \033[1;31m{self.memory._current_game.get('kills',0)}{R}  │  "
                    f"HP sisa: {D}{self.memory._current_game.get('final_hp','?')}{R}")
        if games > 0:
            logger.info(f"  {'─'*54}")
            logger.info(f"  🤖 Career : {wr_color}{wr:.0%} win rate{R} "
                        f"{D}({wins}/{games} games){R}  │  "
                        f"Recent: {wr_color}{rwr:.0%}{R}")
            logger.info(f"  🧠 ML     : {ml_status}")
        logger.info(f"\033[1m{'═'*58}{R}")

    def _print_status(self, mode: str, intel: Dict = None, turn: int = 0):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        if mode == "idle":
            stats = self.memory.get_stats()
            wr = f"{stats['win_rate']:.0%}" if stats.get("games", 0) > 0 else "N/A"
            print(f"[{ts}] HEARTBEAT_OK │ Waiting for game │ "
                  f"Career: {stats.get('games',0)} games, WR={wr}")
        elif mode == "playing" and intel:
            dz   = " │ ⚡ DEATH ZONE!" if intel["is_death_zone"] else ""
            kills = self.memory._current_game.get("kills", 0) if \
                    self.memory._current_game else 0
            moltz = self.memory._current_game.get("moltz_earned", 0) if \
                    self.memory._current_game else 0
            print(f"[{ts}] PLAYING │ T{turn} │ "
                  f"HP:{intel['hp']:.0f}/100 EP:{intel['ep']}/10 │ "
                  f"K:{kills} │ {intel['region_name'][:15]}{dz}")

    # -------------------------------------------------------------------------
    # MAIN ENTRY POINT
    # -------------------------------------------------------------------------

    def run(self):
        """Main run loop — runs forever, game after game."""
        logger.info("Bot starting. Press Ctrl+C to stop.")

        # Print learning stats on startup
        stats = self.memory.get_stats()
        if stats["games"] > 0:
            logger.info(f"Career stats: {stats['win_rate']:.1%} win rate, "
                        f"{stats['total_kills']} total kills, "
                        f"{stats['total_moltz']} total $Moltz")

        # Verify account — cek apakah sudah dalam game
        account_status = self.ensure_account()

        # Jika sudah mati di game yang masih running — tunggu dulu
        if account_status == "waiting":
            gid = getattr(self, "_active_game_id", None)
            if gid:
                self.wait_for_current_game_to_finish(gid)
            account_status = False  # Siap join game baru

        game_count = 0
        while True:
            try:
                game_count += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"  GAME #{game_count} (Career: {self.memory.games_played()} played)")
                logger.info(f"{'='*60}")

                # Find and join game (skip if already in one)
                if account_status != "resume":
                    if not self.find_and_join_game():
                        time.sleep(30)
                        continue

                account_status = False  # Reset for next game

                # Wait for game to start (unless already running)
                if self.game_id:
                    self.wait_for_game_start()

                # Run the game
                if self.game_id and self.agent_id:
                    is_winner, rank = self.run_game()
                    time.sleep(5)  # Brief pause between games

            except KeyboardInterrupt:
                logger.info("\nBot stopped by user.")
                self.memory.save_all()
                stats = self.memory.get_stats()
                logger.info(f"Final career stats: {stats}")
                sys.exit(0)

            except Exception as e:
                logger.error(f"Unexpected error in game loop: {e}", exc_info=True)
                self.memory.save_all()
                logger.info("Recovering and retrying in 30 seconds...")
                time.sleep(30)


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    bot = GameLoop()
    bot.run()
