"""
==============================================================================
MOLTY ROYALE BOT - STATS VIEWER
==============================================================================
Run this to see your bot's learning progress and performance metrics.
Usage: python3 stats.py
"""

import json
import sys
from pathlib import Path
from collections import Counter

DATA_DIR = Path("data")

def load(fname, default):
    path = DATA_DIR / fname
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def bar(value, max_val=1.0, width=20, char="█"):
    filled = int((value / max_val) * width)
    return char * filled + "░" * (width - filled)

def main():
    history     = load("game_history.json", [])
    weights     = load("strategy_weights.json", {})
    enemy_profs = load("enemy_profiles.json", {})

    print("\n" + "="*60)
    print("  MOLTY ROYALE BOT — STATS DASHBOARD")
    print("="*60)

    if not history:
        print("\n  No games played yet. Run main.py to start!\n")
        return

    # ---- CAREER STATS ----
    total    = len(history)
    wins     = sum(1 for g in history if g.get("is_winner"))
    kills    = sum(g.get("kills", 0) for g in history)
    moltz    = sum(g.get("moltz_earned", 0) for g in history)
    avg_rank = sum(g.get("final_rank", 99) for g in history) / total

    print(f"\n  📊 CAREER OVERVIEW ({total} games)")
    print(f"  ─────────────────────────────────────────")
    print(f"  Win Rate:    {wins/total:.1%}  {bar(wins/total)}")
    print(f"  Avg Rank:    #{avg_rank:.1f}")
    print(f"  Total Kills: {kills}  (avg {kills/total:.1f}/game)")
    print(f"  Total Moltz: {moltz:,}  (avg {moltz/total:.0f}/game)")
    print(f"  Wins:        {wins}/{total}")

    # ---- RECENT FORM ----
    recent = history[-10:]
    r_wins = sum(1 for g in recent if g.get("is_winner"))
    r_kills = sum(g.get("kills", 0) for g in recent)
    print(f"\n  📈 RECENT FORM (Last {len(recent)} games)")
    print(f"  ─────────────────────────────────────────")
    print(f"  Win Rate:    {r_wins/len(recent):.1%}  {bar(r_wins/len(recent))}")
    print(f"  Avg Kills:   {r_kills/len(recent):.1f}")

    # Trend
    if len(history) >= 10:
        old_wins = sum(1 for g in history[-20:-10] if g.get("is_winner")) / 10
        new_wins = r_wins / len(recent)
        trend = "↑ IMPROVING" if new_wins > old_wins else \
                "↓ DECLINING" if new_wins < old_wins else "→ STABLE"
        print(f"  Trend:       {trend}")

    # ---- DEATH ANALYSIS ----
    causes = Counter(g.get("death_cause") or "unknown" for g in history
                     if not g.get("is_winner"))
    if causes:
        print(f"\n  💀 DEATH CAUSES")
        print(f"  ─────────────────────────────────────────")
        for cause, count in causes.most_common(5):
            pct = count / total
            print(f"  {cause:<15} {count:>3}x  {bar(pct, max_val=0.5, width=15)}")

    # ---- STRATEGY WEIGHTS ----
    aw = weights.get("action_weights", {})
    if aw:
        print(f"\n  🧠 LEARNED STRATEGY WEIGHTS")
        print(f"  ─────────────────────────────────────────")
        print(f"  Attack vs Evade:   {aw.get('attack_vs_evade', 0.6):.2f}  "
              f"{'(Aggressive)' if aw.get('attack_vs_evade', 0) > 0.6 else '(Cautious)'}")
        print(f"  Heal Threshold:    {aw.get('heal_threshold', 0.3):.2f}  HP%")
        print(f"  Rest Threshold:    {aw.get('rest_threshold', 0.3):.2f}  EP%")
        print(f"  Flee Threshold:    {aw.get('flee_when_losing', 0.7):.2f}")
        print(f"  Attack Threshold:  {weights.get('attack_threshold', 0.65):.2f}  "
              f"Win prob required")

    # ---- ENEMY PROFILES ----
    if enemy_profs:
        print(f"\n  👾 ENEMY PROFILES ({len(enemy_profs)} tracked)")
        print(f"  ─────────────────────────────────────────")
        by_encounters = sorted(enemy_profs.items(),
                               key=lambda x: x[1].get("encounters", 0), reverse=True)
        for eid, prof in by_encounters[:5]:
            w = prof.get("wins_against", 0)
            l = prof.get("losses_to", 0)
            total_enc = w + l
            wr = w/total_enc if total_enc > 0 else 0
            print(f"  ...{eid[-8:]:<10} Enc:{total_enc}  W:{w} L:{l}  WR:{wr:.0%}")

    # ---- ML STATUS ----
    games_needed = max(0, 5 - total)
    if games_needed > 0:
        print(f"\n  🤖 ML STATUS: Need {games_needed} more games to activate")
    else:
        print(f"\n  🤖 ML STATUS: Active ({total} games of training data)")

    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
