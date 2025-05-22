import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lekala_ppf.settings')  # замени на имя своего проекта

app = Celery('lekala_ppf')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()