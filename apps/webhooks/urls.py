from django.urls import path

from apps.webhooks import views

urlpatterns = [
    path(
        "twilio/whatsapp-inbound/",
        views.twilio_whatsapp_inbound,
        name="twilio-whatsapp-inbound",
    ),
]
