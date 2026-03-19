"""
==============================================================================
MOLTY ROYALE BOT - STRATEGY DECISION ENGINE
==============================================================================
Priority system (highest → lowest):
  P0: Escape death zone (emergency)
  P1: Heal if critical HP
  P2: Endgame HP management (Day 11+)
  P3: Low HP heal
  P4: Death zone warning (preemptive)
  P5: EP management
  P6: PvP combat
  P7: Monster farming
  P8: Facilities
  P9: Energy drink
  P10: Explore / Move

FREE ACTIONS (run EVERY turn, 0 EP, no cooldown):
  - Pickup ALL $Moltz/currency (always, even inventory full)
  - Pickup best item if space
  - Equip best weapon

REWARD-MAXIMIZATION FIXES:
  [FIX-R1] $Moltz pickup: currency picked up ALWAYS as free action,
           even when inventory_full. Inventory limit does NOT apply
           to $Moltz collection — rules say pickup is FREE and has
           no cooldown. Separate currency pickup from item pickup.
  [FIX-R2] Wolf is 1-hit kill with fist (ATK10 vs HP5 DEF1 = 9.5dmg).
           Wolf threshold hardcoded to 0.0 — always fight wolves.
           Bear threshold 0.35, Bandit threshold 0.50.
  [FIX-R3] Dead agent loot: after a kill, aggressively scan and
           pickup all ground items in that region (they drop full inventory).
  [FIX-R4] Thought content made informative to attract sponsors:
           "HP:85 EP:8 K:2 | Hunting wolf for $Moltz" etc.
  [FIX-R5] MIN_FREE_INVENTORY_SLOTS raised to 2 for sponsor deliveries
           (sponsors fail if inventory full — keep buffer).
  [FIX-R6] Supply cache interact priority raised — free $Moltz + items.

  STRATEGY FIXES (from previous sessions):
  [FIX-1] Early phase threshold lowered (was raised +0.05, now -0.10)
  [FIX-2] Monster threshold dynamic (0.0 wolf / 0.35 bear / 0.50 bandit)
  [FIX-3] Monster eval runs every phase (not just mid/late)
  [FIX-4] Stuck force-move after 2+ turns
  [FIX-5] Kill confirm HP raised 25→40
"""

import logging
from typing import Dict, Optional, Tuple, List

from .analyzer import StateAnalyzer, WEAPON_PRIORITY

logger = logging.getLogger("MoltyBot.Strategy")

TOTAL_TURNS       = 56
TURNS_PER_DAY     = 4
PHASE_MID_START   = 17
PHASE_LATE_START  = 41
PHASE_FINAL_START = 49

HP_ENDGAME_TARGET = 100
HP_LATE_TARGET    = 80

# [FIX-R2] Per-monster thresholds — wolf is 1-hit kill, always fight it
MONSTER_THRESHOLDS = {
    "wolf"  : 0.00,   # 1-hit kill with fist (ATK10 - DEF0.5 = 9.5 > HP5)
    "bear"  : 0.35,   # 2 hits needed, take ~14 HP — fight if reasonable
    "bandit": 0.50,   # 3 hits, tank ~37 HP — more selective
}
MONSTER_THRESHOLD_DEFAULT = 0.40

# [FIX-R5] Keep 2 inventory slots free for sponsor deliveries
MIN_FREE_INVENTORY_SLOTS = 2


