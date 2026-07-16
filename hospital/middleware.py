from django.conf import settings
from django.shortcuts import render

from .models import Hospital
from .tenancy import reset_current_hospital, set_current_hospital


class TenantMiddleware:
    """
    Resolves the current request's Hospital from its subdomain and makes it
    available as `request.hospital` and via the `tenancy` contextvar (which
    is what TenantModel's manager/save() actually read).

    Must run before anything touches the ORM — in particular before
    AuthenticationMiddleware, since login/session user lookups need to
    already be scoped to the resolved hospital.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        base = settings.BASE_DOMAIN.split(":")[0]

        subdomain = None
        if host.endswith("." + base):
            subdomain = host[: -(len(base) + 1)]

        hospital = None
        if subdomain:
            hospital = Hospital.objects.filter(subdomain=subdomain, is_active=True).first()
            if hospital is None:
                return render(request, "tenant_not_found.html", status=404)

        request.hospital = hospital
        token = set_current_hospital(hospital)
        try:
            return self.get_response(request)
        finally:
            reset_current_hospital(token)
