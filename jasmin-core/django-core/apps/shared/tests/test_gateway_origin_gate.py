"""The origin gate in nginx/nginx.conf.template: only the tenant hosts include
it, every tenant location that proxies drops the secret header before the
backend sees it, the deny map refuses what it should, and docker-compose.yml
ships it switched off.

CI's gateway job (scripts/check_gateway_config.sh) serves the rendered config
with the gate off and on; this reads the template, so a new tenant location
that forgets the header fails here without Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

DJANGO_CORE = Path(__file__).resolve().parents[3]
REPO_ROOT = DJANGO_CORE.parent.parent
TEMPLATE = REPO_ROOT / "nginx" / "nginx.conf.template"

STRIP = 'proxy_set_header X-Origin-Secret "";'
GATE_INCLUDE = "include /etc/nginx/origin_gate/tenant.conf;"


def _config() -> str:
    if not TEMPLATE.is_file():
        pytest.skip("nginx/nginx.conf.template is not in this checkout")
    return re.sub(r"#.*$", "", TEMPLATE.read_text(encoding="utf-8"), flags=re.MULTILINE)


def _blocks(config: str, opener: str) -> list[str]:
    """The bodies of every ``<opener> { ... }`` block, nested blocks included."""
    bodies = []
    for match in re.finditer(opener + r"\s*\{", config):
        depth, start = 1, match.end()
        for index in range(start, len(config)):
            if config[index] == "{":
                depth += 1
            elif config[index] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(config[start:index])
                    break
    return bodies


def _normalized(body: str) -> str:
    return " ".join(body.split())


def _https_server(config: str, server_name: str) -> str:
    matches = [
        body
        for body in _blocks(config, r"\bserver")
        if f"server_name {server_name};" in _normalized(body)
        and "listen 443" in _normalized(body)
    ]
    assert len(matches) == 1, f"expected one HTTPS server block for {server_name}"
    return matches[0]


class TestTenantBlock:
    def test_includes_the_gate(self):
        assert GATE_INCLUDE in _normalized(
            _https_server(_config(), "*.${FRONTEND_DOMAIN}")
        )

    @pytest.mark.parametrize(
        "server_name",
        ["${FRONTEND_DOMAIN}", "${SUPER_ADMIN_SUBDOMAIN}.${FRONTEND_DOMAIN}"],
    )
    def test_the_hosts_reached_directly_have_no_gate(self, server_name):
        assert GATE_INCLUDE not in _normalized(_https_server(_config(), server_name))

    def test_every_proxying_location_drops_the_secret(self):
        tenant = _https_server(_config(), "*.${FRONTEND_DOMAIN}")
        proxying = [
            body
            for body in _blocks(tenant, r"\blocation[^{;]*")
            if "proxy_pass" in body
        ]
        assert len(proxying) >= 10
        for body in proxying:
            assert STRIP in _normalized(body), _normalized(body)


class TestDenyMap:
    def _deny(self, secret_ok: str, uri: str) -> str:
        bodies = _blocks(
            _config(), r'\bmap\s+"\$origin_secret_ok:\$uri"\s+\$origin_gate_deny'
        )
        assert len(bodies) == 1
        entries = re.findall(r"^\s*(\S+)\s+(\S+)\s*;", bodies[0], re.MULTILINE)
        default = dict(entries)["default"]
        for key, value in entries:
            if key.startswith("~") and re.search(key[1:], f"{secret_ok}:{uri}"):
                return value
        return default

    @pytest.mark.parametrize(
        "uri", ["/", "/api/auth/login/", "/media/a.pdf", "/health/"]
    )
    def test_a_request_with_an_accepted_secret_passes(self, uri):
        assert self._deny("1", uri) == "0"

    @pytest.mark.parametrize(
        "uri", ["/", "/api/", "/media/a.pdf", "/healthz", "/x/health/"]
    )
    def test_a_request_without_one_is_refused(self, uri):
        assert self._deny("0", uri) == "1"

    def test_health_passes_without_one(self):
        assert self._deny("0", "/health/") == "0"
        assert self._deny("0", "/health/ready/") == "0"

    def test_the_secrets_come_only_from_the_rendered_file(self):
        bodies = _blocks(
            _config(), r"\bmap\s+\$http_x_origin_secret\s+\$origin_secret_ok"
        )
        assert len(bodies) == 1
        assert _normalized(bodies[0]) == (
            "default 0; include /etc/nginx/origin_gate/secrets.conf;"
        )


def test_compose_ships_the_gate_off():
    # A default secret would switch the gate on before Bunny sends it, and every
    # tenant request would get no answer.
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.is_file():
        pytest.skip("docker-compose.yml is not in this checkout")
    environment = yaml.safe_load(compose.read_text())["services"]["gateway"][
        "environment"
    ]
    assert environment["BUNNY_ORIGIN_SECRET"] == "${BUNNY_ORIGIN_SECRET:-}"
    assert environment["BUNNY_ORIGIN_SECRET_NEXT"] == "${BUNNY_ORIGIN_SECRET_NEXT:-}"
