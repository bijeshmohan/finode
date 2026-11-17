"""What the finode app sends to /api/auth and gets back: sign-in, sign-up, password reset and the session."""

from datetime import date

from pydantic import BaseModel


class AuthOptions(BaseModel):
    """What the sign-in screens offer on this server."""

    signup_enabled: bool
    reset_enabled: bool
    test_notice: bool


class SessionRead(BaseModel):
    """Who is signed in, and today's date where finode's people live (FINODE_TIMEZONE), never the phone's clock."""

    email: str | None
    today: date
    feedback_url: str | None
    can_delete_login: bool


class SignIn(BaseModel):
    email: str
    password: str


class SignUp(BaseModel):
    email: str = ""
    password: str = ""
    confirm_password: str = ""
    invite_code: str = ""
    # Ticked the test notice (only asked when FINODE_TEST_NOTICE is on).
    accept: bool = False


class SignUpResult(BaseModel):
    # False: the account was made but signing in failed; the app asks the person to sign in.
    signed_in: bool


class ForgotPassword(BaseModel):
    email: str = ""


class ResetPassword(BaseModel):
    token_hash: str = ""
    password: str = ""
    confirm_password: str = ""
