"""
URL configuration for lekala_ppf project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    # С Ozon сейчас не работаем: push-уведомления создавали бы заказы,
    # которые потом уходят в 1С. Вернуть — раскомментировать.
    # path('ozon/', include('ozon.urls', namespace='ozon')),
    path('avito/', include('avito.urls', namespace='avito')),
    path('ali/', include('aliexpress.urls', namespace='aliexpress')),
    # С Яндекс.Маркетом не работаем: order/accept и notify создавали бы
    # заказы, которые потом уходят в 1С. Вернуть — раскомментировать.
    # path('yamarket/', include('yamarket.urls', namespace='yamarket')),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)