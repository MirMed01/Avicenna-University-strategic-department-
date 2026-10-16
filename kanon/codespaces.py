"""GitHub Codespaces: адрес программы узнаём из переменных, которые GitHub задаёт в каждом Codespace сам.

Дефект 16.10.2026: Codespace, созданный до правки .devcontainer/devcontainer.json, живёт со старыми переменными
(настройки контейнера применяются только при его создании) — вход отклонялся как «чужая форма» (CSRF, Origin).
Теперь адрес …app.github.dev доверенный в любом Codespace, без пересоздания. Только в режиме разработки.
"""


def settings_from_env(env):
    """(хосты, доверенные адреса, нужно ли верить X-Forwarded-Host) или None, если это не Codespaces."""
    if env.get("CODESPACES") != "true":
        return None
    domain = env.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev"
    # Прокси Codespaces присылает форму то с внешним адресом, то с Origin http(s)://localhost:8000 (снимок 16.10.2026).
    return [f".{domain}"], [f"https://*.{domain}", "https://localhost:8000", "http://localhost:8000"], True
