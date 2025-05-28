from django.urls import path, include, re_path
from aliexpress.views import feed_Ali


app_name = 'aliexpress'
urlpatterns = [
    path('ali_feed/', feed_Ali, name='AliFeed' )
]

