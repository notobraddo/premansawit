"""
==============================================================================
MOLTY ROYALE BOT - MEMORY & PERSISTENCE LAYER
==============================================================================
Stores game history, strategy performance data, enemy profiles,
and learning state. Uses JSON files (Redis optional).
"""

import json
import os
import time
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("MoltyBot.Memory")


class GameMemory:
    """
    Persistent memory store for the bot's learning system.
    Stores game history, combat outcomes, strategy effectiveness,
    enemy profiles, and regional intelligence.
    """

    SCHEMA_VERSION = "2.0"

    def __init__(self, data_dir: str = "data", redis_client=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.redis = redis_client

        # File paths
        self.game_history_path = self.data_dir / "game_history.json"
        self.strategy_path     = self.data_dir / "strategy_weights.json"
        self.enemy_profiles_path = self.data_dir / "enemy_profiles.json"
        self.combat_log_path   = self.data_dir / "combat_log.json"
        self.region_intel_path = self.data_dir / "region_intel.json"

        # In-memory caches (flushed to disk on save)
        self._current_game: Dict = {}
        self._game_history: List[Dict] = self._load(self.game_history_path, [])
        self._strategy_weights: Dict = self._load(self.strategy_path, self._default_weights())
        self._enemy_profiles: Dict = self._load(self.enemy_profiles_path, {})
        self._combat_log: List[Dict] = self._load(self.combat_log_path, [])
        self._region_intel: Dict = self._load(self.region_intel_path, {})

        logger.info(f"Memory loaded: {len(self._game_history)} games, "
                    f"{len(self._enemy_profiles)} enemy profiles")

    # -------------------------------------------------------------------------
    # FILE I/O
    # -------------------------------------------------------------------------

    def _load(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                with open(path, "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load {path}: {e}")
        return default

    def _save(self, path: Path, data: Any):
        try:
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, default=str)
            tmp.replace(path)  # Atomic write
        except IOError as e:
            logger.error(f"Could not save {path}: {e}")

    def save_all(self):
        """Flush all in-memory data to disk."""
        self._save(self.game_history_path, self._game_history)
        self._save(self.strategy_path, self._strategy_weights)
        self._save(self.enemy_profiles_path, self._enemy_profiles)
        self._save(self.combat_log_path, self._combat_log[-5000:])  # Keep last 5000
        self._save(self.region_intel_path, self._region_intel)
        logger.debug("Memory saved to disk")

    # -------------------------------------------------------------------------
    # DEFAULT DATA STRUCTURES
    # -------------------------------------------------------------------------

    def _default_weights(self) -> Dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": datetime.utcnow().isoformat(),
            "games_played": 0,

            # Action preference weights [0.0 - 1.0]
            "action_weights": {
                "explore_vs_move":      0.5,   # >0.5 = prefer explore
                "attack_vs_evade":      0.6,   # >0.5 = prefer attack
                "heal_threshold":       0.30,  # heal when HP% < this
                "rest_threshold":       0.30,  # rest when EP% < this
                "use_facility":         0.7,   # probability of using facility
                "flee_when_losing":     0.7,   # flee if win_prob < this
            },

            # Terrain preferences (learned from wins/deaths)
            "terrain_scores": {
                "plains": 0.5, "forest": 0.6, "hills": 0.7,
                "ruins": 0.65, "water": 0.3
            },

            # Combat aggressiveness by game phase
            "phase_aggression": {
                "early":  0.5,   # Days 1-4: cautious
                "mid":    0.7,   # Days 5-10: moderate
                "late":   0.9,   # Days 11-14: aggressive
            },

            # Win probability threshold to attack
            "attack_threshold": 0.65,

            # Learning rate
            "learning_rate": 0.1,
        }

    # -------------------------------------------------------------------------
    # CURRENT GAME TRACKING
    # -------------------------------------------------------------------------

    def start_game(self, game_id: str, agent_id: str, agent_name: str):
        """Initialize tracking for a new game."""
        self._current_game = {
            "game_id": game_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "start_time": datetime.utcnow().isoformat(),
            "turns": [],
            "kills": 0,
            "deaths_caused": 0,
            "items_collected": [],
            "items_used": [],
            "regions_visited": [],
            "combat_outcomes": [],  # [{enemy, win, damage_dealt, damage_taken}]
            "death_zone_escapes": 0,
            "final_rank": None,
            "final_hp": None,
            "is_winner": False,
            "moltz_earned": 0,
            "death_cause": None,
            "strategies_used": [],
        }
        logger.info(f"Started tracking game {game_id}")

    def record_turn(self, turn_num: int, intel: Dict, action: Dict, result: Dict):
        """Record a single turn's decision and outcome."""
        if not self._current_game:
            return

        # Ringkasan inventory: hitung item per kategori tanpa simpan full list
        inventory = intel.get("inventory", []) or []
        inv_summary = {}
        for item in inventory:
            cat = item.get("category", "other")
            inv_summary[cat] = inv_summary.get(cat, 0) + 1
        # Heal HP tersedia (untuk korelasi survival-vs-inventory di ML)
        item_hp_map = {
            "emergency_food": 20, "bandage": 30, "medkit": 50, "energy_drink": 0
        }
        heal_hp_avail = sum(
            item_hp_map.get(i.get("typeId","").lower(), 0)
            for i in inventory if i.get("category") == "recovery"
        )
        heal_item_count = sum(
            1 for i in inventory
            if i.get("category") == "recovery"
            and item_hp_map.get(i.get("typeId","").lower(), 0) > 0
        )
        equipped = intel.get("equipped_weapon") or {}

        turn_record = {
            "turn"            : turn_num,
            "hp"              : intel.get("hp"),
            "ep"              : intel.get("ep"),
            "action_type"     : action.get("type"),
            "region"          : intel.get("region_name"),
            "is_death_zone"   : intel.get("is_death_zone"),
            "local_enemies"   : len(intel.get("local_agents", [])),
            "local_monsters"  : len(intel.get("local_monsters", [])),
            "success"         : result.get("success", False),
            "timestamp"       : time.time(),
            # ── Inventory snapshot (untuk survival analysis ML) ────
            "inv_heal_count"  : heal_item_count,    # jumlah heal items
            "inv_heal_hp"     : heal_hp_avail,       # total HP bisa di-restore
            "inv_weapon"      : equipped.get("typeId", "fist"),  # senjata aktif
            "inv_weapon_bonus": equipped.get("atkBonus", 0),     # bonus ATK senjata
            "inv_total"       : len(inventory),      # total item
            "inv_categories"  : inv_summary,         # {weapon:1, recovery:2, ...}
        }
        self._current_game["turns"].append(turn_record)

        # Track visited regions
        region = intel.get("region_id")
        if region and region not in self._current_game["regions_visited"]:
            self._current_game["regions_visited"].append(region)

    def record_combat(self, target_id: str, target_type: str,
                      target_data: Dict, won: bool,
                      damage_dealt: int, damage_taken: int,
                      my_stats: Dict = None):
        """
        Record combat outcome untuk learning.

        my_stats = snapshot kondisi kita saat attack, termasuk:
          hp, ep, atk, def, weapon_bonus, effective_hp,
          heal_hp_total, heal_count, heal_ep_total, best_heal_hp

        Field ini yang dipakai ML untuk belajar: apakah punya
        healing items meningkatkan chance menang?
        """
        if not self._current_game:
            return

        # Bangun enemy_stats terstruktur dari target_data
        t_weapon = target_data.get("equippedWeapon") or {}
        enemy_stats = {
            "hp"          : target_data.get("hp", 50),
            "atk"         : target_data.get("atk", 10),
            "def"         : target_data.get("def", 5),
            "weapon_bonus": t_weapon.get("atkBonus", 0),
        }

        record = {
            # Target info
            "target_id"    : target_id,
            "target_type"  : target_type,
            "target_hp"    : target_data.get("hp"),
            "target_atk"   : target_data.get("atk"),
            "target_def"   : target_data.get("def"),
            "target_weapon": t_weapon.get("typeId", "fist"),
            # Combat result
            "won"          : won,
            "damage_dealt" : damage_dealt,
            "damage_taken" : damage_taken,
            "timestamp"    : time.time(),
            # Snapshot kondisi kita saat attack (untuk ML training)
            "my_stats"     : my_stats or {},
            "enemy_stats"  : enemy_stats,
        }
        self._current_game["combat_outcomes"].append(record)

        if won and target_type == "agent":
            self._current_game["kills"] += 1

        # Enemy profile hanya untuk agent manusia (bukan monster)
        if target_type == "agent" and target_id and target_id != "unknown":
            self._update_enemy_profile(target_id, target_data, won)

        # Simpan ke combat_log — ini yang di-load saat ML training
        self._combat_log.append({
            **record,
            "target_name": target_data.get("name", "?"),
        })

    def record_death_zone_escape(self):
        if self._current_game:
            self._current_game["death_zone_escapes"] += 1

    def record_item_collected(self, item: Dict):
        if self._current_game:
            self._current_game["items_collected"].append(item.get("typeId", "unknown"))

    def record_item_used(self, item_id: str, type_id: str, hp_before: float,
                         hp_after: float, context: str = "passive"):
        """
        Log pemakaian item untuk ML learning.

        Args:
            item_id    : ID item yang dipakai
            type_id    : tipe item (emergency_food, bandage, medkit, energy_drink)
            hp_before  : HP kita sebelum pakai item
            hp_after   : HP kita setelah (estimasi: hp_before + heal_value)
            context    : "combat" (ada musuh) | "passive" (tidak ada musuh) |
                         "critical" (HP < 25)
        """
        if not self._current_game:
            return
        HEAL_MAP = {"emergency_food": 20, "bandage": 30,
                    "medkit": 50, "energy_drink": 0}
        hp_restored = HEAL_MAP.get(type_id.lower(), 0)
        record = {
            "item_id"     : item_id,
            "type_id"     : type_id,
            "hp_before"   : hp_before,
            "hp_restored" : hp_restored,
            "hp_after"    : min(100.0, hp_before + hp_restored),
            "context"     : context,   # combat | passive | critical
            "timestamp"   : time.time(),
        }
        # Simpan ke items_used list
        if "items_used" not in self._current_game:
            self._current_game["items_used"] = []
        self._current_game["items_used"].append(record)

        # Update combat_log entry terakhir: heal ini mungkin saat combat
        if context == "combat" and self._current_game.get("combat_outcomes"):
            last = self._current_game["combat_outcomes"][-1]
            last["heals_used"] = last.get("heals_used", 0) + 1
            last["hp_healed_in_combat"] = (
                last.get("hp_healed_in_combat", 0) + hp_restored
            )

    def update_region_intel(self, region_id: str, region_name: str,
                             is_dz: bool, terrain: str = ""):
        """Simpan intel region untuk referensi lintas game."""
        if not region_id:
            return
        existing = self._region_intel.get(region_id, {})
        self._region_intel[region_id] = {
            "name": region_name,
            "terrain": terrain or existing.get("terrain", ""),
            "was_dz": is_dz or existing.get("was_dz", False),
            "dz_count": existing.get("dz_count", 0) + (1 if is_dz else 0),
            "visit_count": existing.get("visit_count", 0) + 1,
        }

    def end_game(self, is_winner: bool, final_rank: int,
                 final_hp: int, moltz_earned: int, death_cause: str = None):
        """Finalize game record and trigger learning."""
        if not self._current_game:
            return

        self._current_game.update({
            "end_time": datetime.utcnow().isoformat(),
            "is_winner": is_winner,
            "final_rank": final_rank,
            "final_hp": final_hp,
            "moltz_earned": moltz_earned,
            "death_cause": death_cause,
            "kills": self._current_game.get("kills", 0),
            "turns_played": len(self._current_game["turns"]),
        })

        self._game_history.append(self._current_game.copy())
        self._strategy_weights["games_played"] += 1
        self.save_all()

        logger.info(f"Game ended: rank={final_rank}, winner={is_winner}, "
                    f"kills={self._current_game.get('kills', 0)}, "
                    f"moltz={moltz_earned}")

        return self._current_game.copy()

    # -------------------------------------------------------------------------
    # ENEMY PROFILING
    # -------------------------------------------------------------------------

    def _update_enemy_profile(self, agent_id: str, agent_data: Dict, we_won: bool):
        """Update enemy agent profile based on combat outcome."""
        if agent_id not in self._enemy_profiles:
            self._enemy_profiles[agent_id] = {
                "encounters": 0,
                "wins_against": 0,
                "losses_to": 0,
                "observed_atk": [],
                "observed_def": [],
                "observed_hp": [],
                "weapons_seen": [],
                "last_seen": None,
            }

        profile = self._enemy_profiles[agent_id]
        profile["encounters"] += 1
        profile["last_seen"] = datetime.utcnow().isoformat()

        if we_won:
            profile["wins_against"] += 1
        else:
            profile["losses_to"] += 1

        if agent_data.get("atk"):
            profile["observed_atk"].append(agent_data["atk"])
        if agent_data.get("def"):
            profile["observed_def"].append(agent_data["def"])
        if agent_data.get("hp"):
            profile["observed_hp"].append(agent_data["hp"])

        weapon = agent_data.get("equippedWeapon")
        if weapon and weapon.get("typeId"):
            profile["weapons_seen"].append(weapon["typeId"])

        # Trim lists to last 10 observations
        for key in ["observed_atk", "observed_def", "observed_hp", "weapons_seen"]:
            profile[key] = profile[key][-10:]

    def get_enemy_profile(self, agent_id: str) -> Optional[Dict]:
        """Get historical data on a specific enemy agent."""
        return self._enemy_profiles.get(agent_id)

    # -------------------------------------------------------------------------
    # STRATEGY WEIGHTS ACCESS
    # -------------------------------------------------------------------------

    @property
    def weights(self) -> Dict:
        return self._strategy_weights

    @property
    def action_weights(self) -> Dict:
        return self._strategy_weights.get("action_weights", {})

    @property
    def attack_threshold(self) -> float:
        return self._strategy_weights.get("attack_threshold", 0.65)

    def update_weight(self, key: str, delta: float):
        """Apply learning update to a strategy weight."""
        weights = self._strategy_weights["action_weights"]
        if key in weights:
            lr = self._strategy_weights.get("learning_rate", 0.1)
            weights[key] = max(0.1, min(0.95, weights[key] + delta * lr))

    def update_attack_threshold(self, delta: float):
        """Adjust combat aggressiveness threshold."""
        lr = self._strategy_weights.get("learning_rate", 0.1)
        current = self._strategy_weights.get("attack_threshold", 0.65)
        self._strategy_weights["attack_threshold"] = max(0.45, min(0.90,
                                                         current + delta * lr))

    # -------------------------------------------------------------------------
    # GAME STATISTICS
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Return overall performance statistics."""
        history = self._game_history
        if not history:
            return {"games": 0}

        wins = sum(1 for g in history if g.get("is_winner"))
        total_kills = sum(g.get("kills", 0) for g in history)
        total_moltz = sum(g.get("moltz_earned", 0) for g in history)
        avg_rank = sum(g.get("final_rank", 100) for g in history) / len(history)

        # Recent form (last 10 games)
        recent = history[-10:]
        recent_wins = sum(1 for g in recent if g.get("is_winner"))
        recent_rate = recent_wins / len(recent) if recent else 0.0

        return {
            "games": len(history),
            "wins": wins,
            "win_rate": wins / len(history),
            "recent_win_rate": recent_rate,
            "total_kills": total_kills,
            "avg_kills_per_game": total_kills / len(history),
            "total_moltz": total_moltz,
            "avg_rank": avg_rank,
            "games_until_ml": max(0, 5 - len(history)),
        }

    def get_recent_games(self, n: int = 10) -> List[Dict]:
        return self._game_history[-n:]

    def get_death_causes(self) -> Dict[str, int]:
        """Analyze what has been killing the bot."""
        causes = {}
        for game in self._game_history:
            cause = game.get("death_cause", "unknown") or "unknown"
            causes[cause] = causes.get(cause, 0) + 1
        return causes

    def games_played(self) -> int:
        return len(self._game_history)
