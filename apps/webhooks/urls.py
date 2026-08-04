from django.urls import path

from apps.webhooks import views


urlpatterns = [
    path(
        "twilio/whatsapp-inbound/",
        views.twilio_whatsapp_inbound,
        name="twilio-whatsapp-inbound",
    ),

    path(
        "ultramsg/whatsapp-inbound/",
        views.ultramsg_whatsapp_inbound,
        name="ultramsg-whatsapp-inbound",
    ),

    path(
        "ghl/whatsapp-inbound/",
        views.ghl_whatsapp_inbound,
        name="ghl-whatsapp-inbound",
    ),
]