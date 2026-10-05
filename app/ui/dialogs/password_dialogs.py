from __future__ import annotations

from app.bootstrap import Services
from app.config.constants import MIN_PASSWORD_LENGTH
from app.security.auth import CurrentUser
from app.services.errors import ValidationError
from app.ui.widgets.forms import Field, FormDialog

PASSWORD_HELP = (f"At least {MIN_PASSWORD_LENGTH} characters, mixing at least two of: "
                 "lowercase, uppercase, digits, symbols.")


class ChangePasswordDialog(FormDialog):
    def __init__(self, parent, services: Services, user: CurrentUser, forced: bool = False):
        def submit(d):
            if d["new"] != d["confirm"]:
                raise ValidationError("New passwords do not match.")
            services.auth.change_password(user, d["old"], d["new"])
        intro = ("Your password was set by an administrator. Please choose your own password "
                 "to continue.") if forced else ""
        super().__init__(parent, "Change password", [
            Field("old", "Current password", "password", required=True),
            Field("new", "New password", "password", required=True, help=PASSWORD_HELP),
            Field("confirm", "Confirm new password", "password", required=True),
        ], on_submit=submit, intro=intro, submit_text="Change password")
