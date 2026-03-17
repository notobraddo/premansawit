"""
==============================================================================
MOLTY ROYALE BOT - MACHINE LEARNING ENGINE
==============================================================================
Uses scikit-learn to build predictive models from game history.
Models:
  1. CombatPredictor   - Predict combat outcome from stats
  2. StrategyOptimizer - Reinforce winning decision patterns
  3. SurvivalAnalyzer  - Identify what behaviors lead to wins
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("MoltyBot.ML")

# Try to import sklearn; degrade gracefully if not installed
try:
    from sklearn.linear_model import LogisticRegression, SGDClassifier
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.exceptions import NotFittedError
    import pickle
    SKLEARN_AVAILABLE = True
    logger.info("scikit-learn available - ML features enabled")
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not found - using heuristic fallback. "
                   "Run: pip3 install scikit-learn numpy")


class CombatPredictor:
    """
    Predicts combat win probability using logistic regression.
    Features: [my_hp%, my_ep%, my_atk_total, my_def,
               enemy_hp%, enemy_atk_total, enemy_def, hp_advantage]
    """

    def __init__(self):
        self.model = None
        self.scaler = None
        self.trained = False
        self.training_samples = 0
        self.MIN_SAMPLES = 20

        if SKLEARN_AVAILABLE:
            self.model = LogisticRegression(max_iter=1000, C=1.0)
            self.scaler = StandardScaler()

    def _extract_features(self, my_stats: Dict, enemy_stats: Dict) -> List[float]:
        """
        Extract feature vector for combat prediction.

        Features [15 total]:
          0  my_hp_pct         : HP kita saat ini / 100
          1  my_ep_pct         : EP kita / 10
          2  my_atk_norm       : (ATK + weapon_bonus) / 40
          3  my_def_norm       : DEF / 15
          4  e_hp_pct          : HP musuh / 100
          5  e_atk_norm        : ATK musuh / 40
          6  e_def_norm        : DEF musuh / 15
          7  hp_advantage      : selisih HP kita vs musuh
          8  atk_advantage     : selisih ATK efektif
          --- NEW: Inventory heal features ---
          9  heal_hp_norm      : total HP bisa dipulihkan / 150 (3x medkit=150)
          10 heal_count_norm   : jumlah heal items / 5
          11 effective_hp_pct  : (hp + heal_hp_total) / 200
          12 heal_ep_norm      : EP dari energy drink / 10
          13 ep_heal_budget    : berapa heal turn dalam EP / 10
          14 hp_heal_advantage : (eff_hp - e_hp) / 150
        """
        my_hp       = my_stats.get("hp", 100)
        my_ep       = my_stats.get("ep", 10)
        my_atk_eff  = my_stats.get("atk", 10) + my_stats.get("weapon_bonus", 0)
        my_def      = my_stats.get("def", 5)

        e_hp        = enemy_stats.get("hp", 50)
        e_atk_eff   = enemy_stats.get("atk", 10) + enemy_stats.get("weapon_bonus", 0)
        e_def       = enemy_stats.get("def", 5)

        # Base features
        my_hp_pct    = my_hp / 100.0
        my_ep_pct    = my_ep / 10.0
        e_hp_pct     = e_hp / 100.0
        hp_advantage = my_hp_pct - e_hp_pct
        atk_advantage= (my_atk_eff - e_atk_eff) / 40.0

        # Inventory heal features (dari _my_combat_stats)
        heal_hp      = float(my_stats.get("heal_hp_total", 0))
        heal_count   = float(my_stats.get("heal_count", 0))
        eff_hp       = float(my_stats.get("effective_hp", my_hp))
        heal_ep      = float(my_stats.get("heal_ep_total", 0))
        # Berapa heal turn bisa dilakukan: 1 heal per 3 EP (attack2+heal1)
        ep_heal_budget = min(heal_count, my_ep / 3.0)
        hp_heal_adv   = (eff_hp - e_hp) / 150.0

        return [
            # Base stats (0-8)
            my_hp_pct,
            my_ep_pct,
            my_atk_eff / 40.0,
            my_def / 15.0,
            e_hp_pct,
            e_atk_eff / 40.0,
            e_def / 15.0,
            hp_advantage,
            atk_advantage,
            # Inventory heal features (9-14)
            heal_hp / 150.0,      # normalized: medkit×3 = 150
            heal_count / 5.0,     # normalized: max 5 items
            eff_hp / 200.0,       # effective HP (hp+heals) normalized
            heal_ep / 10.0,       # EP dari energy drink
            ep_heal_budget / 5.0, # heal turns available
            hp_heal_adv,          # effective HP advantage vs enemy
        ]

    def train(self, combat_records: List[Dict]):
        """Train model on historical combat data."""
        if not SKLEARN_AVAILABLE or len(combat_records) < self.MIN_SAMPLES:
            return False

        X, y = [], []
        for record in combat_records:
            try:
                my_st  = record.get("my_stats", {})
                en_st  = record.get("enemy_stats", {})

                # Fallback: bangun enemy_stats dari field lama
                # (untuk kompatibilitas dengan record lama)
                if not en_st:
                    en_st = {
                        "hp"          : record.get("target_hp", 50),
                        "atk"         : record.get("target_atk", 10),
                        "def"         : record.get("target_def", 5),
                        "weapon_bonus": 0,
                    }

                # Skip jika my_stats kosong (data lama sebelum upgrade)
                # Tapi tetap bisa pakai heuristic dari field dasar
                if not my_st:
                    my_st = {
                        "hp": 80, "ep": 8, "atk": 10, "def": 5,
                        "weapon_bonus": 0,
                        "heal_hp_total": 0, "heal_count": 0,
                        "heal_ep_total": 0, "best_heal_hp": 0,
                        "effective_hp": 80,
                    }

                features = self._extract_features(my_st, en_st)
                X.append(features)
                y.append(1 if record.get("won", False) else 0)
            except Exception:
                continue

        if len(X) < self.MIN_SAMPLES:
            return False

        try:
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.trained = True
            self.training_samples = len(X)
            logger.info(f"CombatPredictor trained on {len(X)} samples")
            return True
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False

    def predict_win_probability(self, my_stats: Dict, enemy_stats: Dict) -> float:
        """
        Predict win probability. Returns heuristic if not trained.
        """
        if not SKLEARN_AVAILABLE or not self.trained:
            return self._heuristic_predict(my_stats, enemy_stats)

        try:
            features = self._extract_features(my_stats, enemy_stats)
            X_scaled = self.scaler.transform([features])
            prob = self.model.predict_proba(X_scaled)[0][1]
            return round(float(prob), 3)
        except Exception as e:
            logger.debug(f"ML prediction failed, using heuristic: {e}")
            return self._heuristic_predict(my_stats, enemy_stats)

    def _heuristic_predict(self, my_stats: Dict, enemy_stats: Dict) -> float:
        """Rule-based fallback when ML model not ready."""
        my_hp    = my_stats.get("hp", 100)
        my_atk   = my_stats.get("atk", 10) + my_stats.get("weapon_bonus", 0)
        my_def   = my_stats.get("def", 5)

        e_hp     = enemy_stats.get("hp", 50)
        e_atk    = enemy_stats.get("atk", 10) + enemy_stats.get("weapon_bonus", 0)
        e_def    = enemy_stats.get("def", 5)

        my_dmg    = max(1, my_atk - e_def * 0.5)
        their_dmg = max(1, e_atk - my_def * 0.5)

        my_ttk    = e_hp / my_dmg
        their_ttk = my_hp / their_dmg

        if their_ttk > my_ttk:
            return min(0.92, 0.55 + (their_ttk - my_ttk) * 0.05)
        else:
            return max(0.08, 0.50 - (my_ttk - their_ttk) * 0.06)


class StrategyOptimizer:
    """
    Reinforcement-style learning: adjusts strategy weights based on
    game outcomes. Uses gradient boosting to identify key success factors.
    """

    def __init__(self):
        self.model = None
        self.scaler = None
        self.trained = False
        self.feature_importance = {}

        if SKLEARN_AVAILABLE:
            self.model = GradientBoostingClassifier(
                n_estimators=50, learning_rate=0.1, max_depth=3
            )
            self.scaler = StandardScaler()

    def _extract_game_features(self, game: Dict) -> List[float]:
        """
        Extract features from a completed game record.

        Features [26 total — base 12 + inventory 7 + combat quality 7]:
          ── Base Survival ──
          0  avg_hp               : rata-rata HP per turn / 100
          1  avg_ep               : rata-rata EP per turn / 10
          2  explore_ratio        : explore turns / total
          3  attack_ratio         : attack turns / total
          4  move_ratio           : move turns / total
          5  rest_ratio           : rest turns / total
          6  combat_win_rate      : combat wins / total combats
          7  combat_frequency     : combats / turns
          8  dz_escape_rate       : dz escapes / turns
          9  region_coverage      : unique regions / turns
          10 kills                : total kills
          11 died_in_dz           : 1 jika mati di DZ, else 0
          ── Inventory Quality ──
          12 avg_heal_count       : rata-rata heal items dimiliki / turn
          13 avg_heal_hp_avail    : rata-rata heal HP tersedia / turn
          14 heal_used_rate       : items dipakai / turns
          15 heal_in_combat_rate  : % heal dipakai saat combat
          16 heal_critical_rate   : % heal dipakai saat HP kritis
          17 avg_weapon_bonus     : rata-rata bonus senjata
          18 weapon_upgrade_rate  : % turn punya senjata > fist
          ── Combat Quality ──
          19 avg_damage_dealt     : damage rata-rata per combat / 30
          20 avg_damage_taken     : kerusakan rata-rata / 30
          21 damage_efficiency    : dealt / (dealt + taken)
          22 heal_per_combat      : heal dipakai per combat
          23 min_hp_reached       : HP terendah yang pernah dicapai
          24 turns_at_critical    : % turn dengan HP < 25
          25 item_collect_rate    : items dikumpulkan / turns
        """
        turns      = game.get("turns", [])
        combats    = game.get("combat_outcomes", [])
        items_used = game.get("items_used", [])   # NEW: from record_item_used
        items_coll = game.get("items_collected", [])

        n_turns   = max(len(turns), 1)
        n_combats = max(len(combats), 1)

        # ── Base features ─────────────────────────────────────────
        combat_wins  = sum(1 for c in combats if c.get("won"))
        combat_rate  = combat_wins / n_combats

        hp_vals   = [t["hp"] for t in turns if t.get("hp") is not None]
        ep_vals   = [t["ep"] for t in turns if t.get("ep") is not None]
        avg_hp    = np.mean(hp_vals) if hp_vals else 50
        avg_ep    = np.mean(ep_vals) if ep_vals else 5
        min_hp    = min(hp_vals) if hp_vals else 0

        action_counts = {}
        for t in turns:
            a = t.get("action_type", "move")
            action_counts[a] = action_counts.get(a, 0) + 1

        explore_ratio = action_counts.get("explore", 0) / n_turns
        attack_ratio  = action_counts.get("attack",  0) / n_turns
        move_ratio    = action_counts.get("move",    0) / n_turns
        rest_ratio    = action_counts.get("rest",    0) / n_turns

        dz_escapes    = game.get("death_zone_escapes", 0)
        regions_count = len(game.get("regions_visited", []))
        kills         = game.get("kills", 0)
        death_in_dz   = 1 if game.get("death_cause") == "death_zone" else 0

        # ── Inventory quality features ────────────────────────────
        heal_cnts  = [t.get("inv_heal_count", 0) for t in turns]
        heal_hps   = [t.get("inv_heal_hp",    0) for t in turns]
        wpn_bonus  = [t.get("inv_weapon_bonus", 0) for t in turns]

        avg_heal_cnt = np.mean(heal_cnts) if heal_cnts else 0
        avg_heal_hp  = np.mean(heal_hps)  if heal_hps  else 0
        avg_wpn_bon  = np.mean(wpn_bonus) if wpn_bonus else 0
        had_weapon   = sum(1 for b in wpn_bonus if b > 0) / n_turns

        n_used = max(len(items_used), 1)
        heal_used_rate    = len(items_used) / n_turns
        heal_in_cbt_rate  = sum(
            1 for i in items_used if i.get("context") == "combat"
        ) / n_used
        heal_crit_rate    = sum(
            1 for i in items_used if i.get("context") == "critical"
        ) / n_used

        # ── Combat quality features ───────────────────────────────
        dd_vals = [c.get("damage_dealt", 0) for c in combats]
        dt_vals = [c.get("damage_taken", 0) for c in combats]
        avg_dd  = np.mean(dd_vals) if dd_vals else 0
        avg_dt  = np.mean(dt_vals) if dt_vals else 0
        total_dd = sum(dd_vals)
        total_dt = sum(dt_vals)
        dmg_eff  = total_dd / max(total_dd + total_dt, 1)  # dealt/(dealt+taken)
        h_per_cbt= sum(c.get("heals_used", 0) for c in combats) / n_combats

        crit_turns = sum(1 for t in turns
                         if t.get("hp", 100) < 25) / n_turns
        item_coll_rate = len(items_coll) / n_turns

        return [
            # Base (0-11)
            avg_hp / 100, avg_ep / 10,
            explore_ratio, attack_ratio, move_ratio, rest_ratio,
            combat_rate, len(combats) / n_turns,
            dz_escapes / n_turns, regions_count / n_turns,
            kills, death_in_dz,
            # Inventory (12-18)
            avg_heal_cnt / 5.0,
            avg_heal_hp / 150.0,
            heal_used_rate,
            heal_in_cbt_rate,
            heal_crit_rate,
            avg_wpn_bon / 21.0,
            had_weapon,
            # Combat quality (19-25)
            avg_dd / 30.0,
            avg_dt / 30.0,
            dmg_eff,
            h_per_cbt / 3.0,
            min_hp / 100.0,
            crit_turns,
            item_coll_rate,
        ]

    def _label_game(self, game: Dict, all_games: List[Dict]) -> int:
        """
        Buat label performa untuk training.
        Fallback hierarchy saat belum ada win:
          1. is_winner = True                → label 1
          2. final_rank ≤ top 25%            → label 1
          3. top 50% berdasarkan rank/turns  → label 1
          4. top half berdasarkan turns_played → label 1
        Tujuan: selalu ada label 0 dan 1 meski belum menang.
        """
        if game.get("is_winner"):
            return 1

        # Coba rank-based
        rank = game.get("final_rank", 100)
        if rank and rank <= 25:
            return 1

        # Relative rank — hanya berguna jika ada variance di ranks
        ranks = [g.get("final_rank", 100) for g in all_games
                 if g.get("final_rank")]
        if ranks and len(set(ranks)) > 1:  # ada variance
            median_rank = sorted(ranks)[len(ranks) // 2]
            if rank < median_rank:  # STRICT less than
                return 1

        # Last resort: bandingkan turns_played
        # (survive lebih lama = lebih baik)
        turns = game.get("turns_played", 0)
        all_turns = [g.get("turns_played", 0) for g in all_games]
        if all_turns:
            median_turns = sorted(all_turns)[len(all_turns) // 2]
            if turns >= median_turns:
                return 1

        return 0

    def train(self, game_history: List[Dict]) -> bool:
        """Train on game history. Label: relative performance score."""
        if not SKLEARN_AVAILABLE or len(game_history) < 5:
            return False

        X, y = [], []
        for game in game_history:
            try:
                features = self._extract_game_features(game)
                X.append(features)
                label = self._label_game(game, game_history)
                y.append(label)
            except Exception:
                continue

        if len(X) < 5:
            return False

        # Jika masih semua 0 atau semua 1, paksa split median turns
        if len(set(y)) < 2:
            turns_list = [g.get("turns_played", 0) for g in game_history]
            med = sorted(turns_list)[len(turns_list) // 2]
            y = [1 if g.get("turns_played", 0) >= med else 0
                 for g in game_history[:len(X)]]
            logger.info("ML: Menggunakan turns_played sebagai label "
                        "(belum ada win/rank variance)")

        if len(set(y)) < 2:
            return False  # benar-benar tidak bisa dibedakan

        try:
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.trained = True

            # Extract feature importance
            feature_names = [
                # Base
                "avg_hp", "avg_ep", "explore_ratio", "attack_ratio",
                "move_ratio", "rest_ratio", "combat_win_rate",
                "combat_frequency", "dz_escape_rate", "region_coverage",
                "kills", "died_in_dz",
                # Inventory
                "avg_heal_count", "avg_heal_hp_avail", "heal_used_rate",
                "heal_in_combat_rate", "heal_critical_rate",
                "avg_weapon_bonus", "weapon_upgrade_rate",
                # Combat quality
                "avg_damage_dealt", "avg_damage_taken", "damage_efficiency",
                "heal_per_combat", "min_hp_reached",
                "turns_at_critical", "item_collect_rate",
            ]
            importances = self.model.feature_importances_
            self.feature_importance = dict(zip(feature_names, importances))

            top = sorted(self.feature_importance.items(),
                         key=lambda x: x[1], reverse=True)[:3]
            logger.info(f"StrategyOptimizer trained. Top factors: {top}")
            return True
        except Exception as e:
            logger.error(f"Strategy training failed: {e}")
            return False

    def get_strategy_recommendations(self) -> Dict:
        """
        Return strategy recommendations based on feature importance.
        Higher importance on a feature → focus more on that behavior.
        """
        if not self.trained or not self.feature_importance:
            return {}

        recs = {}

        if self.feature_importance.get("attack_ratio", 0) > 0.15:
            recs["increase_aggression"] = True
        if self.feature_importance.get("explore_ratio", 0) > 0.15:
            recs["increase_exploration"] = True
        if self.feature_importance.get("dz_escape_rate", 0) > 0.10:
            recs["prioritize_dz_escape"] = True
        # ── Inventory-based recommendations ──────────────────────
        if self.feature_importance.get("avg_heal_count", 0) > 0.10:
            recs["prioritize_item_collection"] = True
        if self.feature_importance.get("heal_in_combat_rate", 0) > 0.12:
            recs["use_heals_during_combat"] = True
        if self.feature_importance.get("avg_weapon_bonus", 0) > 0.12:
            recs["prioritize_weapon_upgrade"] = True
        if self.feature_importance.get("damage_efficiency", 0) > 0.10:
            recs["focus_combat_efficiency"] = True
        if self.feature_importance.get("died_in_dz", 0) > 0.15:
            recs["avoid_death_zone_more"] = True
        if self.feature_importance.get("avg_hp", 0) > 0.15:
            recs["heal_more_aggressively"] = True

        return recs


class LearningEngine:
    """
    Master learning controller.
    Coordinates CombatPredictor + StrategyOptimizer.
    Applies learning updates to strategy weights after each game.
    """

    def __init__(self, memory, min_games_for_ml: int = 5):
        self.memory = memory
        self.min_games = min_games_for_ml
        self.combat_predictor = CombatPredictor()
        self.strategy_optimizer = StrategyOptimizer()
        self.last_trained = None
        logger.info(f"LearningEngine initialized (min_games={min_games_for_ml})")

    def retrain(self, game_history: List[Dict]):
        """Retrain all models on latest game history."""
        if len(game_history) < self.min_games:
            logger.info(f"Need {self.min_games - len(game_history)} more games before ML kicks in")
            return

        # Build combat dataset from all games
        combat_records = []
        for game in game_history:
            for combat in game.get("combat_outcomes", []):
                if combat.get("my_stats") and combat.get("enemy_stats"):
                    combat_records.append(combat)

        if combat_records:
            self.combat_predictor.train(combat_records)

        self.strategy_optimizer.train(game_history)
        self.last_trained = datetime.utcnow()

    def post_game_update(self, game_result: Dict):
        """
        Called after each game ends.
        Analyzes what worked/didn't and updates strategy weights.
        """
        if not game_result:
            return

        is_winner  = game_result.get("is_winner", False)
        final_rank = game_result.get("final_rank", 100)
        kills      = game_result.get("kills", 0)
        turns      = game_result.get("turns_played", 1)
        death_cause = game_result.get("death_cause", "")
        combats    = game_result.get("combat_outcomes", [])

        n_combats     = len(combats)
        combat_wins   = sum(1 for c in combats if c.get("won"))
        combat_loss   = n_combats - combat_wins
        dz_escapes    = game_result.get("death_zone_escapes", 0)

        updates = []

        # === AGGRESSION TUNING ===
        if is_winner:
            # Winner — be more aggressive
            self.memory.update_weight("attack_vs_evade", +0.05)
            self.memory.update_attack_threshold(-0.02)  # Attack sooner
            updates.append("↑ aggression (won)")
        elif final_rank and final_rank < 10:
            # Top 10 but not winner — slight positive
            self.memory.update_weight("attack_vs_evade", +0.02)
            updates.append("↑ aggression (top 10)")
        else:
            # Died early — be more careful
            self.memory.update_weight("attack_vs_evade", -0.03)
            updates.append("↓ aggression (early death)")

        # === DEATH ZONE BEHAVIOR ===
        if death_cause == "death_zone":
            self.memory.update_weight("flee_when_losing", +0.1)
            updates.append("↑ dz avoidance (died in dz)")
        elif dz_escapes > 0 and is_winner:
            self.memory.update_weight("flee_when_losing", +0.02)
            updates.append("↑ dz escape reward")

        # === HEALING BEHAVIOR ===
        if death_cause in ("agent", "monster") and not is_winner:
            # Died in combat — might need more healing
            self.memory.update_weight("heal_threshold", +0.05)
            updates.append("↑ heal threshold (died in combat)")
        elif is_winner and kills > 2:
            # Won with multiple kills — can afford to be less cautious with HP
            self.memory.update_weight("heal_threshold", -0.02)

        # === EXPLORATION BEHAVIOR ===
        if kills > 3:
            # More kills means finding good weapons worked
            self.memory.update_weight("explore_vs_move", +0.05)
            updates.append("↑ exploration (high kills)")

        # === EP MANAGEMENT ===
        rest_turns = sum(1 for t in game_result.get("turns", [])
                         if t.get("action_type") == "rest")
        if rest_turns / max(turns, 1) > 0.3:
            # Too much resting — lower rest threshold
            self.memory.update_weight("rest_threshold", -0.05)
            updates.append("↓ rest threshold (over-resting)")

        # === COMBAT WIN RATE ADJUSTMENT ===
        if n_combats > 0:
            win_rate = combat_wins / n_combats
            if win_rate < 0.4:
                # Combat is not going well — raise attack threshold
                self.memory.update_attack_threshold(+0.05)
                updates.append(f"↑ attack threshold (combat win_rate={win_rate:.1%})")
            elif win_rate > 0.7 and n_combats > 3:
                # Combat is going great — lower threshold to attack more
                self.memory.update_attack_threshold(-0.03)
                updates.append(f"↓ attack threshold (combat win_rate={win_rate:.1%})")

        # Retrain models
        self.retrain(self.memory.get_recent_games(50))
        self.memory.save_all()

        logger.info(f"Post-game learning applied: {updates}")

        # Apply strategy recommendations from ML model
        recs = self.strategy_optimizer.get_strategy_recommendations()
        for rec, active in recs.items():
            if active:
                logger.info(f"ML recommendation: {rec}")

    def predict_combat(self, my_stats: Dict, enemy_stats: Dict) -> float:
        """Predict win probability for a combat encounter."""
        return self.combat_predictor.predict_win_probability(my_stats, enemy_stats)

    def is_ml_active(self) -> bool:
        """Returns True if ML models are trained and being used."""
        return (SKLEARN_AVAILABLE and
                self.memory.games_played() >= self.min_games and
                (self.combat_predictor.trained or self.strategy_optimizer.trained))

    def get_learning_status(self) -> Dict:
        return {
            "sklearn_available": SKLEARN_AVAILABLE,
            "games_played": self.memory.games_played(),
            "ml_active": self.is_ml_active(),
            "combat_model_trained": self.combat_predictor.trained,
            "strategy_model_trained": self.strategy_optimizer.trained,
            "combat_samples": self.combat_predictor.training_samples,
            "last_trained": str(self.last_trained),
            "feature_importance": self.strategy_optimizer.feature_importance,
        }
