import logging
from logging.config import dictConfig
import json
from re import fullmatch
from linuxtools import WORKING_DIR


class NoSocketIOMessages(logging.Filter):
    def filter(self, record):
        if 'socket.io' in record.msg:
            return False
        return True


def config_loggers(logger: logging.Logger, log_level: str) -> None:
    """
    Настраивает логирование

    :param logger: имя базового логгера
    :param log_level: уровень логирования
    :return: None
    """
    dictConfig({
        'version': 1,
        'disable_existing_loggers': False,

        'formatters': {
            'default_formatter': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%d/%m/%Y %H:%M:%S',
            },
            'journal_formatter': {
                "format": "%(asctime)s %(name)s: %(message)s",
                "datefmt": "%b %d %H:%M:%S",
            },
            'stream_formatter': {
                "format": "%(message)s",
                "datefmt": "%b %d %H:%M:%S",
            },
        },

        'filters': {
            'socketio': {
                '()': NoSocketIOMessages,
            },
        },

        'handlers': {
            'server.file.handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': '%s/logs/server.log' % WORKING_DIR,
                'maxBytes': 10000000,
                'backupCount': 5,
                'formatter': 'journal_formatter',
            },
            'app.file.handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': '%s/logs/app.log' % WORKING_DIR,
                'maxBytes': 10000000,
                'backupCount': 5,
                'formatter': 'journal_formatter',
            },
            'stream.handler': {
                'class': 'logging.StreamHandler',
                'formatter': 'stream_formatter',
            },
        },

        'loggers': {
            'werkzeug': {
                'level': 'INFO',
                'handlers': ['server.file.handler'],
                'propagate': False,
                'filters': ['socketio'],
            },
            'flask': {
                'level': 'CRITICAL',
                'handlers': ['stream.handler'],
            },
            'flask.app': {
                'level': 'CRITICAL',
                'handlers': ['stream.handler'],
            },
            '{}'.format(logger.name): {
                'level': '{}'.format(log_level.upper()),
                'handlers': ['stream.handler', 'app.file.handler'],
            },
            'engineio': {
                'level': 'CRITICAL',
                'handlers': ['stream.handler'],
            },
            'socketio': {
                'level': 'CRITICAL',
                'handlers': ['stream.handler'],
            },
        },
    })


def validate_ipv4(*args) -> bool:
    """
    Проверяет правильность формата ip адреса

    :param args: ip адреса для проверки
    :return: true - все адреса валидны, false - есть ошибка
    """
    for ipv4 in args:
        if fullmatch('(\d{1,3}[.]){3}\d{1,3}', ipv4) is None:
            return False
        for number in ipv4.split('.'):
            if not 0 <= int(number) <= 255:
                return False
    else:
        return True


def validate_mac(*macs) -> bool:
    """
    Проверяет правильность формата mac адреса

    :param macs: mac адреса для проверки
    :return: true - все адреса валидны, false - есть ошибка
    """
    for mac in macs:
        if fullmatch('([a-f0-9]{2}:){5}[a-f0-9]{2}', mac) is None:
            return False
    else:
        return True
