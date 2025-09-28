import logging
import logging.config
import os
from pathlib import Path


def setup_logging() -> None:
    Path('logs').mkdir(exist_ok=True)
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': os.getenv('LOG_LEVEL', 'INFO'),
                'formatter': 'standard'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'standard',
                'filename': 'logs/shopping-agent.log',
                'maxBytes': 10 * 1024 * 1024,
                'backupCount': 3
            }
        },
        'loggers': {
            '': {
                'handlers': ['console', 'file'],
                'level': os.getenv('LOG_LEVEL', 'INFO')
            }
        }
    }
    logging.config.dictConfig(config)


