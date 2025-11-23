from django.urls import path
from yamarket.views import updateStock, newOrder, statusOrder,getNotifyYaMarket

app_name = 'yaMarket'

urlpatterns = [
    path('stocks', updateStock, name='updateStockYaMarket'),
    path('order/accept', newOrder, name='newOrder'),
    path('order/status', statusOrder, name='newOrder'),
    path('notyify/', getNotifyYaMarket, name='notifyYaMarket'),

]