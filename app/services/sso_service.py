import os
from typing import Any

import httpx


SSO_SERVICE_URL = os.getenv(
    "SSO_SERVICE_URL",
    "http://localhost:8001",
)


class SSOServiceError(Exception):
    """Raised when SSO service communication fails."""


async def get_user_package(user_id: str) -> dict[str, Any]:
    """
    Fetch the user's package information from SSO service.
    """

    url = f"{SSO_SERVICE_URL}/user/{user_id}/package"

    try:
        async with httpx.AsyncClient(
            timeout=10.0
        ) as client:

            response = await client.get(url)

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                raise SSOServiceError(
                    "Invalid response received from SSO service"
                )

            return data

    except httpx.TimeoutException as exc:
        raise SSOServiceError(
            "SSO service request timed out"
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise SSOServiceError(
            f"SSO service returned status "
            f"{exc.response.status_code}"
        ) from exc

    except httpx.RequestError as exc:
        raise SSOServiceError(
            "Unable to connect to SSO service"
        ) from exc