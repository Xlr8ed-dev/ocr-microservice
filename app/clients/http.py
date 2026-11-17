import httpx

from app.config import settings


class ServiceClients:
    ai: httpx.AsyncClient | None = None
    sso: httpx.AsyncClient | None = None
    auth: httpx.AsyncClient | None = None
    email: httpx.AsyncClient | None = None
    whatsapp: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        common_limits = httpx.Limits(
            max_connections=50,
            max_keepalive_connections=10,
        )

        self.ai = httpx.AsyncClient(
            base_url=settings.AI_SERVICE_URL,
            timeout=settings.AI_SERVICE_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": settings.AI_SERVICE_API_KEY,
            },
            limits=common_limits,
        )

        self.sso = httpx.AsyncClient(
            base_url=settings.SSO_BASE_URL,
            timeout=settings.SSO_TIMEOUT,
            headers={"X-Service-Token": settings.SSO_SERVICE_TOKEN},
            limits=common_limits,
        )

        # No static Authorization header: the caller's own bearer token and
        # X-Device-Fingerprint are forwarded per request by
        # app.services.auth_service, so the auth service validates the real
        # user rather than this service acting as itself.
        self.auth = httpx.AsyncClient(
            base_url=settings.auth_service_base_url,
            timeout=settings.AUTH_SERVICE_TIMEOUT,
            limits=common_limits,
        )

        if settings.EMAIL_SERVICE_URL:
            self.email = httpx.AsyncClient(
                base_url=settings.EMAIL_SERVICE_URL,
                timeout=10.0,
                headers={"X-Service-Token": settings.EMAIL_SERVICE_TOKEN or ""},
            )

        if settings.WHATSAPP_SERVICE_URL:
            self.whatsapp = httpx.AsyncClient(
                base_url=settings.WHATSAPP_SERVICE_URL,
                timeout=10.0,
                headers={"X-Service-Token": settings.WHATSAPP_SERVICE_TOKEN or ""},
            )

    async def shutdown(self) -> None:
        for c in (self.ai, self.sso, self.auth, self.email, self.whatsapp):
            if c is not None:
                await c.aclose()


clients = ServiceClients()