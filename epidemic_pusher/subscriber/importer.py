import os
import csv
import logging

from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Group
from epidemic_pusher.mail.validator import EmailValidator, EmailValidationError

logger = logging.getLogger(__name__)


class ImportError_(Exception):
    pass


class ImportResult:

    def __init__(self):
        self.success_count = 0
        self.skip_count = 0
        self.fail_count = 0
        self.errors = []

    def add_success(self):
        self.success_count += 1

    def add_skip(self, email, reason):
        self.skip_count += 1
        self.errors.append({"email": email, "reason": reason, "type": "skip"})

    def add_fail(self, email, reason):
        self.fail_count += 1
        self.errors.append({"email": email, "reason": reason, "type": "fail"})

    def to_dict(self):
        return {
            "success_count": self.success_count,
            "skip_count": self.skip_count,
            "fail_count": self.fail_count,
            "total": self.success_count + self.skip_count + self.fail_count,
            "errors": self.errors,
        }


class SubscriberImporter:

    REQUIRED_FIELDS = {"name", "email"}
    OPTIONAL_FIELDS = {"group", "remark"}

    @classmethod
    def import_csv(cls, file_path, default_group_id=None):
        if not os.path.isfile(file_path):
            raise ImportError_(f"文件不存在: {file_path}")

        result = ImportResult()

        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)

                if not reader.fieldnames:
                    raise ImportError_("CSV 文件为空或格式错误")

                headers = {h.strip().lower() for h in reader.fieldnames}
                missing = cls.REQUIRED_FIELDS - headers
                if missing:
                    raise ImportError_(f"CSV 缺少必要列: {', '.join(missing)}")

                for row_num, row in enumerate(reader, start=2):
                    cls._import_row(row, row_num, default_group_id, result)

        except UnicodeDecodeError:
            with open(file_path, "r", encoding="gbk") as f:
                reader = csv.DictReader(f)
                for row_num, row in enumerate(reader, start=2):
                    cls._import_row(row, row_num, default_group_id, result)

        db.session.commit()
        logger.info(
            "CSV 导入完成: 成功 %d, 跳过 %d, 失败 %d",
            result.success_count,
            result.skip_count,
            result.fail_count,
        )
        return result

    @classmethod
    def import_excel(cls, file_path, default_group_id=None):
        if not os.path.isfile(file_path):
            raise ImportError_(f"文件不存在: {file_path}")

        try:
            import openpyxl
        except ImportError:
            raise ImportError_("请安装 openpyxl: pip install openpyxl")

        result = ImportResult()
        wb = openpyxl.load_workbook(file_path, read_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            raise ImportError_("Excel 文件为空或只有表头")

        headers = [str(h).strip().lower() if h else "" for h in rows[0]]
        missing = cls.REQUIRED_FIELDS - set(headers)
        if missing:
            raise ImportError_(f"Excel 缺少必要列: {', '.join(missing)}")

        for row_num, row_data in enumerate(rows[1:], start=2):
            row = {headers[i]: row_data[i] for i in range(len(headers)) if i < len(row_data)}
            cls._import_row(row, row_num, default_group_id, result)

        wb.close()
        db.session.commit()

        logger.info(
            "Excel 导入完成: 成功 %d, 跳过 %d, 失败 %d",
            result.success_count,
            result.skip_count,
            result.fail_count,
        )
        return result

    @classmethod
    def _import_row(cls, row, row_num, default_group_id, result):
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip()
        group_name = str(row.get("group", "")).strip()
        remark = str(row.get("remark", "")).strip()

        if not name or not email:
            result.add_fail(email or f"第{row_num}行", "姓名或邮箱为空")
            return

        try:
            email = EmailValidator.validate(email)
        except EmailValidationError as e:
            result.add_fail(email, e.reason)
            return

        group_id = default_group_id
        if group_name:
            group = Group.query.filter_by(name=group_name).first()
            if not group:
                group = Group(name=group_name)
                db.session.add(group)
                db.session.flush()
            group_id = group.id

        existing = Subscriber.query.filter_by(email=email, group_id=group_id).first()
        if existing:
            result.add_skip(email, "该邮箱已存在于此分组中")
            return

        subscriber = Subscriber(
            name=name,
            email=email,
            group_id=group_id,
            remark=remark,
        )
        db.session.add(subscriber)
        result.add_success()

    @classmethod
    def import_file(cls, file_path, default_group_id=None):
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            return cls.import_csv(file_path, default_group_id)
        elif ext in (".xlsx", ".xls"):
            return cls.import_excel(file_path, default_group_id)
        else:
            raise ImportError_(f"不支持的文件格式: {ext}, 仅支持 .csv, .xlsx")

    @staticmethod
    def generate_template_csv(output_path):
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "email", "group", "remark"])
            writer.writerow(["张老师", "zhang@example.com", "教师组", "数学系"])
            writer.writerow(["李老师", "li@example.com", "教师组", "生物系"])
            writer.writerow(["王同学", "wang@example.com", "学生组", "2024级"])

        logger.info("导入模板已生成: %s", output_path)
        return output_path
