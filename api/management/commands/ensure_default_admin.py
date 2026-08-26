from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Idempotently provision the temporary appliance administrator."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default=None)

    def handle(self, *args, **options) -> None:
        username = str(options["username"]).strip()
        password = options["password"] or os.environ.get(
            "OPEN_CINEMA_DEFAULT_ADMIN_PASSWORD",
            "admin",
        )
        if not username:
            raise CommandError("The default administrator username must not be empty.")
        if not password:
            raise CommandError("The default administrator password must not be empty.")

        user_model = get_user_model()
        user, created = user_model._default_manager.get_or_create(
            **{user_model.USERNAME_FIELD: username}
        )
        changed_fields: set[str] = set()
        for field in ("is_active", "is_staff", "is_superuser"):
            if not getattr(user, field):
                setattr(user, field, True)
                changed_fields.add(field)
        if not user.check_password(password):
            user.set_password(password)
            changed_fields.add("password")

        if changed_fields:
            user.save(update_fields=sorted(changed_fields))

        state = "created" if created else "updated" if changed_fields else "unchanged"
        self.stdout.write(f"Default administrator {username!r}: {state}.")
