from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """Limits login attempts per IP — the main brute-force protection
    point. Rate is set in settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    under the 'login' scope."""
    scope = "login"


class RegisterRateThrottle(AnonRateThrottle):
    """Limits account-creation attempts per IP, to slow down mass/scripted
    signups. Rate set under the 'register' scope."""
    scope = "register"
