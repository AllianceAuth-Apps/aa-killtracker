import logging

from app_utils.allianceauth import get_redis_client

logger = logging.getLogger(__name__)


def reset_celery_once_locks():
    """Reset celery once locks for given tasks."""
    r = get_redis_client()
    app_label = "killtracker"
    if keys := r.keys(f":?:qo_{app_label}.*"):
        deleted_count = r.delete(*keys)
        logger.info("Removed %d stuck celery once keys", deleted_count)
    else:
        deleted_count = 0
