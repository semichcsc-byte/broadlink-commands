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

SUBENTRY_TYPE_COMMAND = "command"

CODE_TYPE_IR = "ir"
CODE_TYPE_RF = "rf"

DISCOVERY_TIMEOUT = 5
# The device stops listening on its own; these bound our polling, not the device.
LEARN_TIMEOUT = 30
SWEEP_TIMEOUT = 30
POLL_INTERVAL = 1
