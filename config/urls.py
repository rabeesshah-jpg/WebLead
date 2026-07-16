from django.urls import include, path

from apps.qualification import media_views

urlpatterns = [
    path("api/webhooks/", include("apps.webhooks.urls")),
    path("api/internal/qualification/", include("apps.qualification.urls")),
    path(
        "media/whatsapp_voice_replies/<uuid:audio_id>/",
        media_views.whatsapp_voice_reply_media,
        name="whatsapp-voice-reply-media",
    ),
]
