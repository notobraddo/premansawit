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

FIXES vs original:
  [FIX-1] Early phase threshold was RAISED (+0.05) — made bot most passive
          exactly when it needs kills to get weapons. Now LOWERED (-0.10).
  [FIX-2] Monster win_prob threshold hardcoded 0.60 — too high with fist
          weapon (wolf barely reaches 0.55). Now dynamic: 0.42 early,
          0.52 mid, 0.60 late.
  [FIX-3] Monster eval only ran in mid/late (P7b). Moved to P6 so it runs
          every phase — critical for early weapon farming.
  [FIX-4] explore_bias check caused infinite explore loop when stuck.
          Now forces move after stuck_counter > 2 regardless of bias.
  [FIX-5] Kill-confirm HP threshold raised 25→40 — finish wounded enemies
          earlier before they can flee/heal.
"""

import logging
from typing import Dict, Optional, Tuple, List

from .analyzer import StateAnalyzer, WEAPON_PRIORITY

logger = logging.getLogger("MoltyBot.Strategy")

# == Game Time Rules ==================================================
# 1 turn = 6 game hours = 60s real time
# 4 turns = 1 day | Total = 56 turns = 14 days | Game ends Turn 56
# Ranking: Kills first -> then HP remaining
TOTAL_TURNS       = 56
TURNS_PER_DAY     = 4
PHASE_MID_START   = 17   # Day 5  (Turn 17)
PHASE_LATE_START  = 41   # Day 11 (Turn 41)
PHASE_FINAL_START = 49   # Day 13 (Turn 49)

HP_ENDGAME_TARGET = 100
HP_LATE_TARGET    = 80


class StrategyEngine:

    def __init__(self, analyzer: StateAnalyzer, memory, learning_engine):
        self.analyzer  = analyzer
        self.memory    = memory
        self.learning  = learning_engine
        self.turn_number     = 0
        self.explored_regions = set()
        self.last_region_id  = None
        self.stuck_counter   = 0

        self.known_dz_regions: set = set()

        self.attack_count_per_region: dict = {}
        self.kills_at_last_check: int = 0
        self.MAX_ATTACKS_NO_KILL = 4

        self.dangerous_facilities: set = set()
        self.last_turn_hp: float = 100.0
        self.last_action_type: str = ""
        self.last_region_id_for_facility: str = ""

    # -------------------------------------------------------------------------
    # MAIN DECISION METHOD
    # -------------------------------------------------------------------------

    def decide(self, intel: Dict) -> Tuple[Dict, str, List[Dict]]:
        self.turn_number += 1
        weights          = self.memory.action_weights
        attack_threshold = self.memory.attack_threshold

        if intel["region_id"] == self.last_region_id:
            self.stuck_counter += 1
        else:
            self.stuck_counter  = 0
            self.last_region_id = intel["region_id"]

        self.explored_regions.add(intel["region_id"])

        day        = ((self.turn_number - 1) // TURNS_PER_DAY) + 1
        turns_left = max(0, TOTAL_TURNS - self.turn_number)
        phase      = self._get_phase()
        is_late    = self.turn_number >= PHASE_LATE_START
        is_final   = self.turn_number >= PHASE_FINAL_START

        # [FIX-1] Attack threshold by phase — early game MUST be lower,
        # not higher. Bot starts with fist and needs kills to get weapons.
        if is_final:
            effective_threshold = max(0.40, attack_threshold - 0.20)
        elif is_late:
            effective_threshold = max(0.45, attack_threshold - 0.15)
        elif phase == "late":
            effective_threshold = max(0.48, attack_threshold - 0.10)
        elif phase == "mid":
            effective_threshold = attack_threshold
        else:
            # [FIX-1] WAS: min(0.80, attack_threshold + 0.05) ← WRONG, too high
            effective_threshold = max(0.45, attack_threshold - 0.10)

        _pkey = f"{phase}_{is_late}_{is_final}"
        if not hasattr(self, "_logged_phase") or self._logged_phase != _pkey:
            self._logged_phase = _pkey
            label = "FINAL PUSH" if is_final else ("ENDGAME" if is_late else f"Phase {phase.upper()}")
            logger.info(
                f"{label} Day {day} T{self.turn_number} | "
                f"{turns_left} turns left | threshold={effective_threshold:.0%}"
            )

        # Death zone memory
        if intel["is_death_zone"]:
            self.known_dz_regions.add(intel["region_id"])
        for dz_id in intel.get("pending_death_zones", []):
            self.known_dz_regions.add(dz_id)
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                self.known_dz_regions.add(rid)

        # Facility damage detection
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

        # Attack futility check
        current_kills = intel.get("kills", 0)
        if current_kills > self.kills_at_last_check:
            self.attack_count_per_region[intel["region_id"]] = 0
            self.kills_at_last_check = current_kills
        if self.last_action_type == "attack":
            reg = intel["region_id"]
            self.attack_count_per_region[reg] = \
                self.attack_count_per_region.get(reg, 0) + 1

        free_actions = self._decide_free_actions(intel, weights)

        # ── P0: DEATH ZONE EMERGENCY ──────────────────────────────────────────
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

        # ── P1: CRITICAL HEAL ────────────────────────────────────────────────
        if intel["hp"] <= self.analyzer.hp_critical:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                reason = f"CRITICAL HP ({intel['hp']}/100) - using {heal_item.get('typeId')}"
                return {"type": "use_item", "itemId": heal_item["id"]}, reason, free_actions

            if intel["local_agents"] or intel["local_monsters"]:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "move", "regionId": escape},
                        f"Critical HP ({intel['hp']:.0f}) + enemies → fleeing",
                        free_actions
                    )
            else:
                self.last_action_type = "rest"
                return (
                    {"type": "rest"},
                    f"Critical HP ({intel['hp']:.0f}) no heals → REST",
                    free_actions
                )

        # ── P1b: ENDGAME HP (Day 11+) ────────────────────────────────────────
        if is_late:
            hp_target = HP_ENDGAME_TARGET if is_final else HP_LATE_TARGET
            if intel["hp"] < hp_target and not intel["local_agents"]:
                heal_item = self._find_best_heal_item(intel["inventory"])
                if heal_item:
                    label = "FINAL" if is_final else "ENDGAME"
                    return (
                        {"type": "use_item", "itemId": heal_item["id"]},
                        f"{label} HEAL Day {day}: HP {intel['hp']:.0f}→{hp_target}",
                        free_actions
                    )

        # ── P2: LOW HP — heal if available ───────────────────────────────────
        hp_threshold = weights.get("heal_threshold", 0.30) * 100
        if intel["hp"] < hp_threshold:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                return (
                    {"type": "use_item", "itemId": heal_item["id"]},
                    f"Low HP ({intel['hp']:.0f}) - healing with {heal_item.get('typeId')}",
                    free_actions
                )

        # ── P3: DEATH ZONE WARNING ────────────────────────────────────────────
        if dz_level == 1:
            target = self.analyzer.safest_escape_region(intel, self.known_dz_regions)
            if target:
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "move", "regionId": target},
                    f"Death zone incoming! Moving to {target[:8]}",
                    free_actions
                )

        # ── P4: EP MANAGEMENT ────────────────────────────────────────────────
        ep_pct         = intel["ep"] / max(intel["max_ep"], 1)
        rest_threshold = weights.get("rest_threshold", 0.30)

        if intel["ep"] < self.analyzer.ep_min_attack:
            if not intel["local_agents"]:
                return (
                    {"type": "rest"},
                    f"EP too low ({intel['ep']}) to attack - resting",
                    free_actions
                )
            else:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    return (
                        {"type": "move", "regionId": escape},
                        f"Low EP ({intel['ep']}) with enemy - fleeing",
                        free_actions
                    )

        if ep_pct < rest_threshold and not intel["local_agents"]:
            return (
                {"type": "rest"},
                f"Resting to recover EP ({intel['ep']}/{intel['max_ep']})",
                free_actions
            )

        # ── P5: PvP COMBAT ───────────────────────────────────────────────────
        if intel["local_agents"] and intel["ep"] >= self.analyzer.ep_min_attack:
            atk_count = self.attack_count_per_region.get(intel["region_id"], 0)
            if atk_count >= self.MAX_ATTACKS_NO_KILL:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    self.attack_count_per_region[intel["region_id"]] = 0
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "move", "regionId": escape},
                        f"FUTILE: {atk_count} attacks no kill → reposition",
                        free_actions
                    )

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
                # Only flee if clearly outmatched — not just below threshold
                # [FIX-1] flee_threshold much lower than attack_threshold
                flee_threshold = max(0.35, effective_threshold - 0.18)
                if win_prob < flee_threshold:
                    escape = self.analyzer.safest_escape_region(intel)
                    if escape:
                        self.last_action_type = "move"
                        self.last_region_id_for_facility = intel["region_id"]
                        return (
                            {"type": "move", "regionId": escape},
                            f"win_prob={win_prob:.0%} clearly too low → evade",
                            free_actions
                        )

        # ── P6: MONSTER FARMING ── [FIX-3] runs EVERY phase now ─────────────
        if intel["local_monsters"] and intel["ep"] >= self.analyzer.ep_min_attack:
            atk_count_m = self.attack_count_per_region.get(intel["region_id"], 0)
            if atk_count_m < self.MAX_ATTACKS_NO_KILL * 2:
                target, win_prob, reasoning = self._evaluate_monster_targets(
                    intel, intel["local_monsters"], phase
                )
                if target:
                    self.last_action_type = "attack"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "attack", "targetId": target["id"], "targetType": "monster"},
                        reasoning, free_actions
                    )

        # ── P7: FACILITIES ───────────────────────────────────────────────────
        facility = self.analyzer.get_useful_facility(intel)
        if facility and weights.get("use_facility", 0.7) > 0.5:
            if intel["region_id"] not in self.dangerous_facilities:
                self.last_action_type = "interact"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "interact", "interactableId": facility["id"]},
                    f"Using facility: {facility.get('type')} in {intel['region_name']}",
                    free_actions
                )

        # ── P8: ENERGY DRINK if EP low ───────────────────────────────────────
        if intel["ep"] < 5:
            drink = next(
                (i for i in intel["inventory"]
                 if "energy" in i.get("typeId", "").lower()), None
            )
            if drink:
                return (
                    {"type": "use_item", "itemId": drink["id"]},
                    f"Energy Drink to recover EP ({intel['ep']})",
                    free_actions
                )

        # ── P9: EXPLORE / MOVE ───────────────────────────────────────────────
        has_combat = bool(intel["local_agents"] or intel["local_monsters"])

        # [FIX-4] Force move when stuck — break infinite explore loop
        if self.stuck_counter > 2:
            self.stuck_counter = 0
            target_region = self._choose_move_target(intel)
            if target_region:
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "move", "regionId": target_region},
                    f"Stuck {self.stuck_counter}+ turns → force move",
                    free_actions
                )

        # Explore unvisited regions only if no combat nearby
        if intel["region_id"] not in self.explored_regions and not has_combat:
            self.explored_regions.add(intel["region_id"])
            self.last_action_type = "explore"
            self.last_region_id_for_facility = intel["region_id"]
            return (
                {"type": "explore"},
                f"Exploring {intel['region_name']} for items/enemies",
                free_actions
            )

        # Move toward unvisited / valuable region
        target_region = self._choose_move_target(intel)
        if target_region:
            self.last_action_type = "move"
            self.last_region_id_for_facility = intel["region_id"]
            return (
                {"type": "move", "regionId": target_region},
                f"Moving to {target_region[:8]} (stuck={self.stuck_counter})",
                free_actions
            )

        # Fallback explore
        self.last_action_type = "explore"
        self.last_region_id_for_facility = intel["region_id"]
        return (
            {"type": "explore"},
            f"Fallback explore {intel['region_name']} (EP:{intel['ep']}, HP:{intel['hp']})",
            free_actions
        )

    # -------------------------------------------------------------------------
    # FREE ACTION PLANNER
    # -------------------------------------------------------------------------

    def _decide_free_actions(self, intel: Dict, weights: Dict) -> List[Dict]:
        free = []

        if not intel["inventory_full"] and intel["local_items"]:
            for entry in intel["local_items"]:
                item = entry.get("item", {})
                if item.get("category") == "currency":
                    free.append({"type": "pickup", "itemId": item["id"]})

            if len(intel["inventory"]) < 9:
                best_entry = self.analyzer.get_best_item_on_ground(
                    intel["local_items"], intel["inventory"]
                )
                if best_entry:
                    item = best_entry.get("item", {})
                    if item.get("category") != "currency":
                        free.append({"type": "pickup", "itemId": item["id"]})

        best_weapon = self.analyzer.best_weapon_in_inventory(intel["inventory"])
        if best_weapon and self.analyzer.should_upgrade_weapon(
            intel["equipped_weapon"], best_weapon
        ):
            free.append({"type": "equip", "itemId": best_weapon["id"]})

        for msg in intel["unread_messages"][:2]:
            sender_id = msg.get("senderId")
            msg_type  = msg.get("type", "public")
            content   = msg.get("content", "").lower()
            if sender_id and "enemy" not in content and "kill" not in content:
                if msg_type == "private" or msg.get("channel") == "private":
                    free.append({
                        "type"    : "whisper",
                        "targetId": sender_id,
                        "message" : "Acknowledged. Open to alliance."
                    })

        return free

    # -------------------------------------------------------------------------
    # COMBAT TARGET EVALUATION
    # -------------------------------------------------------------------------

    def _evaluate_combat_targets(
        self, intel: Dict, targets: List[Dict], threshold: float
    ) -> Tuple[Optional[Dict], float, str]:
        my_stats    = self._my_combat_stats(intel)
        best_target = None
        best_score  = -1.0
        best_prob   = 0.0

        for target in targets:
            enemy_stats = self._enemy_combat_stats(target)
            profile     = self.memory.get_enemy_profile(target.get("id", ""))

            if profile:
                hist_wins   = profile.get("wins_against", 0)
                hist_losses = profile.get("losses_to", 0)
                total       = hist_wins + hist_losses
                if total > 0:
                    win_prob = (self.learning.predict_combat(my_stats, enemy_stats) * 0.7 +
                                (hist_wins / total) * 0.3)
                else:
                    win_prob = self.learning.predict_combat(my_stats, enemy_stats)
            else:
                win_prob = self.learning.predict_combat(my_stats, enemy_stats)

            target_hp      = target.get("hp", 100)
            weakness_bonus = max(0, (100 - target_hp) / 200)
            score          = win_prob + weakness_bonus

            if score > best_score:
                best_score  = score
                best_target = target
                best_prob   = win_prob

        if best_target is None:
            return None, 0.0, "No visible target"

        # [FIX-5] Kill confirm threshold raised 25→40
        if best_target.get("hp", 100) <= 40 and intel.get("ep", 0) >= 2:
            return (
                best_target, best_prob,
                f"Kill confirm {best_target.get('name','?')} HP≤40"
            )

        if best_prob >= threshold:
            return (
                best_target, best_prob,
                f"ATTACKING {best_target.get('name','?')} "
                f"win_prob={best_prob:.0%} threshold={threshold:.0%}"
            )

        return None, best_prob, (
            f"Best win_prob={best_prob:.0%} < threshold={threshold:.0%}"
        )

    def _evaluate_monster_targets(
        self, intel: Dict, monsters: List[Dict], phase: str = "early"
    ) -> Tuple[Optional[Dict], float, str]:
        """
        [FIX-2] Dynamic threshold per phase:
          early: 0.42 — must farm to get weapons, be aggressive
          mid  : 0.52 — normal
          late : 0.60 — conservative, preserve HP for ranking
        """
        # [FIX-2] Dynamic floor instead of hardcoded 0.60
        threshold = {"early": 0.42, "mid": 0.52, "late": 0.60}.get(phase, 0.42)

        # Sort by HP ascending — kill weakest first (wolf before bear)
        sorted_monsters = sorted(monsters, key=lambda m: m.get("hp", 99))

        for monster in sorted_monsters:
            win_prob = self.analyzer.monster_win_probability(intel, monster)
            if win_prob >= threshold:
                return (
                    monster, win_prob,
                    f"HUNTING {monster.get('type','monster')} "
                    f"win_prob={win_prob:.0%} (floor={threshold:.0%})"
                )

        return None, 0.0, f"Monsters below threshold={threshold:.0%}"

    # -------------------------------------------------------------------------
    # MOVEMENT
    # -------------------------------------------------------------------------

    def _choose_move_target(self, intel: Dict) -> Optional[str]:
        connections = intel["connections"]
        if not connections:
            return None

        pending_dz = set(str(x) for x in intel.get("pending_death_zones", []))
        all_dz     = self.known_dz_regions | pending_dz
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                all_dz.add(rid)

        def region_score(region_id: str) -> float:
            score = 0.0
            if region_id not in self.explored_regions:
                score += 3.0
            if region_id in all_dz:
                score -= 100.0
            if region_id in self.dangerous_facilities:
                score -= 5.0
            return score

        truly_safe    = [c for c in connections if c not in all_dz]
        safe_conns    = truly_safe if truly_safe else connections
        best          = max(safe_conns, key=region_score)
        self.last_action_type = "move"
        self.last_region_id_for_facility = intel["region_id"]
        return best

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_phase(self) -> str:
        if self.turn_number < PHASE_MID_START:
            return "early"
        elif self.turn_number < PHASE_LATE_START:
            return "mid"
        return "late"

    def _find_best_heal_item(self, inventory: List[Dict]) -> Optional[Dict]:
        heal_items = [
            i for i in inventory
            if i.get("category") == "recovery"
            and "energy" not in i.get("typeId", "").lower()
        ]
        if not heal_items:
            return None
        priority = {"medkit": 3, "bandage": 2, "emergency_food": 1}
        return max(
            heal_items,
            key=lambda item: max(
                (s for k, s in priority.items()
                 if k in item.get("typeId", "").lower()),
                default=0
            )
        )

    def _my_combat_stats(self, intel: Dict) -> Dict:
        weapon_bonus, weapon_range = self.analyzer.get_equipped_bonus(
            intel["equipped_weapon"]
        )
        heal_stats = self.analyzer.inventory_heal_stats(intel.get("inventory", []))
        return {
            "hp"           : intel["hp"],
            "ep"           : intel["ep"],
            "atk"          : intel["atk"],
            "def"          : intel["def"],
            "weapon_bonus" : weapon_bonus,
            "weapon_range" : weapon_range,
            "heal_hp_total": heal_stats["heal_hp_total"],
            "heal_ep_total": heal_stats["heal_ep_total"],
            "heal_count"   : heal_stats["heal_count"],
            "best_heal_hp" : heal_stats["best_heal_hp"],
            "effective_hp" : intel["hp"] + heal_stats["heal_hp_total"],
            "inventory"    : intel.get("inventory", []),
        }

    def _enemy_combat_stats(self, target: Dict) -> Dict:
        weapon = target.get("equippedWeapon") or {}
        return {
            "hp"          : target.get("hp", 50),
            "atk"         : target.get("atk", 10),
            "def"         : target.get("def", 5),
            "weapon_bonus": weapon.get("atkBonus", 0),
        }

    def reset_for_new_game(self):
        self.turn_number      = 0
        self.explored_regions  = set()
        self.last_region_id    = None
        self.stuck_counter     = 0
        self.known_dz_regions  = set()
        self.attack_count_per_region = {}
        self.kills_at_last_check     = 0
        self.dangerous_facilities    = set()
        self.last_turn_hp            = 100.0
        self.last_action_type        = ""
        self.last_region_id_for_facility = ""
        logger.info("Strategy engine reset for new game")
