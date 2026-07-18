
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import path,include
from django.conf.urls.static import static
from django.shortcuts import redirect
from HMS import settings


def favicon(request):
    # Resolved per-request, not at import time — static_url() reads
    # whitenoise's manifest.json in production (built by collectstatic),
    # which may not exist yet the instant the app boots. Evaluating this
    # eagerly as a urlpatterns argument would crash startup if collectstatic
    # hasn't run; a view function defers it until the first real request.
    return redirect(static_url('img/favicon.ico'), permanent=True)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('hospital/',include('hospital.urls')),
    path('api/', include('hospital.api.urls')),
    # Browsers request this path unprompted regardless of any <link rel="icon">
    # tag (or lack of one) — a single redirect here covers every template
    # without touching each one individually.
    path('favicon.ico', favicon),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
