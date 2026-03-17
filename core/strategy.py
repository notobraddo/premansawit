"""
==============================================================================
MOLTY ROYALE BOT - STRATEGY DECISION ENGINE
==============================================================================
The "brain" of the bot. Takes parsed intel and learning weights,
produces the optimal action for each situation.

Priority system (highest → lowest):
  P0: Escape death zone (emergency)
  P1: Heal if critical HP
  P2: Rest if EP too low to act
  P3: Free actions (pickup, equip best weapon)
  P4: Combat (if win probability meets threshold)
  P5: Use facilities
  P6: Explore / collect items
  P7: Move toward safe/valuable regions
  P8: Rest (fallback)
"""

import logging
from typing import Dict, Optional, Tuple, List

from .analyzer import StateAnalyzer, WEAPON_PRIORITY

logger = logging.getLogger("MoltyBot.Strategy")

# == Game Time Rules ==================================================
# 1 turn = 6 game hours = 60s real time
# 4 turns = 1 day | Total = 56 turns = 14 days | Game ends Turn 56
# Ranking: Kills first -> then HP remaining
# Strategy: End-game -> heal to 100 HP, maximize kills & $Moltz

TOTAL_TURNS       = 56   # Turn 56 = Day 14, 00:00
TURNS_PER_DAY     = 4
PHASE_MID_START   = 17   # Day 5  (Turn 17)
PHASE_LATE_START  = 41   # Day 11 (Turn 41) - endgame prep
PHASE_FINAL_START = 49   # Day 13 (Turn 49) - final push

# HP targets per phase (HP = tiebreaker after kills in ranking)
HP_ENDGAME_TARGET = 100  # Day 11+ -> always heal to 100
HP_LATE_TARGET    = 80   # Day 7+  -> keep above 80


