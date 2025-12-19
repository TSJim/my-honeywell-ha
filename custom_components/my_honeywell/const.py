"""Constants for the My Honeywell integration."""
from datetime import timedelta

DOMAIN = "my_honeywell"

# Configuration
CONF_COOL_AWAY_TEMPERATURE = "cool_away_temperature"
CONF_HEAT_AWAY_TEMPERATURE = "heat_away_temperature"

# Defaults
DEFAULT_COOL_AWAY_TEMPERATURE = 88
DEFAULT_HEAT_AWAY_TEMPERATURE = 61
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

# Retry settings
DEFAULT_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2  # seconds

# Platforms
PLATFORMS = ["climate", "sensor"]
