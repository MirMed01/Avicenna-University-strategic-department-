"""Политика безопасности содержимого (ASVS 14.4.3): браузер выполняет только скрипты и стили с нашего адреса.

Скриптов в программе нет; стили — свой файл и атрибуты style в шаблонах; картинки QR и значки — встроенные.
"""

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def content_security_policy(get_response):
    def middleware(request):
        response = get_response(request)
        response.setdefault("Content-Security-Policy", CSP)
        return response

    return middleware
