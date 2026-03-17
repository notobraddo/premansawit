"""
==============================================================================
MOLTY ROYALE BOT - GAME STATE ANALYZER
==============================================================================
Parses and analyzes game state. Calculates combat probabilities,
weapon rankings, death zone risk, and threat assessments.
"""

from typing import Optional, List, Dict, Tuple
import logging

logger = logging.getLogger("MoltyBot.Analyzer")

# =============================================================================
# WEAPON PRIORITY TABLE (ATK bonus → priority score)
# =============================================================================
WEAPON_PRIORITY = {
    "katana": 100,   # +21 ATK, melee
    "sniper": 95,    # +17 ATK, range 2
    "sword":  70,    # +8 ATK, melee
    "pistol": 65,    # +6 ATK, range 1
    "knife":  40,    # +5 ATK, melee
    "bow":    35,    # +3 ATK, range 1
    "fist":   0,     # default
}

WEAPON_BONUS = {
    "katana": 21, "sniper": 17, "sword": 8,
    "pistol": 6, "knife": 5, "bow": 3, "fist": 0
}

WEAPON_RANGE = {
    "katana": 0, "sword": 0, "knife": 0, "fist": 0,
    "pistol": 1, "bow": 1, "sniper": 2
}

# Recovery item HP/EP values (dari Game_Guide.txt)
RECOVERY_VALUES = {
    "medkit":          {"hp": 50, "ep": 0},
    "bandage":         {"hp": 30, "ep": 0},
    "emergency_food":  {"hp": 20, "ep": 0},
    "energy_drink":    {"hp": 0,  "ep": 5},
}
# Alias flat maps untuk lookup cepat
ITEM_HP_RESTORE = {k: v["hp"] for k, v in RECOVERY_VALUES.items()}
ITEM_EP_RESTORE = {k: v["ep"] for k, v in RECOVERY_VALUES.items() if v["ep"] > 0}


