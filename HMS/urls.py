
from django.contrib import admin
from django.urls import path,include
from django.conf.urls.static import static
from HMS import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('hospital/',include('hospital.urls')),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
