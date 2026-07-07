"""URL routes for qualification internal APIs."""

from django.urls import path

from apps.qualification.api.views import (
    ExtractAPIView,
    RenderAudioAPIView,
    VoiceCallCompletedAPIView,
)

urlpatterns = [
    path(
        "extract/",
        ExtractAPIView.as_view(),
        name="internal-qualification-extract",
    ),
    path(
        "render-audio/",
        RenderAudioAPIView.as_view(),
        name="internal-qualification-render-audio",
    ),
    path(
        "voice-call-completed/",
        VoiceCallCompletedAPIView.as_view(),
        name="internal-qualification-voice-call-completed",
    ),
]
