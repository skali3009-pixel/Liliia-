"""Тесты правовых документов и согласия (services/legal.py)."""

import pytest

import config
from services.legal import DOCUMENTS, LEGAL_VERSION, document_url, links_ready, render


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_OWNER", "ИП Иванова И. И.")
    monkeypatch.setattr(config, "LEGAL_REQUISITES", "ИНН 123456789012, ОГРНИП 000")
    monkeypatch.setattr(config, "LEGAL_EMAIL", "hello@example.com")
    monkeypatch.setattr(config, "BOT_USERNAME", "test_bot")
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com")


@pytest.mark.parametrize("slug", sorted(DOCUMENTS))
def test_every_document_renders(slug):
    page = render(slug)
    assert page and page.startswith("<!DOCTYPE html>")
    assert DOCUMENTS[slug].title in page


@pytest.mark.parametrize("slug", sorted(DOCUMENTS))
def test_no_placeholder_survives_rendering(slug):
    """Незаполненная метка в оферте — это провал: документ станет недействительным."""
    page = render(slug)
    assert "{{" not in page and "}}" not in page


@pytest.mark.parametrize("slug", sorted(DOCUMENTS))
def test_owner_details_are_substituted(slug):
    page = render(slug)
    assert "ИП Иванова И. И." in page
    assert "hello@example.com" in page
    assert "@test_bot" in page


def test_version_is_shown_to_the_reader():
    assert LEGAL_VERSION in render("offer")


def test_offer_states_it_is_not_medical():
    """Дисклеймер обязан быть в оферте, а не только на словах в чате."""
    page = render("offer").lower()
    assert "не оказывает медицинских услуг" in page
    assert "врача" in page


def test_privacy_lists_who_gets_the_data():
    page = render("privacy")
    for company in ("Telegram", "Anthropic", "Groq"):
        assert company in page
    assert "Трансграничная передача" in page


def test_privacy_marks_health_data_as_special():
    assert "состояни" in render("privacy").lower()
    assert "специальная категория" in render("consent").lower()


def test_marketing_consent_is_voluntary():
    """Согласие на рекламу нельзя делать условием доступа — так и написано."""
    page = render("marketing").lower()
    assert "добровольное" in page
    assert "отказ ни на что не влияет" in page


def test_unknown_document_is_not_rendered():
    assert render("secret") is None
    assert render("") is None


def test_document_links_point_to_the_public_address():
    assert document_url("offer") == "https://example.com/legal/offer"
    assert links_ready() is True


def test_links_are_not_offered_without_a_public_address(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert links_ready() is False


def test_the_owner_name_never_stands_where_it_would_need_declining():
    """Имя владельца — одна строка, а русский язык склоняет.

    В документах было «является публичной офертой Индивидуальный
    предприниматель Иванова» и «рекламного характера от Индивидуальный
    предприниматель Иванова»: обе фразы требуют родительного падежа, а
    подставляется всегда именительный. Склонять строку нельзя — она бывает
    и фамилией, и «ООО «Аура»».

    Поэтому правило простое: {{OWNER}} стоит либо сразу после тега (то есть
    первым в строке или абзаце), либо после тире. И то и другое в русском
    требует именительного падежа, и подстановка читается при любой форме
    владельца — хоть фамилией, хоть «ООО «Аура»».
    """
    import re
    from pathlib import Path

    from services.legal import LEGAL_DIR

    allowed = re.compile(r"(?:>|—)\s*$")
    for path in sorted(Path(LEGAL_DIR).glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{\{OWNER\}\}", text):
            before = text[:match.start()]
            assert allowed.search(before), (
                f"{path.name}: имя владельца стоит в позиции, где его надо было бы "
                f"склонять — «…{before[-60:].strip()} {{{{OWNER}}}}»"
            )


@pytest.mark.parametrize("owner", [
    "Иванова Лилия Сергеевна",
    "Индивидуальный предприниматель Иванова Лилия Сергеевна",
    "Общество с ограниченной ответственностью «Аура»",
])
def test_documents_read_correctly_for_any_form_of_owner(monkeypatch, owner):
    """Самозанятая, ИП и общество — три разные строки, и все должны читаться."""
    monkeypatch.setattr(config, "LEGAL_OWNER", owner)
    for slug in ("offer", "marketing"):
        page = render(slug)
        assert owner in page
        # Ровно то, что было сломано: предлог или творительный падеж вплотную
        # перед именем владельца.
        assert f"офертой {owner}" not in page
        assert f"от {owner}" not in page
