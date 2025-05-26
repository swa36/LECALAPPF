from django.urls import path
from avito.views import *
app_name = 'avito'

urlpatterns = [
    path('avito_feed/', feed_avito, name='AvitoFeed'),
    path('avito_stock/', feed_avito_stock, name='AvitoFeedStock'),
]