class StrategyEngine:

    def __init__(self, analyzer: StateAnalyzer, memory, learning_engine):
        self.analyzer  = analyzer
        self.memory    = memory
        self.learning  = learning_engine
        self.turn_number      = 0
        self.explored_regions = set()
        self.last_region_id   = None
        self.stuck_counter    = 0

        self.known_dz_regions: set    = set()
        self.attack_count_per_region: dict = {}
        self.kills_at_last_check: int = 0
        self.MAX_ATTACKS_NO_KILL      = 4

        self.dangerous_facilities: set = set()
        self.last_turn_hp: float      = 100.0
        self.last_action_type: str    = ""
        self.last_region_id_for_facility: str = ""

        # [FIX-R3] Track regions where we just got a kill (loot aggressively)
        self.recent_kill_regions: set = set()

    # -------------------------------------------------------------------------
    # MAIN DECISION METHOD
    # -------------------------------------------------------------------------

    def decide(self, intel: Dict) -> Tuple[Dict, str, List[Dict]]:
        self.turn_number += 1
        weights          = self.memory.action_weights
        attack_threshold = self.memory.attack_threshold

        # Stuck detection
        if intel["region_id"] == self.last_region_id:
            self.stuck_counter += 1
        else:
            self.stuck_counter    = 0
            self.last_region_id   = intel["region_id"]
        self.explored_regions.add(intel["region_id"])

        day        = ((self.turn_number - 1) // TURNS_PER_DAY) + 1
        turns_left = max(0, TOTAL_TURNS - self.turn_number)
        phase      = self._get_phase()
        is_late    = self.turn_number >= PHASE_LATE_START
        is_final   = self.turn_number >= PHASE_FINAL_START

        # [FIX-1] Early threshold LOWERED — bot needs kills to get weapons
        if is_final:
            effective_threshold = max(0.40, attack_threshold - 0.20)
        elif is_late:
            effective_threshold = max(0.45, attack_threshold - 0.15)
        elif phase == "late":
            effective_threshold = max(0.48, attack_threshold - 0.10)
        elif phase == "mid":
            effective_threshold = attack_threshold
        else:
            effective_threshold = max(0.45, attack_threshold - 0.10)

        # Log phase transition once
        _pkey = f"{phase}_{is_late}_{is_final}"
        if not hasattr(self, "_logged_phase") or self._logged_phase != _pkey:
            self._logged_phase = _pkey
            label = "FINAL PUSH" if is_final else ("ENDGAME" if is_late else f"Phase {phase.upper()}")
            logger.info(f"{label} Day {day} T{self.turn_number} | {turns_left}t left | threshold={effective_threshold:.0%}")

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
            logger.warning(f"TRAP! Facility di {intel['region_name']} merusak HP ({self.last_turn_hp:.0f}→{hp_now:.0f})")
        self.last_turn_hp = hp_now

        # Attack futility + kill tracking
        current_kills = intel.get("kills", 0)
        if current_kills > self.kills_at_last_check:
            self.attack_count_per_region[intel["region_id"]] = 0
            self.kills_at_last_check = current_kills
            # [FIX-R3] Mark this region for aggressive looting
            self.recent_kill_regions.add(intel["region_id"])
            logger.info(f"KILL confirmed! Loot region {intel['region_name']} aggressively.")
        else:
            self.recent_kill_regions.discard(intel["region_id"])

        if self.last_action_type == "attack":
            reg = intel["region_id"]
            self.attack_count_per_region[reg] = self.attack_count_per_region.get(reg, 0) + 1

        # ── FREE ACTIONS (runs EVERY turn before main action) ────────────────
        free_actions = self._decide_free_actions(intel, weights)

        # ── P0: DEATH ZONE EMERGENCY ──────────────────────────────────────────
        dz_level = self.analyzer.death_zone_danger_level(intel)
        if dz_level >= 2:
            target = self.analyzer.safest_escape_region(intel, self.known_dz_regions)
            if target:
                logger.warning(f"⚡ DZ ESCAPE! {intel['region_name']} → {target[:8]}")
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "move", "regionId": target},
                    f"EMERGENCY DZ escape (HP:{intel['hp']:.0f})",
                    free_actions
                )

        # ── P1: CRITICAL HEAL ────────────────────────────────────────────────
        if intel["hp"] <= self.analyzer.hp_critical:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                return (
                    {"type": "use_item", "itemId": heal_item["id"]},
                    f"CRITICAL HP ({intel['hp']:.0f}) using {heal_item.get('typeId')}",
                    free_actions
                )
            if intel["local_agents"] or intel["local_monsters"]:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    self.last_action_type = "move"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "move", "regionId": escape},
                        f"Critical HP ({intel['hp']:.0f}) + enemies → flee",
                        free_actions
                    )
            self.last_action_type = "rest"
            return {"type": "rest"}, f"Critical HP ({intel['hp']:.0f}) no heals → REST", free_actions

        # ── P2: ENDGAME HP (Day 11+) ──────────────────────────────────────────
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

        # ── P3: LOW HP HEAL ───────────────────────────────────────────────────
        hp_threshold = weights.get("heal_threshold", 0.30) * 100
        if intel["hp"] < hp_threshold:
            heal_item = self._find_best_heal_item(intel["inventory"])
            if heal_item:
                return (
                    {"type": "use_item", "itemId": heal_item["id"]},
                    f"Low HP ({intel['hp']:.0f}) healing with {heal_item.get('typeId')}",
                    free_actions
                )

        # ── P4: DEATH ZONE WARNING ────────────────────────────────────────────
        if dz_level == 1:
            target = self.analyzer.safest_escape_region(intel, self.known_dz_regions)
            if target:
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "move", "regionId": target},
                    f"DZ incoming → {target[:8]}",
                    free_actions
                )

        # ── P5: EP MANAGEMENT ────────────────────────────────────────────────
        ep_pct         = intel["ep"] / max(intel["max_ep"], 1)
        rest_threshold = weights.get("rest_threshold", 0.30)

        if intel["ep"] < self.analyzer.ep_min_attack:
            if not intel["local_agents"]:
                return {"type": "rest"}, f"EP too low ({intel['ep']}) → rest", free_actions
            else:
                escape = self.analyzer.safest_escape_region(intel)
                if escape:
                    return (
                        {"type": "move", "regionId": escape},
                        f"Low EP ({intel['ep']}) with enemy → flee",
                        free_actions
                    )

        if ep_pct < rest_threshold and not intel["local_agents"]:
            return {"type": "rest"}, f"Banking EP ({intel['ep']}/{intel['max_ep']})", free_actions

        # ── P6: PvP COMBAT ───────────────────────────────────────────────────
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
                flee_threshold = max(0.35, effective_threshold - 0.18)
                if win_prob < flee_threshold:
                    escape = self.analyzer.safest_escape_region(intel)
                    if escape:
                        self.last_action_type = "move"
                        self.last_region_id_for_facility = intel["region_id"]
                        return (
                            {"type": "move", "regionId": escape},
                            f"PvP win_prob={win_prob:.0%} too low → evade",
                            free_actions
                        )

        # ── P7: MONSTER FARMING ── [FIX-R2] Per-type thresholds ──────────────
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

        # ── P8: FACILITIES ── [FIX-R6] Supply cache prioritized ──────────────
        facility = self.analyzer.get_useful_facility(intel)
        if facility and weights.get("use_facility", 0.7) > 0.5:
            if intel["region_id"] not in self.dangerous_facilities:
                ftype = (facility.get("type") or "").lower()
                # Supply cache = free loot, always use early
                is_supply = "supply" in ftype
                is_medical = "medical" in ftype and intel["hp"] < 85
                is_watch   = "watchtower" in ftype
                if is_supply or is_medical or is_watch:
                    self.last_action_type = "interact"
                    self.last_region_id_for_facility = intel["region_id"]
                    return (
                        {"type": "interact", "interactableId": facility["id"]},
                        f"Facility: {facility.get('type')} in {intel['region_name']}",
                        free_actions
                    )

        # ── P9: ENERGY DRINK ─────────────────────────────────────────────────
        if intel["ep"] < 5:
            drink = next(
                (i for i in intel["inventory"] if "energy" in i.get("typeId", "").lower()),
                None
            )
            if drink:
                return (
                    {"type": "use_item", "itemId": drink["id"]},
                    f"Energy Drink → recover EP ({intel['ep']})",
                    free_actions
                )

        # ── P10: EXPLORE / MOVE ───────────────────────────────────────────────
        has_combat = bool(intel["local_agents"] or intel["local_monsters"])

        # [FIX-4] Force move when stuck
        if self.stuck_counter > 2:
            self.stuck_counter = 0
            target_region = self._choose_move_target(intel)
            if target_region:
                self.last_action_type = "move"
                self.last_region_id_for_facility = intel["region_id"]
                return (
                    {"type": "move", "regionId": target_region},
                    f"Stuck → force move to {target_region[:8]}",
                    free_actions
                )

        # Explore unvisited region if no combat
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
                f"Moving to {target_region[:8]}",
                free_actions
            )

        # Fallback explore
        self.last_action_type = "explore"
        self.last_region_id_for_facility = intel["region_id"]
        return (
            {"type": "explore"},
            f"Fallback explore {intel['region_name']} (EP:{intel['ep']} HP:{intel['hp']:.0f})",
            free_actions
        )

    # -------------------------------------------------------------------------
    # FREE ACTIONS — runs EVERY turn, 0 EP, no cooldown
    # -------------------------------------------------------------------------

    def _decide_free_actions(self, intel: Dict, weights: Dict) -> List[Dict]:
        """
        [FIX-R1] CRITICAL: $Moltz/currency pickup is ALWAYS first priority,
        even when inventory is full. Rules: pickup is Group 2 (free, no CD).
        Inventory limit does not apply to currency collection.

        [FIX-R3] After a kill, pickup ALL items (dead agent dropped full inventory).
        """
        free = []

        # ── 1. ALWAYS pickup currency ($Moltz) — inventory full doesn't matter ──
        if intel["local_items"]:
            for entry in intel["local_items"]:
                item = entry.get("item", {})
                if item.get("category") == "currency":
                    item_id = item.get("id")
                    if item_id:
                        free.append({"type": "pickup", "itemId": item_id})
                        logger.debug(f"FREE: Pickup $Moltz {item_id[:8]}")

        # ── 2. Pickup non-currency items if inventory has space ──────────────
        inv_count  = len(intel.get("inventory", []))
        max_pickup = 10 - MIN_FREE_INVENTORY_SLOTS  # keep 2 slots free for sponsors

        if intel["local_items"] and inv_count < max_pickup:
            # [FIX-R3] After a kill in this region, pickup EVERYTHING
            is_loot_region = intel["region_id"] in self.recent_kill_regions
            if is_loot_region:
                # Grab as many items as possible (up to max_pickup)
                for entry in intel["local_items"]:
                    item = entry.get("item", {})
                    if item.get("category") != "currency" and item.get("id"):
                        if inv_count < max_pickup:
                            free.append({"type": "pickup", "itemId": item["id"]})
                            inv_count += 1
                            logger.debug(f"FREE: Loot pickup {item.get('typeId')} after kill")
            else:
                # Normal: pickup best item
                best_entry = self.analyzer.get_best_item_on_ground(
                    intel["local_items"], intel.get("inventory", [])
                )
                if best_entry:
                    item = best_entry.get("item", {})
                    if item.get("category") != "currency" and item.get("id"):
                        free.append({"type": "pickup", "itemId": item["id"]})

        # ── 3. Auto-equip best weapon ────────────────────────────────────────
        best_weapon = self.analyzer.best_weapon_in_inventory(intel.get("inventory", []))
        if best_weapon and self.analyzer.should_upgrade_weapon(
            intel.get("equipped_weapon"), best_weapon
        ):
            free.append({"type": "equip", "itemId": best_weapon["id"]})
            logger.debug(f"FREE: Equip {best_weapon.get('typeId')}")

        # ── 4. Respond to whispers (alliance building) ───────────────────────
        for msg in intel.get("unread_messages", [])[:2]:
            sender_id = msg.get("senderId")
            msg_type  = msg.get("type", "public")
            content   = msg.get("content", "").lower()
            if sender_id and "kill" not in content and "enemy" not in content:
                if msg_type == "private" or msg.get("channel") == "private":
                    free.append({
                        "type"    : "whisper",
                        "targetId": sender_id,
                        "message" : "Acknowledged. Open to truce."
                    })

        return free

    # -------------------------------------------------------------------------
    # COMBAT EVALUATION
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

        # [FIX-5] Kill confirm threshold 25→40
        if best_target.get("hp", 100) <= 40 and intel.get("ep", 0) >= 2:
            return (
                best_target, best_prob,
                f"Kill confirm {best_target.get('name','?')} HP≤40 → loot incoming"
            )

        if best_prob >= threshold:
            return (
                best_target, best_prob,
                f"ATTACK {best_target.get('name','?')} win_prob={best_prob:.0%}"
            )

        return None, best_prob, f"PvP win_prob={best_prob:.0%} < threshold={threshold:.0%}"

    def _evaluate_monster_targets(
        self, intel: Dict, monsters: List[Dict], phase: str = "early"
    ) -> Tuple[Optional[Dict], float, str]:
        """
        [FIX-R2] Per-monster thresholds:
          Wolf   → 0.00 (1-hit kill with fist, ALWAYS fight)
          Bear   → 0.35 (2 hits, acceptable risk)
          Bandit → 0.50 (3 hits, selective)
        """
        # Sort by easiest first: wolf < bear < bandit
        type_order = {"wolf": 0, "bear": 1, "bandit": 2}
        sorted_monsters = sorted(
            monsters,
            key=lambda m: (type_order.get((m.get("type") or "wolf").lower(), 1), m.get("hp", 99))
        )

        for monster in sorted_monsters:
            mtype     = (monster.get("type") or "wolf").lower()
            threshold = MONSTER_THRESHOLDS.get(mtype, MONSTER_THRESHOLD_DEFAULT)

            win_prob  = self.analyzer.monster_win_probability(intel, monster)

            if win_prob >= threshold:
                hp_left_after = max(0, intel["hp"] - self._estimate_damage_taken(intel, monster))
                return (
                    monster, win_prob,
                    f"HUNT {mtype} win_prob={win_prob:.0%} "
                    f"(floor={threshold:.0%}) → $Moltz drop incoming"
                )

        return None, 0.0, "All monsters below threshold"

    def _estimate_damage_taken(self, intel: Dict, monster: Dict) -> float:
        """Quick estimate of HP we'll lose fighting this monster."""
        monster_stats = {
            "wolf"  : {"atk": 15, "def": 1},
            "bear"  : {"atk": 20, "def": 2},
            "bandit": {"atk": 25, "def": 3},
        }
        mtype    = (monster.get("type") or "wolf").lower()
        stats    = monster_stats.get(mtype, {"atk": 18, "def": 2})
        m_hp     = monster.get("hp", 10)
        # Damage we deal per hit
        wpn, _   = self.analyzer.get_equipped_bonus(intel.get("equipped_weapon"))
        my_dmg   = max(1, intel["atk"] + wpn - stats["def"] * 0.5)
        hits_needed = max(1, int(m_hp / my_dmg) + (1 if m_hp % my_dmg else 0))
        their_dmg   = max(1, stats["atk"] - intel["def"] * 0.5)
        # They attack hits_needed - 1 times (we kill them on last hit)
        return their_dmg * max(0, hits_needed - 1)

    # -------------------------------------------------------------------------
    # MOVEMENT
    # -------------------------------------------------------------------------

    def _choose_move_target(self, intel: Dict) -> Optional[str]:
        connections = intel.get("connections") or []
        if not connections:
            return None

        pending_dz = set(str(x) for x in intel.get("pending_death_zones", []))
        all_dz     = self.known_dz_regions | pending_dz
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                all_dz.add(rid)

        phase = self._get_phase()

        def region_score(rid: str) -> float:
            score = 0.0
            if rid not in self.explored_regions:
                score += 3.0
            if rid in all_dz:
                score -= 100.0
            if rid in self.dangerous_facilities:
                score -= 5.0
            # Prefer hills (vision) in mid/late for better intel
            if phase in ("mid", "late"):
                score += 0.5  # slight bias toward unexplored
            return score

        truly_safe = [c for c in connections if c not in all_dz]
        safe_conns = truly_safe if truly_safe else connections
        best = max(safe_conns, key=region_score)
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
                (s for k, s in priority.items() if k in item.get("typeId", "").lower()),
                default=0
            )
        )

    def _my_combat_stats(self, intel: Dict) -> Dict:
        weapon_bonus, weapon_range = self.analyzer.get_equipped_bonus(
            intel.get("equipped_weapon")
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

    def build_thought(self, intel: Dict, reasoning: str) -> Dict:
        """
        [FIX-R4] Informative thoughts attract sponsors.
        Rules: thoughts revealed after ~1 minute. Strategic + status info
        increases chance spectators send medkits, bandages, etc.
        """
        kills  = self.memory._current_game.get("kills", 0) if self.memory._current_game else 0
        weapon = ""
        if intel.get("equipped_weapon"):
            weapon = intel["equipped_weapon"].get("typeId", "fist")
        phase  = self._get_phase()
        status = (
            f"HP:{intel['hp']:.0f} EP:{intel['ep']} K:{kills} "
            f"wpn:{weapon or 'fist'} phase:{phase}"
        )
        return {
            "reasoning"    : f"{status} | {reasoning[:80]}",
            "plannedAction": "",  # filled by caller
        }

    def reset_for_new_game(self):
        self.turn_number             = 0
        self.explored_regions         = set()
        self.last_region_id           = None
        self.stuck_counter            = 0
        self.known_dz_regions         = set()
        self.attack_count_per_region  = {}
        self.kills_at_last_check      = 0
        self.recent_kill_regions      = set()
        self.dangerous_facilities     = set()
        self.last_turn_hp             = 100.0
        self.last_action_type         = ""
        self.last_region_id_for_facility = ""
        logger.info("Strategy engine reset for new game")
