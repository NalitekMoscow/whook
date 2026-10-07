"""
Вспомогательный скрипт для генерации Django-миграций библиотеки `whook`.

Библиотека поставляет свои миграции, но не имеет ни `manage.py`,
ни запускаемого Django-проекта. Этот скрипт поднимает минимальное
Django-окружение с SQLite в памяти (`:memory:`), чтобы можно было
запустить `makemigrations`, не трогая реальную базу данных.

Запуск:
    poetry run python make_migrations_script.py
"""

import django
from django.conf import settings

settings.configure(
    DEBUG=True,
    SECRET_KEY='fake-key-for-migrations',
    INSTALLED_APPS=[
        'django.contrib.contenttypes',
        'django.contrib.auth',
        'whook',
    ],
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    },
    DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
)

django.setup()

from django.core.management import call_command
call_command('makemigrations', 'whook')
