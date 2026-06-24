from django.urls import path

from apps.qualification import render_audio_views, views

urlpatterns = [
    path(
        "extract/",
        views.internal_qualification_extract,
        name="internal-qualification-extract",
    ),
    path(
        "render-audio/",
        render_audio_views.internal_render_audio,
        name="internal-qualification-render-audio",
    ),
]
