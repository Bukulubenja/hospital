"""
Multi-tenant support: every hospital organization on this deployment is a
`Hospital` row, and every tenant-scoped model carries a `hospital` FK.

`TenantMiddleware` (see middleware.py) resolves the current request's
Hospital from its subdomain and stores it in the `_current_hospital`
contextvar for the duration of the request. `TenantModel` (the abstract
base every tenant-scoped model inherits) uses that contextvar to:

  - auto-scope `Model.objects` to the current hospital (TenantManager)
  - auto-populate `hospital` on save if not already set

This keeps tenant-safety in the model layer rather than requiring every
view/service call site to remember to filter by hospital.
"""

import contextvars

from django.db import models

_current_hospital = contextvars.ContextVar("current_hospital", default=None)


def set_current_hospital(hospital):
    return _current_hospital.set(hospital)


def get_current_hospital():
    return _current_hospital.get()


def reset_current_hospital(token):
    _current_hospital.reset(token)


class TenantManager(models.Manager):
    """
    Default manager for tenant-scoped models — always filters to the
    current request's hospital (via the contextvar), including filtering
    to "no hospital" when none is set (the platform/no-subdomain path).
    There is deliberately no unscoped fallback here; `all_objects` below
    is the only sanctioned way to see across tenants.
    """

    def get_queryset(self):
        return super().get_queryset().filter(hospital=get_current_hospital())


class TenantModel(models.Model):
    """
    Abstract base for every tenant-scoped model. Adds a `hospital` FK,
    auto-populated on save from the current request's tenant context if
    not already set — this covers `Model.objects.create(...)`,
    `get_or_create(...)`, and every `ModelForm.save()` in the codebase
    without needing changes at those call sites.
    """

    hospital = models.ForeignKey(
        "hospital.Hospital", on_delete=models.CASCADE, related_name="+"
    )

    objects = TenantManager()
    all_objects = models.Manager()  # explicit cross-tenant escape hatch — shell/mgmt-command use only

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.hospital_id is None:
            self.hospital = get_current_hospital()
        super().save(*args, **kwargs)
