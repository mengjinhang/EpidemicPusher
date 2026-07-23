import logging

from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Group
from epidemic_pusher.mail.validator import EmailValidator, EmailValidationError

logger = logging.getLogger(__name__)


class SubscriberError(Exception):
    pass


class SubscriberManager:

    @staticmethod
    def add(name, email, group_id=None, remark=""):
        try:
            email = EmailValidator.validate(email)
        except EmailValidationError as e:
            raise SubscriberError(str(e))

        if group_id:
            group = Group.query.get(group_id)
            if not group:
                raise SubscriberError(f"分组不存在: ID={group_id}")

        existing = Subscriber.query.filter_by(email=email, group_id=group_id).first()
        if existing:
            raise SubscriberError(f"该邮箱已存在于此分组中: {email}")

        subscriber = Subscriber(
            name=name,
            email=email,
            group_id=group_id,
            remark=remark,
        )
        db.session.add(subscriber)
        db.session.commit()

        logger.info("添加订阅者: %s <%s>", name, EmailValidator.mask_email(email))
        return subscriber

    @staticmethod
    def update(subscriber_id, **kwargs):
        subscriber = Subscriber.query.get(subscriber_id)
        if not subscriber:
            raise SubscriberError(f"订阅者不存在: ID={subscriber_id}")

        if "email" in kwargs:
            try:
                kwargs["email"] = EmailValidator.validate(kwargs["email"])
            except EmailValidationError as e:
                raise SubscriberError(str(e))

        if "group_id" in kwargs and kwargs["group_id"]:
            group = Group.query.get(kwargs["group_id"])
            if not group:
                raise SubscriberError(f"分组不存在: ID={kwargs['group_id']}")

        for key, value in kwargs.items():
            if hasattr(subscriber, key):
                setattr(subscriber, key, value)

        db.session.commit()
        logger.info("更新订阅者: ID=%d", subscriber_id)
        return subscriber

    @staticmethod
    def delete(subscriber_id):
        subscriber = Subscriber.query.get(subscriber_id)
        if not subscriber:
            raise SubscriberError(f"订阅者不存在: ID={subscriber_id}")

        db.session.delete(subscriber)
        db.session.commit()
        logger.info("删除订阅者: ID=%d", subscriber_id)
        return True

    @staticmethod
    def delete_batch(subscriber_ids):
        count = Subscriber.query.filter(Subscriber.id.in_(subscriber_ids)).delete(
            synchronize_session="fetch"
        )
        db.session.commit()
        logger.info("批量删除订阅者: %d 人", count)
        return count

    @staticmethod
    def get(subscriber_id):
        subscriber = Subscriber.query.get(subscriber_id)
        if not subscriber:
            raise SubscriberError(f"订阅者不存在: ID={subscriber_id}")
        return subscriber

    @staticmethod
    def list_all(group_id=None, status=None, keyword=None, page=1, per_page=20):
        query = Subscriber.query

        if group_id:
            query = query.filter_by(group_id=group_id)
        if status:
            query = query.filter_by(status=status)
        if keyword:
            query = query.filter(
                db.or_(
                    Subscriber.name.contains(keyword),
                    Subscriber.email.contains(keyword),
                    Subscriber.remark.contains(keyword),
                )
            )

        query = query.order_by(Subscriber.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            "items": [s.to_dict() for s in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }

    @staticmethod
    def get_active_by_groups(group_ids):
        return Subscriber.query.filter(
            Subscriber.group_id.in_(group_ids),
            Subscriber.status == "active",
        ).all()

    @staticmethod
    def get_all_active():
        return Subscriber.query.filter_by(status="active").all()

    @staticmethod
    def set_status(subscriber_id, status):
        valid_statuses = ("active", "inactive", "bounced")
        if status not in valid_statuses:
            raise SubscriberError(f"无效状态: {status}, 可选: {valid_statuses}")

        subscriber = Subscriber.query.get(subscriber_id)
        if not subscriber:
            raise SubscriberError(f"订阅者不存在: ID={subscriber_id}")

        subscriber.status = status
        db.session.commit()
        return subscriber

    @staticmethod
    def count(group_id=None):
        query = Subscriber.query.filter_by(status="active")
        if group_id:
            query = query.filter_by(group_id=group_id)
        return query.count()
