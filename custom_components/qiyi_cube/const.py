"""Constants for the QiYi Smart Cube integration."""

DOMAIN = "qiyi_cube"

CONF_MAC = "mac"  # reversed MAC bytes as hex, needed for the handshake

# Gyro samples arrive ~13/s; push orientation to HA at most this often.
ORIENTATION_UPDATE_INTERVAL = 1.0

# Solution search: start once the cube has been still for SOLVE_DELAY, stop at
# the first solution of at most SOLVE_MAX_LENGTH moves (typically tens of ms;
# searching on for a full second only saves about one move) or after
# SOLVE_SECONDS with the best found so far.
SOLVE_DELAY = 0.3
SOLVE_MAX_LENGTH = 20
SOLVE_SECONDS = 1.0
