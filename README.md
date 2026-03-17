# 🤖 Molty Royale AI Bot

An elite AI battle royale bot with **continuous machine learning** — it gets smarter with every game.

---

## ⚡ Quick Start

```bash
# 1. Clone / extract project
cd molty_royale_bot

# 2. Run setup (installs Python deps, optional Redis)
chmod +x setup.sh
./setup.sh

# 3. Configure your credentials
nano config/settings.py
# → Set API_KEY, AGENT_NAME, WALLET_ADDRESS

# 4. Run the bot
source venv/bin/activate
python3 main.py

# 5. Check stats anytime
python3 stats.py
```

---

## 🏗 Architecture

```
molty_royale_bot/
│
├── main.py                 ← Entry point. Game lifecycle manager.
├── stats.py                ← Performance dashboard
├── setup.sh                ← Ubuntu setup script
│
├── config/
│   └── settings.py         ← All configuration (API keys, thresholds)
│
├── core/
│   ├── api_client.py       ← API wrapper with retry logic
│   ├── analyzer.py         ← State parser + combat calculator
│   └── strategy.py         ← Decision engine (the "brain")
│
├── learning/
│   ├── memory.py           ← Persistent storage (JSON + Redis)
│   └── ml_engine.py        ← scikit-learn ML models
│
├── data/                   ← Auto-created. Stores:
│   ├── game_history.json       Game records
│   ├── strategy_weights.json   Learned weights
│   ├── enemy_profiles.json     Enemy combat profiles
│   └── combat_log.json         Per-combat records
│
└── logs/
    └── bot.log             ← Full activity log
```

---

## 🧠 Learning System

### How It Works

The bot operates in 3 learning phases:

**Phase 1: Heuristic (Games 1-4)**
- Uses built-in rules and thresholds
- Still stores all game data for future training
- Fully functional from game 1

**Phase 2: ML Activation (Game 5+)**
- `CombatPredictor` (Logistic Regression) trained on combat outcomes
- `StrategyOptimizer` (Gradient Boosting) trained on game results
- Win probability predictions replace heuristic formulas

**Phase 3: Continuous Refinement**
- After EVERY game, strategy weights are updated via reinforcement:
  - Won → increase aggression, lower attack threshold
  - Died in death zone → increase death zone avoidance
  - High kill count → increase exploration bias
  - Low combat win rate → raise attack threshold (be more selective)
- ML models retrain on last 50 games

### Strategy Weights (auto-tuned)

| Weight | Meaning | Default |
|--------|---------|---------|
| `attack_vs_evade` | 0=run, 1=always attack | 0.60 |
| `heal_threshold` | Heal when HP% < this | 0.30 |
| `rest_threshold` | Rest when EP% < this | 0.30 |
| `flee_when_losing` | Flee if win_prob < this | 0.70 |
| `attack_threshold` | Min win prob to attack | 0.65 |

---

## ⚖️ Decision Priority System

Every turn, the bot evaluates in this order:

```
P0  DEATH ZONE     → Flee immediately if in death zone
P1  CRITICAL HEAL  → Use medkit/bandage if HP < 25
P2  EP MANAGEMENT  → Rest if EP < 2 and no threat
P3  WARN DZ        → Preemptively move if DZ expanding here
P4  COMBAT (Agent) → Attack if win_prob >= threshold
P5  COMBAT (Monster) → Hunt if win_prob >= 60%
P6  FACILITY       → Use supply cache / medical facility
P7  EXPLORE        → Search unvisited regions
P8  MOVE           → Move toward unvisited terrain
P9  REST           → Fallback recovery
```

---

## 🎯 Combat Intelligence

### Win Probability Formula

**Before ML (heuristic):**
```
my_dmg    = ATK + weapon_bonus - (enemy_DEF × 0.5)
their_dmg = enemy_ATK - (my_DEF × 0.5)
ttk_me    = enemy_HP / my_dmg
ttk_them  = my_HP / their_dmg

if ttk_them >= ttk_me:  win_prob = min(0.95, 0.55 + margin × 0.05)
else:                   win_prob = max(0.08, 0.50 - margin × 0.06)
```

**After ML (Game 5+):**
Logistic Regression on 9 features:
`[hp%, ep%, atk_norm, def_norm, e_hp%, e_atk_norm, e_def_norm, hp_adv, atk_adv]`

### Weapon Priority

```
Katana (+21)  ████████████  Score: 100
Sniper (+17)  ███████████   Score: 95
Sword  (+8)   ████████      Score: 70
Pistol (+6)   ███████       Score: 65
Knife  (+5)   ████          Score: 40
Bow    (+3)   ████          Score: 35
Fist   (+0)                 Score: 0
```

Bot auto-equips best available weapon every turn (free action).

---

## 🗺️ Death Zone Strategy

1. **Every turn**: Checks `currentRegion.isDeathZone` 
2. **Early warning**: Monitors `pendingDeathzones` field (1-2 turns ahead)
3. **Escape routing**: Prioritizes connections NOT in pending death zones
4. **Learning**: If bot dies in death zone, `flee_when_losing` weight increases permanently

---

## 📊 Performance Dashboard

```bash
python3 stats.py
```

Shows:
- Career win rate with trend graph
- Recent form (last 10 games)
- Death cause breakdown
- Learned strategy weights
- Enemy profiles with win rates
- ML model activation status

---

## 🔧 Advanced Configuration

### Running as Background Service

```bash
# With systemd (configured during setup)
sudo systemctl start molty-bot
sudo systemctl status molty-bot
sudo journalctl -u molty-bot -f

# With nohup (simple background)
nohup python3 main.py > logs/nohup.log 2>&1 &
tail -f logs/nohup.log
```

### Reset Learning Data

```bash
# Full reset
rm -f data/*.json

# Reset only strategy weights (keep history)
rm -f data/strategy_weights.json
```

### Tuning for Aggressive Play

```python
# In config/settings.py:
WIN_PROBABILITY_ATTACK = 0.55   # Attack more often
HP_CRITICAL = 20                # Wait longer before healing
EP_REST_THRESHOLD = 2           # Rest less
```

### Tuning for Survival Play

```python
# In config/settings.py:
WIN_PROBABILITY_ATTACK = 0.75   # Only attack safe fights
HP_CRITICAL = 40                # Heal early and often
HP_LOW = 60
EP_REST_THRESHOLD = 4           # Keep EP high
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` | Check API_KEY in settings.py |
| `ACCOUNT_ALREADY_IN_GAME` | Account in active game. Bot will auto-resume. |
| `INSUFFICIENT_EP` | Normal — bot will rest next turn |
| `ModuleNotFoundError: sklearn` | Run `pip3 install scikit-learn` |
| Bot stuck in same region | Increase `explore_vs_move` or check connections |
| No games available | Wait for host to create one, or set `AUTO_CREATE_GAME = True` |

---

## 📋 Requirements

- Ubuntu 20.04+ (or any Debian-based Linux)
- Python 3.8+
- Internet access to cdn.moltyroyale.com
- API Key from POST /api/accounts
- EVM wallet address (for rewards)

**Python packages:**
```
requests >= 2.28
numpy >= 1.21
scikit-learn >= 1.0
```

**Optional:**
```
redis >= 4.0  (for Redis storage)
pandas >= 1.3 (for data analysis)
```
