from django.urls import path
from ozon.views import ozon_push
app_name = 'ozon'

urlpatterns = [
    path('push/', ozon_push, name='ozon_push'),
]