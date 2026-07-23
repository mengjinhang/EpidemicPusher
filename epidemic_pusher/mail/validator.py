import re
import logging

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

COMMON_DOMAINS = {
    "qq.com", "163.com", "126.com", "yeah.net",
    "gmail.com", "outlook.com", "hotmail.com",
    "foxmail.com", "sina.com", "sohu.com",
    "139.com", "189.cn", "wo.cn",
    "edu.cn",
}

DISPOSABLE_DOMAINS = {
    "tempmail.com", "guerrillamail.com", "mailinator.com",
    "throwaway.email", "temp-mail.org", "fakeinbox.com",
}


class EmailValidationError(Exception):
    def __init__(self, email, reason):
        self.email = email
        self.reason = reason
        super().__init__(f"邮箱验证失败 [{email}]: {reason}")


class EmailValidator:

    @staticmethod
    def validate_format(email):
        if not email or not isinstance(email, str):
            raise EmailValidationError(email, "邮箱地址不能为空")

        email = email.strip().lower()

        if len(email) > 254:
            raise EmailValidationError(email, "邮箱地址长度超过254个字符")

        if not EMAIL_REGEX.match(email):
            raise EmailValidationError(email, "邮箱格式不正确")

        local_part, domain = email.rsplit("@", 1)

        if len(local_part) > 64:
            raise EmailValidationError(email, "邮箱用户名部分超过64个字符")

        if ".." in email:
            raise EmailValidationError(email, "邮箱地址包含连续的点号")

        return email

    @staticmethod
    def validate_domain(email):
        _, domain = email.rsplit("@", 1)

        if domain in DISPOSABLE_DOMAINS:
            raise EmailValidationError(email, f"不支持临时邮箱域名 {domain}")

        if "." not in domain:
            raise EmailValidationError(email, "邮箱域名格式不正确")

        return True

    @classmethod
    def validate(cls, email):
        email = cls.validate_format(email)
        cls.validate_domain(email)
        return email

    @classmethod
    def validate_batch(cls, emails):
        results = {"valid": [], "invalid": []}
        seen = set()

        for email in emails:
            try:
                validated = cls.validate(email)
                if validated in seen:
                    results["invalid"].append({
                        "email": email,
                        "reason": "重复的邮箱地址",
                    })
                else:
                    seen.add(validated)
                    results["valid"].append(validated)
            except EmailValidationError as e:
                results["invalid"].append({
                    "email": e.email,
                    "reason": e.reason,
                })

        logger.info(
            "批量验证完成: 有效 %d, 无效 %d",
            len(results["valid"]),
            len(results["invalid"]),
        )
        return results

    @staticmethod
    def is_edu_email(email):
        _, domain = email.rsplit("@", 1)
        return domain.endswith(".edu") or domain.endswith(".edu.cn")

    @staticmethod
    def get_domain(email):
        return email.rsplit("@", 1)[1]

    @staticmethod
    def mask_email(email):
        local, domain = email.rsplit("@", 1)
        if len(local) <= 2:
            masked_local = local[0] + "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
