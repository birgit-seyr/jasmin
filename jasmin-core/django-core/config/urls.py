from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

# Main URL router - delegates to public_urls or tenant_urls based on schema
urlpatterns: list[path] = []

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
