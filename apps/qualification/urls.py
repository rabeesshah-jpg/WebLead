from django.urls import path

from apps.qualification.api.views import ExtractAPIView, RenderAudioAPIView

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
]
