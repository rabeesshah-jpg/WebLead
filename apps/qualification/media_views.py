"""Public WhatsApp voice reply media serving."""

from __future__ import annotations

from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotFound

from apps.qualification.whatsapp_audio import (
    _file_is_expired,
    find_audio_file,
    is_valid_audio_id,
)


from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "HEAD"])
def whatsapp_voice_reply_media(request: HttpRequest, audio_id: object) -> HttpResponse:
    """Serve generated WhatsApp voice reply audio without internal auth."""
    audio_id_str = str(audio_id)
    if not is_valid_audio_id(audio_id_str):
        return HttpResponseNotFound()

    audio_path = find_audio_file(audio_id_str)
    if audio_path is None or not audio_path.is_file():
        return HttpResponseNotFound()

    if _file_is_expired(audio_path):
        audio_path.unlink(missing_ok=True)
        return HttpResponseNotFound()

    if request.method == "HEAD":
        response = HttpResponse(content_type="audio/ogg")
        response["Content-Length"] = str(audio_path.stat().st_size)
        return response

    return FileResponse(
        audio_path.open("rb"),
        content_type="audio/ogg",
        as_attachment=False,
    )
