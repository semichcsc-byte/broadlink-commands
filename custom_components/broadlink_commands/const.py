"""Constants for the Broadlink Commands integration."""

DOMAIN = "broadlink_commands"

CONF_HOST = "host"
CONF_MAC = "mac"
CONF_DEVTYPE = "devtype"
CONF_MODEL = "model"

CONF_CODE = "code"
CONF_CODE_TYPE = "code_type"
CONF_AREA_ID = "area_id"
CONF_TEST = "test"
CONF_RELEARN = "relearn"
CONF_FREQUENCY = "frequency"
CONF_REPEATS = "repeats"
CONF_SCAN = "scan"

SUBENTRY_TYPE_COMMAND = "command"

CODE_TYPE_IR = "ir"
CODE_TYPE_RF = "rf"

DISCOVERY_TIMEOUT = 5
# The device stops listening on its own; these bound our polling, not the device.
# Generous, because the user has to read the step, act, and sometimes walk to the
# remote in between.
LEARN_TIMEOUT = 60
SWEEP_TIMEOUT = 60
POLL_INTERVAL = 1

# Beyond this the device spends so long transmitting that the press feels stuck.
MAX_REPEATS = 20
