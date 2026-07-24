from django.urls import path

from apps.webhooks import views

urlpatterns = [
    path(
        "waha/whatsapp-inbound/",
        views.waha_whatsapp_inbound,
        name="waha-whatsapp-inbound",
    ),
]
