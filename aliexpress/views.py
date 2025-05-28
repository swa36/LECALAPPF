from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
# Create your views here.

def feed_Ali(request):
    return HttpResponse(open(settings.BASE_DIR/ 'feed_for_marketplace' / 'ali.xml', encoding='utf-8').read(),
                        content_type='text/xml')