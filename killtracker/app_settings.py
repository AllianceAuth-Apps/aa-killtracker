"""Settings for killtracker."""

from app_utils.app_settings import clean_setting

KILLTRACKER_REDISQ_LOCK_TIMEOUT = clean_setting("KILLTRACKER_REDISQ_LOCK_TIMEOUT", 5)
"""Timeout for lock to ensure atomic access to ZKB RedisQ."""

KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER = clean_setting(
    "KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER", 60
)
"""Ignore killmails that are older than the given number in minutes
sometimes killmails appear belated on ZKB,
this feature ensures they don't create new alerts.
"""

KILLTRACKER_MAX_KILLMAILS_PER_RUN = clean_setting(
    "KILLTRACKER_MAX_KILLMAILS_PER_RUN", 200
)
"""Maximum number of killmails retrieved from ZKB by task run."""

KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS = clean_setting(
    "KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 30
)
"""Killmails older than set number of days will be purged from the database.
If you want to keep all killmails set this to 0.
"""

KILLTRACKER_QUEUE_ID = clean_setting("KILLTRACKER_QUEUE_ID", "")
"""Unique ID used to identify this server when fetching killmails from zKillboard.

Please note that the queue ID must be globally unique for all users of the zKillboard API, so choose carefully.

We recommend using only characters (upper and lower case) and numbers,
but no spaces or any special characters when choosing your ID.

Example: ``"Voltron9000"`` (don't use this exact example)

We suggest to use your alliance or corporation name (without spaces and special characters) as queue ID.

If you are running multiple instances of Killtracker please choose a different queue ID for each of them.

This setting is mandatory.
"""


KILLTRACKER_STORING_KILLMAILS_ENABLED = clean_setting(
    "KILLTRACKER_STORING_KILLMAILS_ENABLED", False
)
"""Whether killmails retrieved from ZKB are stored in the database."""

KILLTRACKER_WEBHOOK_SET_AVATAR = clean_setting("KILLTRACKER_WEBHOOK_SET_AVATAR", True)
"""Wether app sets the name and avatar icon of a webhook.
When False the webhook will use it's own values as set on the platform.
"""

KILLTRACKER_SHOW_NPC_TYPES = clean_setting("KILLTRACKER_SHOW_NPC_TYPES", True)
"""Wether NPC types (e.g. Guristas Assaulter) can be selected as attacker types
when creating trackers.
"""


#####################
# INTERNAL SETTINGS

KILLTRACKER_REDISQ_TTW = clean_setting("KILLTRACKER_REDISQ_TTW", 5)
"""Max duration to wait for new killmails from redisq in seconds."""

KILLTRACKER_TASKS_TIMEOUT = clean_setting("KILLTRACKER_TASKS_TIMEOUT", 1_800)
"""Tasks hard timeout."""

KILLTRACKER_DISCORD_SEND_DELAY = clean_setting(
    "KILLTRACKER_DISCORD_SEND_DELAY", default_value=2, min_value=1, max_value=900
)
"""Delay in seconds between every message sent to Discord
this needs to be >= 1 to prevent 429 Too Many Request errors.
"""

KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES = clean_setting(
    "KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES", 3
)
"""Maximum retries when generating a message from a killmail."""

KILLTRACKER_GENERATE_MESSAGE_RETRY_COUNTDOWN = clean_setting(
    "KILLTRACKER_GENERATE_MESSAGE_RETRY_COUNTDOWN", 10
)
"""Delay when retrying to generate a message in seconds."""

KILLTRACKER_TASK_OBJECTS_CACHE_TIMEOUT = clean_setting(
    "KILLTRACKER_TASK_OBJECTS_CACHE_TIMEOUT", 60
)
"""Cache duration for objects in tasks in seconds."""

KILLTRACKER_TASK_MINIMUM_RETRY_DELAY = clean_setting(
    "KILLTRACKER_TASK_MINIMUM_RETRY_DELAY", default_value=0.05
)
"""Minimum delay when retrying a task."""

KILLTRACKER_STORAGE_KILLMAILS_LIFETIME = clean_setting(
    "KILLTRACKER_STORAGE_KILLMAILS_LIFETIME", 3_600 * 1
)
"""Max lifetime of killmails in temporary storage in seconds."""
