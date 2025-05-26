from django.http import HttpResponse
from django.conf import settings


# Create your views here.
def feed_avito(request):
    return HttpResponse(open(settings.BASE_DIR / "feed_for_marketplace" / "avito.xml", encoding='utf-8').read(),
                        content_type='text/xml')

def feed_avito_stock(request):
    return HttpResponse(open(settings.BASE_DIR / "feed_for_marketplace" / "avito_stock.xml", encoding='utf-8').read(),
                        content_type='text/xml')