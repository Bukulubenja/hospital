from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Doctor, Nurse, User

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