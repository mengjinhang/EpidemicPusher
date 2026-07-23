import pytest

from epidemic_pusher.mail.validator import EmailValidator, EmailValidationError


class TestEmailValidator:

    def test_valid_email(self):
        assert EmailValidator.validate("test@example.com") == "test@example.com"

    def test_valid_email_uppercase(self):
        assert EmailValidator.validate("Test@Example.COM") == "test@example.com"

    def test_valid_email_with_dots(self):
        assert EmailValidator.validate("first.last@example.com") == "first.last@example.com"

    def test_valid_email_with_plus(self):
        assert EmailValidator.validate("user+tag@example.com") == "user+tag@example.com"

    def test_invalid_empty(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate("")

    def test_invalid_none(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate(None)

    def test_invalid_no_at(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate("userexample.com")

    def test_invalid_double_dots(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate("user..name@example.com")

    def test_invalid_no_domain_dot(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate("user@localhost")

    def test_disposable_domain(self):
        with pytest.raises(EmailValidationError):
            EmailValidator.validate("user@tempmail.com")

    def test_batch_validate(self):
        emails = [
            "valid@example.com",
            "also.valid@example.com",
            "invalid",
            "valid@example.com",  # duplicate
            "bad@tempmail.com",   # disposable
        ]
        result = EmailValidator.validate_batch(emails)
        assert len(result["valid"]) == 2
        assert len(result["invalid"]) == 3

    def test_mask_email_short(self):
        assert EmailValidator.mask_email("ab@example.com") == "a*@example.com"

    def test_mask_email_long(self):
        masked = EmailValidator.mask_email("username@example.com")
        assert masked.startswith("u")
        assert masked.endswith("e@example.com")
        assert "*" in masked

    def test_is_edu_email(self):
        assert EmailValidator.is_edu_email("user@pku.edu.cn")
        assert EmailValidator.is_edu_email("user@mit.edu")
        assert not EmailValidator.is_edu_email("user@gmail.com")

    def test_get_domain(self):
        assert EmailValidator.get_domain("user@example.com") == "example.com"
