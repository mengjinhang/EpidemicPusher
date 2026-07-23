import logging

from epidemic_pusher.database import db
from epidemic_pusher.models import Group, Subscriber

logger = logging.getLogger(__name__)


class GroupError(Exception):
    pass


class GroupManager:

    @staticmethod
    def create(name, description=""):
        if not name or not name.strip():
            raise GroupError("分组名称不能为空")

        name = name.strip()
        existing = Group.query.filter_by(name=name).first()
        if existing:
            raise GroupError(f"分组名称已存在: {name}")

        group = Group(name=name, description=description)
        db.session.add(group)
        db.session.commit()

        logger.info("创建分组: %s", name)
        return group

    @staticmethod
    def update(group_id, **kwargs):
        group = Group.query.get(group_id)
        if not group:
            raise GroupError(f"分组不存在: ID={group_id}")

        if "name" in kwargs:
            name = kwargs["name"].strip()
            existing = Group.query.filter(
                Group.name == name, Group.id != group_id
            ).first()
            if existing:
                raise GroupError(f"分组名称已存在: {name}")
            kwargs["name"] = name

        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)

        db.session.commit()
        logger.info("更新分组: ID=%d", group_id)
        return group

    @staticmethod
    def delete(group_id):
        group = Group.query.get(group_id)
        if not group:
            raise GroupError(f"分组不存在: ID={group_id}")

        subscriber_count = group.subscribers.count()
        if subscriber_count > 0:
            Subscriber.query.filter_by(group_id=group_id).update(
                {"group_id": None}, synchronize_session="fetch"
            )

        db.session.delete(group)
        db.session.commit()

        logger.info(
            "删除分组: %s (已将 %d 个订阅者移至未分组)",
            group.name,
            subscriber_count,
        )
        return True

    @staticmethod
    def get(group_id):
        group = Group.query.get(group_id)
        if not group:
            raise GroupError(f"分组不存在: ID={group_id}")
        return group

    @staticmethod
    def list_all():
        groups = Group.query.order_by(Group.created_at.desc()).all()
        return [g.to_dict() for g in groups]

    @staticmethod
    def get_with_subscriber_count():
        groups = Group.query.order_by(Group.name).all()
        result = []
        for g in groups:
            data = g.to_dict()
            data["active_count"] = g.subscribers.filter_by(status="active").count()
            result.append(data)
        return result
