import json
import logging
from datetime import UTC, datetime


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        item = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ["method", "path", "status_code", "duration_ms", "request_id"]:
            if hasattr(record, field):
                item[field] = getattr(record, field)
        # Never serialize record.__dict__, request bodies, credentials or SQL exception parameters.
        return json.dumps(item, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("photoprint")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJsonFormatter())
        logger.addHandler(handler)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
