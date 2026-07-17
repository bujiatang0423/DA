from ipaddress import ip_address


def is_loopback(host: str) -> bool:
    normalized_host = host.strip().lower()
    if normalized_host == "localhost":
        return True

    try:
        return ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def validate_security(
    bind_host: str,
    authentication_enabled: bool,
    allowed_origins: tuple[str, ...],
) -> None:
    if not is_loopback(bind_host):
        if authentication_enabled:
            explanation = "remote authentication is not implemented"
        else:
            explanation = "authentication is disabled"
        raise ValueError(f"non-loopback bind_host is rejected because {explanation}")

    if "*" in allowed_origins:
        raise ValueError("wildcard allowed origin is not permitted")
