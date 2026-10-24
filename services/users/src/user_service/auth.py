"""Политики авторизации методов user-service (ТЗ 6.0, 6.1)."""

from stand_core.grpc import AuthPolicy

USER_SERVICE = "/users.v1.UserService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{USER_SERVICE}/SignUp": AuthPolicy.SERVICE,
    f"{USER_SERVICE}/ConfirmEmail": AuthPolicy.SERVICE,
    f"{USER_SERVICE}/SignIn": AuthPolicy.SERVICE,
    f"{USER_SERVICE}/SignOut": AuthPolicy.USER,
    f"{USER_SERVICE}/GetMe": AuthPolicy.USER,
    f"{USER_SERVICE}/UpdateProfile": AuthPolicy.USER,
    f"{USER_SERVICE}/LegacyResetPassword": AuthPolicy.SERVICE,
}
