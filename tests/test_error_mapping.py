"""Тесты маппинга ошибок на русские сообщения."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))


def test_imap_unavailable():
    from handler import _humanize_error
    raw = b'[UNAVAILABLE] LOGIN internal server error sc=abc123'
    assert _humanize_error(str(raw)) == "Сервер почты недоступен, попробуйте позже"


def test_telegram_all_options_used():
    from handler import _humanize_error
    raw = "Returned when all available options for this type of number were already used"
    assert _humanize_error(raw) == "Слишком много попыток. Подождите 10 минут"


def test_phone_number_invalid():
    from handler import _humanize_error
    raw = "The phone number is invalid (caused by SendCodeRequest)"
    assert _humanize_error(raw) == "Неверный номер телефона"


def test_flood_wait():
    from handler import _humanize_error
    raw = "A wait of 120 seconds is required (caused by SendCodeRequest)"
    assert _humanize_error(raw) == "Подождите 2 мин"


def test_unknown_error_sanitized():
    from handler import _humanize_error
    raw = "SomeTelethonInternalDetail(param=secret123)"
    assert _humanize_error(raw) == "Ошибка сервера, попробуйте позже"


def test_auth_key_unregistered():
    from handler import _humanize_error
    raw = "session expired, re-auth needed"
    assert _humanize_error(raw) == "Сессия истекла, войдите заново"