class StateAnalyzer:
    """Analyzes raw game state and produces structured intelligence."""

    def __init__(self, hp_critical: int = 25, hp_low: int = 50,
                 ep_min_attack: int = 2, ep_rest_threshold: int = 3):
        self.hp_critical = hp_critical
        self.hp_low = hp_low
        self.ep_min_attack = ep_min_attack
        self.ep_rest_threshold = ep_rest_threshold

    # -------------------------------------------------------------------------
    # CORE STATE PARSING
    # -------------------------------------------------------------------------

    def parse(self, state: Dict) -> Dict:
        """
        Parse raw API state into structured intelligence report.
        Returns a dict with all relevant tactical information.
        """
        self_data = state.get("self", {})
        region = state.get("currentRegion", {})
        visible_agents = state.get("visibleAgents", []) or []
        visible_monsters = state.get("visibleMonsters", []) or []
        visible_items = state.get("visibleItems", []) or []
        messages = state.get("recentMessages", []) or []
        pending_dz_raw = state.get("pendingDeathzones", []) or []
        # API bisa return list-of-dict [{"regionId":"...", "turnsLeft":N}]
        # atau list-of-str ["region-id-1", ...] — normalize ke set of str
        pending_dz = []
        for item in pending_dz_raw:
            if isinstance(item, dict):
                rid = item.get("regionId") or item.get("id") or item.get("region_id")
                if rid:
                    pending_dz.append(rid)
            elif isinstance(item, str) and item:
                pending_dz.append(item)

        self_id = self_data.get("id", "")
        self_region_id = self_data.get("regionId", region.get("id", ""))

        # Filter to same-region targets
        local_agents = [a for a in visible_agents
                        if a.get("regionId") == self_region_id
                        and a.get("isAlive", False)
                        and a.get("id") != self_id]
        local_monsters = [m for m in visible_monsters
                          if m.get("regionId") == self_region_id]
        local_items = [i for i in visible_items
                       if i.get("regionId") == self_region_id]

        # Remote-range targets (range 1-2 weapons)
        remote_agents = [a for a in visible_agents
                         if a.get("regionId") != self_region_id
                         and a.get("isAlive", False)
                         and a.get("id") != self_id]

        inventory = self_data.get("inventory", []) or []
        equipped = self_data.get("equippedWeapon")

        # ── Visible regions: kumpulkan status DZ dari region yang terlihat
        visible_regions_raw = state.get("visibleRegions", []) or []
        # Map region_id → {name, is_death_zone} dari semua region terlihat
        region_status_map = {}
        for vr in visible_regions_raw:
            rid = vr.get("id") or vr.get("regionId")
            if rid:
                region_status_map[rid] = {
                    "name": vr.get("name", rid[:8]),
                    "is_dz": vr.get("isDeathZone", False),
                }
        # Juga: connections bisa berupa list of str ATAU list of dict
        raw_connections = region.get("connections", [])
        connections_ids = []
        connections_status = {}  # region_id -> is_dz
        for c in raw_connections:
            if isinstance(c, str):
                connections_ids.append(c)
                # Cek di visibleRegions
                if c in region_status_map:
                    connections_status[c] = region_status_map[c]["is_dz"]
            elif isinstance(c, dict):
                cid = c.get("id") or c.get("regionId", "")
                if cid:
                    connections_ids.append(cid)
                    connections_status[cid] = c.get("isDeathZone", False)

        return {
            # Self stats
            "self_id": self_id,
            "self_region_id": self_region_id,
            "hp": self_data.get("hp", 100),
            "max_hp": self_data.get("maxHp", 100),
            "ep": self_data.get("ep", 10),
            "max_ep": self_data.get("maxEp", 10),
            "atk": self_data.get("atk", 10),
            "def": self_data.get("def", 5),
            "vision": self_data.get("vision", 1),
            "is_alive": self_data.get("isAlive", True),
            "kills": self_data.get("kills", 0),

            # Region
            "region": region,
            "region_id": region.get("id", ""),
            "region_name": region.get("name", "unknown"),
            "is_death_zone": region.get("isDeathZone", False),
            "connections": connections_ids,
            "connections_status": connections_status,  # {region_id: is_dz}
            "terrain": region.get("terrain", "plains"),
            "weather": region.get("weather", "clear"),
            "interactables": region.get("interactables", []) or [],
            "pending_death_zones": pending_dz,

            # Combat targets
            "local_agents": local_agents,
            "local_monsters": local_monsters,
            "remote_agents": remote_agents,

            # Items
            "local_items": local_items,
            "inventory": inventory,
            "equipped_weapon": equipped,
            "inventory_full": len(inventory) >= 10,

            # Messages
            "messages": messages,
            "unread_messages": [m for m in messages
                                if m.get("senderId") != self_id],

            # Game status
            "game_status": state.get("gameStatus", "running"),
            "result": state.get("result"),

            # In-game time tracking (Day 1–14, Hour 0–24)
            # API fields: currentDay / gameDay / day / time / currentTime
            "game_day":  (state.get("currentDay")
                          or state.get("gameDay")
                          or state.get("day")
                          or 1),
            "game_hour": (state.get("currentHour")
                          or state.get("gameHour")
                          or state.get("hour")
                          or 0),
            "alive_count": state.get("aliveCount", state.get("aliveAgents", 99)),
        }

    # -------------------------------------------------------------------------
    # COMBAT CALCULATIONS
    # -------------------------------------------------------------------------

    def calc_damage(self, atk: int, weapon_bonus: int, target_def: int) -> int:
        """Calculate damage dealt: ATK + weapon_bonus - (DEF × 0.5), min 1."""
        return max(1, int(atk + weapon_bonus - (target_def * 0.5)))

    def get_equipped_bonus(self, equipped_weapon) -> Tuple[int, int]:
        """Returns (atk_bonus, range) for equipped weapon."""
        if not equipped_weapon:
            return 0, 0
        wtype = equipped_weapon.get("typeId", "fist").lower()
        for key in WEAPON_BONUS:
            if key in wtype:
                return WEAPON_BONUS[key], WEAPON_RANGE[key]
        return equipped_weapon.get("atkBonus", 0), 0

    def inventory_heal_stats(self, inventory: list) -> dict:
        """
        Hitung total HP dan EP yang bisa dipulihkan dari inventory.
        Digunakan untuk kalkulasi "effective HP" dalam combat.

        Returns:
          heal_hp_total    : total HP restore dari semua recovery item (kecuali energy_drink)
          heal_ep_total    : total EP restore dari energy drinks
          heal_count       : jumlah item healing (recovery category)
          best_heal_hp     : HP restore item terbaik yang dimiliki
          heal_turns_avail : berapa turn heal bisa dilakukan (tiap 1 EP)
          items            : list detail tiap heal item {typeId, hp, ep}
        """
        heal_hp_total = 0
        heal_ep_total = 0
        heal_count    = 0
        best_heal_hp  = 0
        items_detail  = []

        for item in inventory:
            tid = item.get("typeId", "").lower()
            cat = item.get("category", "")
            if cat != "recovery":
                continue
            hp_val = ITEM_HP_RESTORE.get(tid, 0)
            ep_val = ITEM_EP_RESTORE.get(tid, 0)
            if hp_val > 0 or ep_val > 0:
                heal_hp_total += hp_val
                heal_ep_total += ep_val
                heal_count    += 1
                if hp_val > best_heal_hp:
                    best_heal_hp = hp_val
                items_detail.append({
                    "id"    : item.get("id"),
                    "typeId": tid,
                    "hp"    : hp_val,
                    "ep"    : ep_val,
                })

        return {
            "heal_hp_total"    : heal_hp_total,
            "heal_ep_total"    : heal_ep_total,
            "heal_count"       : heal_count,
            "best_heal_hp"     : best_heal_hp,
            "heal_turns_avail" : heal_count,   # 1 EP per heal
            "items"            : items_detail,
        }

    def win_probability(self, intel: Dict, target: Dict) -> float:
        """
        Estimate probability of winning a fight against target.
        Uses damage-per-turn simulation accounting for HP, ATK, DEF.
        Returns float [0.0, 1.0].
        """
        my_atk = intel["atk"]
        my_def = intel["def"]
        my_hp  = intel["hp"]
        my_ep  = intel.get("ep", 10)
        weapon_bonus, _ = self.get_equipped_bonus(intel["equipped_weapon"])

        t_hp = target.get("hp", 50)
        t_atk = target.get("atk", 10)
        t_def = target.get("def", 5)
        t_weapon = target.get("equippedWeapon") or {}
        t_weapon_bonus = t_weapon.get("atkBonus", 0)

        my_damage    = self.calc_damage(my_atk, weapon_bonus, t_def)
        their_damage = max(1, self.calc_damage(t_atk, t_weapon_bonus, my_def))

        # ── Inventory heal stats ──────────────────────────────────
        # Kita bisa heal di tengah combat: setiap 1 EP = 1 use_item
        # Attack cost 2 EP, heal cost 1 EP
        # Jadi dari EP=8: bisa attack(2)+heal(1)+attack(2)+heal(1)+attack(2) = 3 attack + 2 heals
        heal_stats     = self.inventory_heal_stats(intel.get("inventory", []))
        heal_hp_avail  = heal_stats["heal_hp_total"]   # Total HP bisa dipulihkan
        heal_ep_avail  = heal_stats["heal_ep_total"]   # EP dari energy drink
        heal_count     = heal_stats["heal_count"]

        # Berapa heal yang bisa kita lakukan dalam combat ini?
        # Setiap attack=2EP, heal=1EP → dalam EP total kita bisa selipkan heal
        # Max heals pakai: 1 heal per 3 EP (attack(2) + heal(1) pola)
        max_heals_doable = min(heal_count, my_ep // 3)

        # Effective HP = HP sekarang + HP dari heals yang bisa kita pakai
        # Kita akan heal saat HP < 40% (ambang batas konservatif)
        heals_to_use   = max_heals_doable
        effective_my_hp = my_hp + sum(
            h["hp"] for h in heal_stats["items"][:heals_to_use]
        )
        # EP tambahan dari energy drink: bisa tambah lebih banyak attack
        effective_my_ep = my_ep + heal_ep_avail

        # ── Combat simulation dengan heal ────────────────────────
        # Simulasi turn-by-turn: kita attack → damage → heal jika perlu
        sim_my_hp    = float(my_hp)
        sim_enemy_hp = float(t_hp)
        sim_ep       = float(effective_my_ep)
        sim_heals    = list(heal_stats["items"][:])  # copy
        sim_wins     = False
        HEAL_THRESHOLD = 35.0  # Heal saat HP ≤ ini

        for _ in range(50):  # max 50 iterasi
            if sim_ep < 2:
                break
            # Kita serang
            sim_enemy_hp -= my_damage
            sim_ep       -= 2
            if sim_enemy_hp <= 0:
                sim_wins = True
                break
            # Musuh balas
            sim_my_hp -= their_damage
            if sim_my_hp <= 0:
                break
            # Heal jika perlu dan bisa
            if sim_my_hp <= HEAL_THRESHOLD and sim_heals and sim_ep >= 1:
                best_heal = max(sim_heals, key=lambda h: h["hp"])
                sim_heals.remove(best_heal)
                sim_my_hp = min(100.0, sim_my_hp + best_heal["hp"])
                sim_ep    -= 1

        # ── Base probability dari simulasi ────────────────────────
        if sim_wins:
            # Menang di simulasi → prob tinggi, tapi sesuaikan dengan margin HP sisa
            hp_margin = sim_my_hp / 100.0
            prob = min(0.95, 0.65 + hp_margin * 0.25)
        else:
            # Kalah di simulasi
            # Cek seberapa jauh kita bisa bertahan (% HP musuh sudah dikurangi)
            damage_dealt_ratio = max(0, (t_hp - sim_enemy_hp) / max(t_hp, 1))
            prob = max(0.05, damage_dealt_ratio * 0.45)

        # ── Bonus dari heal items (even if simulation shows loss) ──
        # Punya heal items memberikan "buffer" keamanan
        heal_buffer = min(0.10, heal_hp_avail / 200.0)  # max +10%
        prob += heal_buffer

        # ── Adjust for HP + effective HP ratio ────────────────────
        eff_hp_ratio = min(1.0, effective_my_hp / max(effective_my_hp + t_hp, 1))
        prob = prob * 0.75 + eff_hp_ratio * 0.25

        return round(min(0.95, max(0.05, prob)), 3)

    def monster_win_probability(self, intel: Dict, monster: Dict) -> float:
        """Estimate win probability against a monster."""
        monster_stats = {
            "wolf":   {"hp": 5,  "atk": 15, "def": 1},
            "bear":   {"hp": 15, "atk": 20, "def": 2},
            "bandit": {"hp": 25, "atk": 25, "def": 3},
        }
        mtype = monster.get("type", "wolf").lower()
        stats = monster_stats.get(mtype, {"hp": 20, "atk": 18, "def": 2})

        # Use actual HP if available
        stats["hp"] = monster.get("hp", stats["hp"])
        return self.win_probability(intel, {**stats, "equippedWeapon": None})

    # -------------------------------------------------------------------------
    # WEAPON ANALYSIS
    # -------------------------------------------------------------------------

    def best_weapon_in_inventory(self, inventory: List[Dict]) -> Optional[Dict]:
        """Return the best weapon item from inventory by priority score."""
        weapons = [i for i in inventory if i.get("category") == "weapon"]
        if not weapons:
            return None

        def score(w):
            wtype = w.get("typeId", "fist").lower()
            for name, pts in WEAPON_PRIORITY.items():
                if name in wtype:
                    return pts
            return w.get("atkBonus", 0)

        return max(weapons, key=score)

    def should_upgrade_weapon(self, equipped: Optional[Dict],
                               candidate: Dict) -> bool:
        """Returns True if candidate weapon is better than equipped."""
        if not equipped:
            return True

        def score(w):
            if not w:
                return -1
            wtype = w.get("typeId", "fist").lower()
            for name, pts in WEAPON_PRIORITY.items():
                if name in wtype:
                    return pts
            return w.get("atkBonus", 0)

        return score(candidate) > score(equipped)

    def get_best_item_on_ground(self, local_items: List[Dict],
                                 inventory: List[Dict]) -> Optional[Dict]:
        """Find the most valuable item on the ground to pick up."""
        if not local_items:
            return None

        equipped_names = {i.get("typeId", "") for i in inventory}

        priority_order = [
            # Best weapons first
            lambda i: "katana" in i.get("item", {}).get("typeId", "").lower(),
            lambda i: "sniper" in i.get("item", {}).get("typeId", "").lower(),
            lambda i: "sword" in i.get("item", {}).get("typeId", "").lower(),
            lambda i: "pistol" in i.get("item", {}).get("typeId", "").lower(),
            # Currency (always grab)
            lambda i: i.get("item", {}).get("category") == "currency",
            # Recovery items
            lambda i: i.get("item", {}).get("category") == "recovery",
            # Utility items
            lambda i: i.get("item", {}).get("category") == "utility",
            # Any weapon
            lambda i: i.get("item", {}).get("category") == "weapon",
        ]

        for check in priority_order:
            candidates = [item for item in local_items if check(item)]
            if candidates:
                return candidates[0]

        return local_items[0] if local_items else None

    # -------------------------------------------------------------------------
    # DEATH ZONE ANALYSIS
    # -------------------------------------------------------------------------

    def death_zone_danger_level(self, intel: Dict) -> int:
        """
        Returns danger level 0-3:
        0 = Safe
        1 = Warning (region in pendingDeathzones)
        2 = Critical (in death zone)
        3 = Emergency (in death zone AND low HP)
        """
        if intel["is_death_zone"]:
            if intel["hp"] < self.hp_critical:
                return 3
            return 2
        if intel["region_id"] in intel["pending_death_zones"]:
            return 1
        return 0

    def safest_escape_region(self, intel: Dict,
                              known_dz: set = None) -> Optional[str]:
        """
        Select the safest adjacent region to escape to.
        Avoids all known death zones (current + pending + memory).
        """
        connections = intel["connections"]
        if not connections:
            return None

        pending = set(str(x) for x in intel["pending_death_zones"])
        all_dz = pending | (known_dz or set())
        # Tambah connections_status
        for rid, is_dz in intel.get("connections_status", {}).items():
            if is_dz:
                all_dz.add(rid)

        truly_safe = [c for c in connections if c not in all_dz]
        if truly_safe:
            return truly_safe[0]
        # Semua koneksi DZ? Pilih yang paling "jauh" dari known DZ
        # (setidaknya coba kabur)
        return connections[0] if connections else None

    # -------------------------------------------------------------------------
    # FACILITY ANALYSIS
    # -------------------------------------------------------------------------

    def get_useful_facility(self, intel: Dict) -> Optional[Dict]:
        """Find the most useful available facility in current region."""
        facilities = [f for f in intel["interactables"]
                      if not f.get("isUsed", False)]
        if not facilities:
            return None

        # Priority: supply_cache > medical (if low HP) > watchtower > broadcast
        priority = {
            "supply_cache": 100,
            "medical": 80 if intel["hp"] < self.hp_low else 30,
            "watchtower": 50,
            "broadcast": 20,
            "cave": 10,  # Last resort hiding
        }

        def facility_score(f):
            ftype = f.get("type", "").lower()
            for key, score in priority.items():
                if key in ftype:
                    return score
            return 5

        return max(facilities, key=facility_score)
