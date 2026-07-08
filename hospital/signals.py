from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditLog, Bed, Department, Doctor, Drug, LabTest, Nurse, Service, User, Ward

# Models a Hospital Admin manages through the Django admin, linked from the
# admin dashboard's "Manage catalogs" card. AuditLog is deliberately excluded
# here — it gets view-only access below, since add/change are already
# blocked at the ModelAdmin level and delete is reserved for superusers
# (see AuditLogAdmin.has_delete_permission).
ADMIN_MANAGED_MODELS = [Department, Ward, Bed, Service, Drug, LabTest, User]

HOSPITAL_ADMINS_GROUP = "Hospital Admins"

# Maps a role to the profile model that should exist for a user with
# that role. Add an entry here (and a matching model) if another role
# ever needs its own profile table.
ROLE_PROFILE_MODELS = {
    User.Role.DOCTOR: Doctor,
    User.Role.NURSE: Nurse,
}


@receiver(post_save, sender=User)
def create_role_profile(sender, instance, created, **kwargs):
    """
    Ensure a role-specific profile (Doctor/Nurse) exists whenever a new
    User is created with that role.

    - `get_or_create` instead of `create` so this can never raise an
      IntegrityError on the OneToOneField if the signal is ever
      triggered more than once for the same user.
    - `transaction.on_commit` defers the profile creation until the
      outer transaction actually commits, so a User row is never left
      without its profile because something later in the same
      transaction rolled back.
    """
    if not created:
        return

    profile_model = ROLE_PROFILE_MODELS.get(instance.role)
    if profile_model is None:
        return

    transaction.on_commit(lambda: profile_model.objects.get_or_create(user=instance))


def _get_or_create_hospital_admins_group():
    """
    A group (not per-user permissions) so the permission set is defined once
    and every Hospital Admin stays in sync automatically, rather than each
    user's grant slowly drifting as models change.
    """
    group, _ = Group.objects.get_or_create(name=HOSPITAL_ADMINS_GROUP)

    permissions = []
    for model in ADMIN_MANAGED_MODELS:
        content_type = ContentType.objects.get_for_model(model)
        model_name = model._meta.model_name
        permissions += list(
            Permission.objects.filter(
                content_type=content_type,
                codename__in=[
                    f"view_{model_name}",
                    f"add_{model_name}",
                    f"change_{model_name}",
                    f"delete_{model_name}",
                ],
            )
        )

    audit_log_content_type = ContentType.objects.get_for_model(AuditLog)
    permissions += list(
        Permission.objects.filter(content_type=audit_log_content_type, codename="view_auditlog")
    )

    group.permissions.set(permissions)
    return group


@receiver(post_save, sender=User)
def grant_admin_staff_access(sender, instance, created, **kwargs):
    """
    ADMIN-role users manage catalogs (departments, wards, drugs, services,
    lab tests, staff accounts) through the Django admin via the admin
    dashboard's quick links, so they need `is_staff` plus the matching
    model permissions to actually use it — `is_staff` alone only grants
    the admin *login*, not access to any model within it.

    Runs on every save, not just creation, so promoting an existing user to
    ADMIN also grants access. Only ever grants — a role change away from
    ADMIN does not remove the user from the group or revoke `is_staff`,
    since that's a more sensitive action better left to an explicit choice
    in the Django admin.

    Uses `.update()` rather than `instance.save()` so this doesn't
    recursively re-trigger post_save.
    """
    if instance.role != User.Role.ADMIN:
        return

    if not instance.is_staff:
        User.objects.filter(pk=instance.pk).update(is_staff=True)

    group = _get_or_create_hospital_admins_group()
    instance.groups.add(group)