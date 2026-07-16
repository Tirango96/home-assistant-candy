"""Constants for the Candy integration."""

DOMAIN = "candy"
PLATFORMS = ["sensor", "select", "number", "button", "switch"]

DATA_KEY_COORDINATOR = "coordinator"
DATA_KEY_STATS_COORDINATOR = "stats_coordinator"
DATA_KEY_CLIENT = "client"

CONF_INTEGRATION_TITLE = "Candy"
CONF_KEY_USE_ENCRYPTION = "use_encryption"

# Integration mode stored in config entry
CONF_KEY_MODE = "mode"
MODE_READ_ONLY = "read_only"
MODE_FULL_CONTROL = "full_control"

# Config entry fields populated from Simply-Fi cloud in Full Control mode
CONF_KEY_MAC_ADDRESS = "mac_address"
CONF_KEY_PROGRAMS = "simply_fi_programs"
CONF_KEY_DEVICE_MODEL = "device_model"
CONF_KEY_SERIAL_NUMBER = "serial_number"

UNIQUE_ID_WASHING_MACHINE = "{0}-washing_machine"
UNIQUE_ID_WASH_PROGRAM = "{0}-wash_program"
UNIQUE_ID_WASH_CYCLE_STATUS = "{0}-wash_cycle_status"
UNIQUE_ID_WASH_REMAINING_TIME = "{0}-wash_remaining_time"
UNIQUE_ID_WASH_TEMPERATURE = "{0}-wash_temperature"
UNIQUE_ID_WASH_SPIN_SPEED = "{0}-wash_spin_speed"
UNIQUE_ID_WASH_FILL_PERCENT = "{0}-wash_fill_percent"
UNIQUE_ID_WASH_ERROR = "{0}-wash_error"
UNIQUE_ID_WASH_DELAY = "{0}-wash_delay"
UNIQUE_ID_WASH_NTC_WATER = "{0}-wash_ntc_water"
UNIQUE_ID_WASH_NTC_DRUM = "{0}-wash_ntc_drum"
UNIQUE_ID_WASH_MOTOR_FREQ = "{0}-wash_motor_freq"
UNIQUE_ID_WASH_TOTAL_CYCLES = "{0}-wash_total_cycles"
UNIQUE_ID_WASH_CHECK_UP = "{0}-wash_check_up"
UNIQUE_ID_WASH_SOIL_LEVEL = "{0}-wash_soil_level"
UNIQUE_ID_WASH_ESTIMATED_DURATION = "{0}-wash_estimated_duration"

UNIQUE_ID_WASH_PROGRAM_SELECT = "{0}-wash_program_select"
UNIQUE_ID_WASH_TEMP_SELECT = "{0}-wash_temp_select"
UNIQUE_ID_WASH_SPIN_SELECT = "{0}-wash_spin_select"
UNIQUE_ID_WASH_SOIL_SELECT = "{0}-wash_soil_select"
UNIQUE_ID_WASH_DELAY_NUMBER = "{0}-wash_delay_number"
UNIQUE_ID_WASH_START_BUTTON = "{0}-wash_start_button"
UNIQUE_ID_WASH_PAUSE_BUTTON = "{0}-wash_pause_button"
UNIQUE_ID_WASH_STOP_BUTTON = "{0}-wash_stop_button"
UNIQUE_ID_WASH_STEAM_SWITCH = "{0}-wash_steam_switch"

UNIQUE_ID_TUMBLE_DRYER = "{0}-tumble_dryer"
UNIQUE_ID_TUMBLE_PROGRAM = "{0}-tumble_program"
UNIQUE_ID_TUMBLE_CYCLE_STATUS = "{0}-tumble_cycle_status"
UNIQUE_ID_TUMBLE_REMAINING_TIME = "{0}-tumble_remaining_time"

UNIQUE_ID_OVEN = "{0}-oven"
UNIQUE_ID_OVEN_PROGRAM = "{0}-oven_program"
UNIQUE_ID_OVEN_TEMP = "{0}-oven-temp"
UNIQUE_ID_DISHWASHER = "{0}-dishwasher"
UNIQUE_ID_DISHWASHER_PROGRAM = "{0}-dishwasher_program"
UNIQUE_ID_DISHWASHER_REMAINING_TIME = "{0}-dishwasher_remaining_time"

DEVICE_NAME_WASHING_MACHINE = "Washing machine"
DEVICE_NAME_TUMBLE_DRYER = "Tumble dryer"
DEVICE_NAME_OVEN = "Oven"
DEVICE_NAME_DISHWASHER = "Dishwasher"

SUGGESTED_AREA_BATHROOM = "Bathroom"
SUGGESTED_AREA_KITCHEN = "Kitchen"
