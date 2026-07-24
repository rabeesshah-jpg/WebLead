from django.urls import path

from apps.whatsapp.api import SendWhatsAppMessageAPIView

urlpatterns = [
    path(
        "send/",
        SendWhatsAppMessageAPIView.as_view(),
        name="internal-whatsapp-send",
    ),
]
