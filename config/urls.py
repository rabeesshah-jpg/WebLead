from django.urls import include, path

urlpatterns = [
    path("api/webhooks/", include("apps.webhooks.urls")),
]
