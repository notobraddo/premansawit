import os

"""
==============================================================================
MOLTY ROYALE BOT - CONFIGURATION
==============================================================================
Edit values here before running the bot.
"""

# =============================================================================
# API CREDENTIALS (REQUIRED)
# =============================================================================
API_KEY = os.environ.get("API_KEY", "mr_live_xxxxxxxxxxxxxxxxxxxx")
BASE_URL = os.environ.get("BASE_URL", "https://cdn.moltyroyale.com/api")

# =============================================================================
# WALLET (REQUIRED FOR REWARDS)
# =============================================================================
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "0xxxxxxxxxxxxxxxxxxxx")

# =============================================================================
# GAME PREFERENCES
# =============================================================================
PREFERRED_GAME_TYPE = "free"
AUTO_CREATE_GAME = False         # If True, create game if none waiting
GAME_MAP_SIZE = "medium"         # "medium" | "large" | "massive"

# =============================================================================
# SURVIVAL THRESHOLDS
# =============================================================================
HP_CRITICAL = 65
HP_LOW = 45
EP_MIN_ATTACK = 2                # Min EP required to attack
EP_REST_THRESHOLD = 3

# =============================================================================
# COMBAT DECISION THRESHOLDS
# =============================================================================
WIN_PROBABILITY_ATTACK = 0.65
WIN_PROBABILITY_AGGRESSIVE = 0.80 # Use aggressive tactics if >= 80%

# =============================================================================
# LEARNING SYSTEM
# =============================================================================
LEARNING_ENABLED = True
DATA_DIR = "data"                # Directory to store learning data
MIN_GAMES_FOR_ML = 5             # Min games before ML model activates
LEARNING_RATE = 0.1              # Learning rate for strategy updates

# =============================================================================
# REDIS (OPTIONAL)
# =============================================================================
REDIS_ENABLED = False
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "DEBUG"
LOG_TO_FILE = True
LOG_FILE = "logs/bot.log"

# =============================================================================
# TIMING
# =============================================================================
TURN_INTERVAL = 60               # Seconds between turns (DO NOT CHANGE)
POLL_INTERVAL_WAITING = 5        # Seconds between polls when waiting for game
POLL_INTERVAL_DEAD = 60          # Seconds between polls when dead/idle
ROOM_HUNT_INTERVAL = 2           # Aggressive polling interval when hunting for rooms
HEARTBEAT_INTERVAL = 300         # Seconds between idle heartbeat checks (5 min)
