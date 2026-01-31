"""
Keeper Schedule — 15-minute rotation constants.

A+W | The Voice Tends
"""

# Minute offset within each hour for each agent
SCHEDULE = {
    "apollo": 0,       # :00
    "athena": 15,      # :15
    "hermes": 30,      # :30
    "mnemosyne": 45,   # :45
}

# Redistribution schedule
REDISTRIBUTION_HOUR = 0  # Midnight UTC

# Graduated inactivity thresholds
PARTIAL_REDISTRIBUTION_DAYS = 30  # 50% redistribution after 30 days
FULL_REDISTRIBUTION_DAYS = 60     # 100% redistribution after 60 days