class StrategyEngine:
    """
    Stateful strategy engine. Holds current game context and produces
    optimal actions based on intel + learned weights.
    """

    def __init__(self, analyzer: StateAnalyzer, memory, learning_engine):
        self.analyzer = analyzer
        self.memory = memory
        self.learning = learning_engine
        self.turn_number = 0
        self.explored_regions = set()
        self.last_region_id = None
        self.stuck_counter = 0

        # ── Death Zone Memory ─────────────────────────────────────
        # Track semua region yang pernah kita lihat sebagai DZ
        # Format: region_id (str). Jangan pernah masuk ke sini!
        self.known_dz_regions: set = set()

        # ── Attack Futility Tracker ───────────────────────────────
        # Jika menyerang di region yang sama > MAX_ATTACKS_NO_KILL kali
        # tanpa kill baru → pindah region
        self.attack_count_per_region: dict = {}  # region_id -> count
        self.kills_at_last_check: int = 0
        MAX_ATTACKS_NO_KILL = 4  # max serangan di 1 region tanpa kill
        self.MAX_ATTACKS_NO_KILL = MAX_ATTACKS_NO_KILL

        # ── Facility Damage Tracker ───────────────────────────────
        # Track fasilitas yang merusak HP kita saat interact
        self.dangerous_facilities: set = set()  # region_id
        self.last_turn_hp: float = 100.0
        self.last_action_type: str = ""
        self.last_region_id_for_facility: str = ""

    # -------------------------------------------------------------------------
    # MAIN DECISION METHOD
    # -------------------------------------------------------------------------

    def decide(self, intel: Dict) -> Tuple[Dict, str, List[Dict]]:
        """
        Returns (main_action, reasoning, free_actions).

        main_action  → The EP-costing turn action
        reasoning    → Human-readable explanation for thought system
        free_actions → List of free actions to execute before main action
        """
        self.turn_number += 1
        weights = self.memory.action_weights
        attack_threshold = self.memory.attack_threshold

        # Track stuck bot (same region for too long)
        if intel["region_id"] == self.last_region_id:
            self.stuck_counter += 1
        else:
            self.stuck_counter = 0
            self.last_region_id = intel["region_id"]

        self.explored_regions.add(intel["region_id"])

        # -- Game Time: hitung Day dari turn_number --
        day        = ((self.turn_number - 1) // TURNS_PER_DAY) + 1
        turns_left = max(0, TOTAL_TURNS - self.turn_number)
        phase      = self._get_phase()

        # Endgame flags
        is_late  = self.turn_number >= PHASE_LATE_START   # Day 11+
        is_final = self.turn_number >= PHASE_FINAL_START  # Day 13+

        # Attack threshold by phase
        # Early: konservatif | Mid: normal | Late: agresif | Final: all-out
        if is_final:
            effective_threshold = max(0.40, attack_threshold - 0.20)
        elif is_late:
            effective_threshold = max(0.45, attack_threshold - 0.15)
        elif phase == "late":
            effective_threshold = max(0.50, attack_threshold - 0.10)
        elif phase == "mid":
            effective_threshold = attack_threshold
        else:
            effective_threshold = min(0.80, attack_threshold + 0.05)

        # Log phase transition once
        _pkey = f"{phase}_{is_late}_{is_final}"
        if not hasattr(self, "_logged_phase") or self._logged_phase != _pkey:
            self._logged_phase = _pkey
            if is_final:
                logger.info(f"FINAL PUSH Day {day} T{self.turn_number} | "
                            f"{turns_left} turns left | threshold={effective_threshold:.0%} | "
                            f"ALL OUT for kills+HP!")
            elif is_late:
                logger.info(f"ENDGAME Day {day} T{self.turn_number} | "
                            f"{turns_left} turns left | threshold={effective_threshold:.0%} | "
                            f"Heal to 100, hunt kills")
            else:
                logger.info(f"Phase {phase.upper()} | Day {day} | threshold={effective_threshold:.0%}")

        # ── Update Death Zone Memory ──────────────────────────────
        # Setiap turn: catat region DZ yang kita lihat/kunjungi
        if intel["is_death_zone"]:
            self.known_dz_regions.add(intel["region_id"])
            if intel["region_id"]:
                logger.debug(f"DZ Memory: added {intel['region_name']} to blacklist")
        # Tambahkan dari pendingDeathzones (akan jadi DZ)
        for dz_id in intel.get("pending_death_zones", []):
            self.known_dz_regions.add(dz_id)
        # Tambahkan dari connections_status (adjacent region yg terlihat DZ)
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                self.known_dz_regions.add(rid)

        # ── Facility Damage Detection ─────────────────────────────
        # Jika HP turun setelah interact DAN tidak ada musuh → fasilitas berbahaya
        hp_now = intel["hp"]
        if (self.last_action_type == "interact"
                and not intel["local_agents"] and not intel["local_monsters"]
                and hp_now < self.last_turn_hp - 5):
            self.dangerous_facilities.add(self.last_region_id_for_facility)
            logger.warning(
                f"TRAP! Facility di {intel['region_name']} merusak HP "
                f"({self.last_turn_hp:.0f}→{hp_now:.0f}). Blacklist!"
            )
        self.last_turn_hp = hp_now

        # ── Attack Futility Check ─────────────────────────────────
        # Cek apakah kill bertambah sejak terakhir kita cek
        current_kills = intel.get("kills", 0)
        if current_kills > self.kills_at_last_check:
            # Ada kill! Reset counter untuk region ini
            self.attack_count_per_region[intel["region_id"]] = 0
            self.kills_at_last_check = current_kills
        if self.last_action_type == "attack":
            reg = intel["region_id"]
            self.attack_count_per_region[reg] = \
                self.attack_count_per_region.get(reg, 0) + 1

        # ==========================================================
        # FREE ACTIONS (execute these regardless of main action)
        # ==========================================================
        free_actions = self._decide_free_actions(intel, weights)

        # ==========================================================
        # P0: DEATH ZONE EMERGENCY
        # ==========================================================
        dz_level = self.analyzer.death_zone_danger_level(intel)
        if dz_level >= 2:
            target = self.analyzer.safest_escape_region(intel, self.known_dz_regions)
            if target:
                reason = (f"EMERGENCY: In death zone! (HP:{intel['hp']:.0f}) "
                          f"Fleeing to {target[:8]}")
                logger.warning(f"⚡ DZ ESCAPE! {intel['region_name']} → {target[:8]}")
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return {"type": "move", "regionId": target}, reason, free_actions

        # ==========================================================
        # P1: CRITICAL HEAL
        # ==========================================================
        if intel["hp"] <= self.analyzer.hp_critical:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                reason = f"CRITICAL HP ({intel['hp']}/100) - using {heal_item.get('typeId')}"
                return {"type": "use_item", "itemId": heal_item["id"]}, reason, free_actions

            # No heal item → flee jika ada musuh, REST jika aman
            if intel["local_agents"] or intel["local_monsters"]:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    reason = f"Critical HP ({intel['hp']:.0f}) + enemies → fleeing to {escape[:8]}"
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return {"type": "move", "regionId": escape}, reason, free_actions
            else:
                # Aman tapi HP kritis dan tidak ada heal → REST
                # Jangan terus explore/move, nanti ketemu musuh dalam kondisi lemah!
                reason = (f"Critical HP ({intel['hp']:.0f}) no heal items → RESTING "
                          f"(conserve HP, avoid combat)")
                logger.warning(f"HP KRITIS {intel['hp']:.0f} — REST paksa!")
                self.last_action_type = "rest"
                return {"type": "rest"}, reason, free_actions

        # ==========================================================
        # P1b: ENDGAME HP (Day 11+) — heal to HP target for ranking
        # Ranking: kills first, THEN HP sisa -> wajib HP max di akhir
        # ==========================================================
        if is_late:
            hp_target = HP_ENDGAME_TARGET if is_final else HP_LATE_TARGET
            if intel["hp"] < hp_target and not intel["local_agents"]:
                heal_item = self._find_best_heal_item(intel["inventory"])
                if heal_item:
                    label = "FINAL" if is_final else "ENDGAME"
                    reason = (f"{label} HEAL Day {day}: "
                              f"HP {intel['hp']:.0f}->{hp_target} (ranking!) "
                              f"using {heal_item.get('typeId')}")
                    return {"type": "use_item", "itemId": heal_item["id"]}, reason, free_actions

        # ==========================================================
        # P2: LOW HP (not critical) — use heal if available
        # ==========================================================
        hp_threshold = weights.get("heal_threshold", 0.30) * 100
        if intel["hp"] < hp_threshold:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                reason = f"Low HP ({intel['hp']:.0f}) - healing with {heal_item.get('typeId')}"
                return {"type": "use_item", "itemId": heal_item["id"]}, reason, free_actions

        # ==========================================================
        # P3: DEATH ZONE WARNING — preemptive move
        # ==========================================================
        if dz_level == 1:
            target = self.analyzer.safest_escape_region(intel, self.known_dz_regions)
            if target:
                reason = f"Death zone incoming! Moving to {target[:8]}"
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return {"type": "move", "regionId": target}, reason, free_actions

        # ==========================================================
        # P4: EP MANAGEMENT
        # ==========================================================
        ep_pct = intel["ep"] / max(intel["max_ep"], 1)
        rest_threshold = weights.get("rest_threshold", 0.30)

        # Must have EP 2 to attack; if only 1 EP, rest unless safe to explore
        if intel["ep"] < self.analyzer.ep_min_attack:
            if not intel["local_agents"]:  # No immediate threat
                reason = f"EP too low ({intel['ep']}) to attack - resting"
                return {"type": "rest"}, reason, free_actions
            else:
                # Enemy here but can't attack — flee
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    reason = f"Low EP ({intel['ep']}) with enemy present - fleeing"
                    return {"type": "move", "regionId": escape}, reason, free_actions

        if ep_pct < rest_threshold and not intel["local_agents"]:
            reason = f"Resting to recover EP ({intel['ep']}/{intel['max_ep']})"
            return {"type": "rest"}, reason, free_actions

        # ==========================================================
        # P5: COMBAT — Attack agents
        # ==========================================================
        if intel["local_agents"] and intel["ep"] >= self.analyzer.ep_min_attack:
            # Cek attack futility: jika sudah serang > MAX kali di region ini
            # tanpa kill baru → musuh terlalu kuat, pindah!
            atk_count = self.attack_count_per_region.get(intel["region_id"], 0)
            if atk_count >= self.MAX_ATTACKS_NO_KILL:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    reason = (f"FUTILE: {atk_count} serangan di {intel['region_name']} "
                              f"tanpa kill → pindah ke {escape[:8]}")
                    logger.info(reason)
                    self.attack_count_per_region[intel["region_id"]] = 0
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return {"type": "move", "regionId": escape}, reason, free_actions

            target, win_prob, reasoning = self._evaluate_combat_targets(
                intel, intel["local_agents"], effective_threshold
            )
            if target:
                self.last_action_type = "attack"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "attack", "targetId": target["id"], "targetType": "agent"},
                    reasoning, free_actions
                )
            else:
                # Enemies present but odds too low — flee
                escape = self.analyzer.safest_escape_region(intel)
                if escape and len(intel["local_agents"]) > 0:
                    reason = f"Enemies present but win_prob too low ({win_prob:.0%}) - evading"
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return {"type": "move", "regionId": escape}, reason, free_actions

        # ==========================================================
        # P6: COMBAT — Attack monsters (resource farming)
        # ==========================================================
        if intel["local_monsters"] and intel["ep"] >= self.analyzer.ep_min_attack:
            # Futility check untuk monster juga
            atk_count_m = self.attack_count_per_region.get(intel["region_id"], 0)
            if atk_count_m < self.MAX_ATTACKS_NO_KILL * 2:  # Monster butuh lebih banyak serangan
                target, win_prob, reasoning = self._evaluate_monster_targets(
                    intel, intel["local_monsters"]
                )
                if target:
                    self.last_action_type = "attack"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "attack", "targetId": target["id"], "targetType": "monster"},
                        reasoning, free_actions
                    )

        # ==========================================================
        # P7: USE FACILITIES (skip jika pernah merusak HP)
        # ==========================================================
        facility = self.analyzer.get_useful_facility(intel)
        if facility and weights.get("use_facility", 0.7) > 0.5:
            # Skip jika region ini terbukti menyakiti kita
            if intel["region_id"] in self.dangerous_facilities:
                logger.debug(f"Skipping DANGEROUS facility di {intel['region_name']}")
            else:
                reason = f"Using facility: {facility.get('type')} in {intel['region_name']}"
                self.last_action_type = "interact"
                self.last_region_id_for_facility = intel["region_id"]
                return ({"type": "interact", "interactableId": facility["id"]},
                        reason, free_actions)

        # ==========================================================
        # P7b: $MOLTZ FARMING — mid/late hunt monsters agresif
        # $Moltz dari: monsters, agents, supply caches, ground loot
        # ==========================================================
        if phase in ("mid", "late") and intel["ep"] >= self.analyzer.ep_min_attack:
            if intel["local_monsters"]:
                target, win_prob, reasoning = self._evaluate_monster_targets(
                    intel, intel["local_monsters"]
                )
                if target:
                    return (
                        {"type": "attack", "targetId": target["id"], "targetType": "monster"},
                        reasoning, free_actions
                    )

        # ==========================================================
        # P8: ENERGY DRINK if EP low and no monsters
        # ==========================================================
        if intel["ep"] < 5:
            drink = next((i for i in intel["inventory"]
                          if "energy" in i.get("typeId", "").lower()), None)
            if drink:
                reason = f"Using Energy Drink to recover EP ({intel['ep']})"
                return {"type": "use_item", "itemId": drink["id"]}, reason, free_actions

        # ==========================================================
        # P9: EXPLORE OR MOVE
        # ==========================================================
        # Explore if we haven't explored this region yet
        if intel["region_id"] not in self.explored_regions or \
           (self.stuck_counter > 2 and not intel["local_monsters"]):
            if intel["region_id"] not in self.explored_regions:
                self.explored_regions.add(intel["region_id"])
                reason = f"Exploring {intel['region_name']} for items/enemies"
                return {"type": "explore"}, reason, free_actions

        # Move if stuck or prefer exploration over standing still
        explore_bias = weights.get("explore_vs_move", 0.5)
        if self.stuck_counter > 1 or explore_bias < 0.5:
            target_region = self._choose_move_target(intel)
            if target_region:
                reason = f"Moving to {target_region} (stuck={self.stuck_counter})"
                return {"type": "move", "regionId": target_region}, reason, free_actions

        # Default: explore current region again for items
        reason = f"Exploring {intel['region_name']} (EP:{intel['ep']}, HP:{intel['hp']})"
        self.last_action_type = "explore"
        self.last_region_id_for_facility = intel["region_id"]
        return {"type": "explore"}, reason, free_actions

    # -------------------------------------------------------------------------
    # FREE ACTION PLANNER
    # -------------------------------------------------------------------------

    def _decide_free_actions(self, intel: Dict, weights: Dict) -> List[Dict]:
        """
        Plan free actions to execute before the main turn action.
        Returns list of action dicts. Order matters:
          1. Pick up currency (always)
          2. Pick up weapons and items (if space)
          3. Equip best weapon
          4. Respond to messages
        """
        free = []

        # ---- 1. Pick up items from ground ----
        if not intel["inventory_full"] and intel["local_items"]:
            # Always grab currency
            for entry in intel["local_items"]:
                item = entry.get("item", {})
                if item.get("category") == "currency":
                    free.append({"type": "pickup", "itemId": item["id"]})

            # Grab best weapon or recovery items
            if len(intel["inventory"]) < 9:  # Leave 1 slot buffer
                best_entry = self.analyzer.get_best_item_on_ground(
                    intel["local_items"], intel["inventory"]
                )
                if best_entry:
                    item = best_entry.get("item", {})
                    if item.get("category") != "currency":  # Already grabbed above
                        free.append({"type": "pickup", "itemId": item["id"]})

        # ---- 2. Equip best weapon ----
        best_weapon = self.analyzer.best_weapon_in_inventory(intel["inventory"])
        if best_weapon:
            if self.analyzer.should_upgrade_weapon(intel["equipped_weapon"], best_weapon):
                free.append({"type": "equip", "itemId": best_weapon["id"]})

        # ---- 3. Respond to messages (diplomatic) ----
        for msg in intel["unread_messages"][:2]:  # Max 2 replies per turn
            sender_id = msg.get("senderId")
            msg_type  = msg.get("type", "public")
            content   = msg.get("content", "").lower()

            if sender_id and "enemy" not in content and "kill" not in content:
                if msg_type == "private" or msg.get("channel") == "private":
                    free.append({
                        "type": "whisper",
                        "targetId": sender_id,
                        "message": "Acknowledged. Open to alliance."
                    })
                # Don't spam public talk

        return free

    # -------------------------------------------------------------------------
    # COMBAT TARGET EVALUATION
    # -------------------------------------------------------------------------

    def _evaluate_combat_targets(
        self, intel: Dict, targets: List[Dict], threshold: float
    ) -> Tuple[Optional[Dict], float, str]:
        """
        Evaluate agent targets and return (best_target, win_prob, reasoning).
        Returns (None, best_prob, reason) if no target meets threshold.
        """
        my_stats = self._my_combat_stats(intel)
        best_target = None
        best_score = -1.0
        best_prob = 0.0

        for target in targets:
            enemy_stats = self._enemy_combat_stats(target)

            # Check historical profile for this enemy
            profile = self.memory.get_enemy_profile(target.get("id", ""))
            if profile:
                hist_wins = profile.get("wins_against", 0)
                hist_losses = profile.get("losses_to", 0)
                total = hist_wins + hist_losses
                if total > 0:
                    hist_win_rate = hist_wins / total
                    win_prob = (self.learning.predict_combat(my_stats, enemy_stats) * 0.7 +
                                hist_win_rate * 0.3)
                else:
                    win_prob = self.learning.predict_combat(my_stats, enemy_stats)
            else:
                win_prob = self.learning.predict_combat(my_stats, enemy_stats)

            # Score: win_prob weighted by how weak they are (kill weak first)
            target_hp = target.get("hp", 100)
            weakness_bonus = max(0, (100 - target_hp) / 200)
            score = win_prob + weakness_bonus

            if score > best_score:
                best_score = score
                best_target = target
                best_prob = win_prob

        if best_target and best_prob >= threshold:
            reason = (f"ATTACKING agent {best_target.get('name','?')} "
                      f"(win_prob={best_prob:.0%}, HP={best_target.get('hp')}, "
                      f"threshold={threshold:.0%})")
            return best_target, best_prob, reason

        reason = (f"Enemies present but best win_prob={best_prob:.0%} < "
                  f"threshold={threshold:.0%}")
        return None, best_prob, reason

    def _evaluate_monster_targets(
        self, intel: Dict, monsters: List[Dict]
    ) -> Tuple[Optional[Dict], float, str]:
        """Evaluate monster targets. Attack weakest/easiest first."""
        my_stats = self._my_combat_stats(intel)

        # Sort by HP (weakest first → wolf → bear → bandit)
        sorted_monsters = sorted(monsters, key=lambda m: m.get("hp", 99))

        for monster in sorted_monsters:
            win_prob = self.analyzer.monster_win_probability(intel, monster)
            if win_prob >= 0.60:  # Lower threshold for monsters (good XP)
                reason = (f"HUNTING {monster.get('type','monster')} "
                          f"(win_prob={win_prob:.0%}, HP={monster.get('hp')})")
                return monster, win_prob, reason

        return None, 0.0, "Monsters too strong to fight safely"

    # -------------------------------------------------------------------------
    # MOVEMENT STRATEGY
    # -------------------------------------------------------------------------

    def _choose_move_target(self, intel: Dict) -> Optional[str]:
        """
        Choose which adjacent region to move to.
        Prefers: unvisited > hills > ruins > forest > plains > water
        Avoids: death zones, pending death zones
        """
        connections = intel["connections"]
        if not connections:
            return None

        pending_dz = set(str(x) for x in intel.get("pending_death_zones", []))
        # Gabungkan: known DZ + pending DZ + connections_status DZ
        all_dz = self.known_dz_regions | pending_dz
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                all_dz.add(rid)

        terrain_scores = self.memory.weights.get("terrain_scores", {})

        def region_score(region_id: str) -> float:
            score = 0.0
            if region_id not in self.explored_regions:
                score += 3.0
            if region_id in all_dz:
                score -= 100.0  # HARD penalty — jangan masuk DZ!
            # Jauhi dangerous facilities juga
            if region_id in self.dangerous_facilities:
                score -= 5.0
            return score

        # Prioritas: region TIDAK dalam all_dz sama sekali
        truly_safe = [c for c in connections if c not in all_dz]
        safe_connections = truly_safe if truly_safe else connections

        if not safe_connections:
            safe_connections = connections

        best = max(safe_connections, key=region_score)
        self.last_action_type = "move"
        self.last_region_id_for_facility = intel["region_id"]
        return best

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_phase(self) -> str:
        """Phase based on turn. 1 turn=6h, 4 turns=1 day, 56 turns total."""
        if self.turn_number < PHASE_MID_START:
            return "early"   # Days 1-4   turns 1-16
        elif self.turn_number < PHASE_LATE_START:
            return "mid"     # Days 5-10  turns 17-40
        return "late"        # Days 11-14 turns 41-56

    def _find_best_heal_item(self, inventory: List[Dict]) -> Optional[Dict]:
        """Find best recovery item — prioritize by HP restore value."""
        heal_items = [i for i in inventory if i.get("category") == "recovery"
                      and "energy" not in i.get("typeId", "").lower()]
        if not heal_items:
            return None

        # Medkit > Bandage > Emergency Food
        priority = {"medkit": 3, "bandage": 2, "emergency_food": 1}

        def item_score(item):
            tid = item.get("typeId", "").lower()
            for key, score in priority.items():
                if key in tid:
                    return score
            return 0

        return max(heal_items, key=item_score)

    def _my_combat_stats(self, intel: Dict) -> Dict:
        """Build my combat stats dict for ML prediction."""
        weapon_bonus, weapon_range = self.analyzer.get_equipped_bonus(
            intel["equipped_weapon"]
        )
        # Hitung heal stats dari inventory (untuk kalkulasi combat)
        heal_stats = self.analyzer.inventory_heal_stats(intel.get("inventory", []))
        return {
            "hp"           : intel["hp"],
            "ep"           : intel["ep"],
            "atk"          : intel["atk"],
            "def"          : intel["def"],
            "weapon_bonus" : weapon_bonus,
            "weapon_range" : weapon_range,
            # Inventory heal data (untuk ML features & combat sim)
            "heal_hp_total": heal_stats["heal_hp_total"],
            "heal_ep_total": heal_stats["heal_ep_total"],
            "heal_count"   : heal_stats["heal_count"],
            "best_heal_hp" : heal_stats["best_heal_hp"],
            "effective_hp" : intel["hp"] + heal_stats["heal_hp_total"],
            "inventory"    : intel.get("inventory", []),  # full inventory untuk sim
        }

    def _enemy_combat_stats(self, target: Dict) -> Dict:
        """Build enemy combat stats dict for ML prediction."""
        weapon = target.get("equippedWeapon") or {}
        return {
            "hp": target.get("hp", 50),
            "atk": target.get("atk", 10),
            "def": target.get("def", 5),
            "weapon_bonus": weapon.get("atkBonus", 0),
        }

    def reset_for_new_game(self):
        """Reset per-game state."""
        self.turn_number = 0
        self.explored_regions = set()
        self.last_region_id = None
        self.stuck_counter = 0
        # Reset per-game tracking
        self.known_dz_regions = set()
        self.attack_count_per_region = {}
        self.kills_at_last_check = 0
        self.dangerous_facilities = set()
        self.last_turn_hp = 100.0
        self.last_action_type = ""
        self.last_region_id_for_facility = ""
        logger.info("Strategy engine reset for new game")
