from datetime import datetime

import requests
from flask import current_app
from flask_jwt_extended import current_user
from lin import db, manager
from lin.interface import InfoCrud as Base
from sqlalchemy import Column, Integer, String, text

from app.libs.error_code import RecordRemoveException
from app.libs.utils import paging
from app.models.case import Case


class Task(Base):
    id = Column(Integer, primary_key=True, autoincrement=True, comment='任务id')
    task_no = Column(String(20), comment='任务编号')
    project_id = Column(Integer, nullable=False, comment='工程id')
    create_user = Column(Integer, nullable=False, comment='执行人id')
    total = Column(Integer, default=0, comment='用例执行总数')
    success = Column(Integer, default=0, comment='成功数')
    fail = Column(Integer, default=0, comment='失败数')

    def __init__(self, project_id, user_id, total):
        super().__init__()
        self.project_id = project_id
        self.create_user = user_id
        self.total = total

    def new_task(self):
        db.session.add(self)
        db.session.flush()
        db.session.commit()

    def update_task_no(self):
        self.task_no = self._create_time.strftime("%Y%m%d%H%M%S") + '_' + str(self.project_id)
        db.session.commit()

    def update_result(self, success=None, fail=None):
        if success is not None:
            self.success = success
        if fail is not None:
            self.fail = fail
        db.session.commit()

        # 将执行结果广播给客户端
        api_server = current_app.config.get('API_SERVER')
        res = requests.get(url=api_server + '/v1/task/task/' + str(self.project_id))
        current_app.logger.debug(res.text)

    @classmethod
    def all_tasks(cls, project):
        tasks = cls.query.filter(
            cls.project_id == project if project else '',
            cls.delete_time == None,
        ).order_by(
            text('update_time desc')
        ).all()

        for task in tasks:
            create_user = manager.user_model.query.filter_by(id=task.create_user).first()
            setattr(task, 'create_user_name', create_user.username)
            task._fields.append('create_user_name')

        return tasks

    @classmethod
    def get_tasks(cls, user, project, no, start, end, page=None, count=None):
        count = int(count) if count else current_app.config.get('COUNT_DEFAULT')
        page = int(page) if page else current_app.config.get('PAGE_DEFAULT') + 1
        results = cls.query.filter(
            cls.create_user == user if user else '',
            cls.project_id == project if project else '',
            cls.task_no.like(f'%{no}%') if no is not None else '',
            cls._create_time.between(start, end) if start and end else '',
            cls.delete_time == None,
        ).with_entities(
            cls.id,
            cls.task_no,
            cls.project_id,
            cls.create_user,
            cls.total,
            cls.success,
            cls.fail,
            cls._create_time.label('create_time')
        ).order_by(
            text('update_time desc')
        ).paginate(page, count)

        items = [dict(zip(result.keys(), result)) for result in results.items]
        for item in items:
            # 获取工程名称
            from app.models.project import Project
            project_name = Project.query.filter_by(id=item['project_id']).first()
            item['project_name'] = project_name.name
            # 获取执行人名称
            user = manager.user_model.query.filter_by(id=item['create_user']).first()
            item['username'] = user.username
            item['create_time'] = int(round(item['create_time'].timestamp() * 1000))
        results.items = items
        data = paging(results)
        return data

    @classmethod
    def delete_tasks(cls, user, project, no, start, end):
        tasks = cls.query.filter(
            cls.create_user == user if user else '',
            cls.project_id == project if project else '',
            cls.task_no.like(f'%{no}%') if no is not None else '',
            cls._create_time.between(start, end) if start and end else '',
            cls.delete_time == None,
        ).all()
        task_no_list = [task.task_no for task in tasks]
        try:
            for task in tasks:
                task.delete_time = datetime.now()
            db.session.commit()
            # 删除日志
            for task_no in task_no_list:
                Case.case_log_remove(name=None, url=None, project=None, task=task_no, result=None, start=None, end=None)
        except Exception:
            db.session.rollback()
            raise RecordRemoveException()

        return len(tasks)

    @classmethod
    def user_task(cls, uid, name, start, end, page=None, count=None):
        count = int(count) if count else current_app.config.get('COUNT_DEFAULT')
        page = int(page) if page else current_app.config.get('PAGE_DEFAULT') + 1
        from app.models.project import Project
        if not uid:
            uid = current_user.id
        results = cls.query.join(Project, Project.id == cls.project_id).filter(
            cls.create_user == uid,
            Project.name.like(f'%{name}%') if name is not None else '',
            cls._create_time.between(start, end) if start and end else '',
            cls.delete_time == None,
        ).with_entities(
            cls.id,
            cls.task_no,
            cls.project_id,
            cls.create_user,
            cls.total,
            cls.success,
            cls.fail,
            cls._create_time.label('create_time')
        ).order_by(
            text('Task.update_time desc')
        ).paginate(page, count)

        items = [dict(zip(result.keys(), result)) for result in results.items]
        for item in items:
            # 获取工程名称
            from app.models.project import Project
            project_name = Project.query.filter_by(id=item['project_id']).first()
            item['project_name'] = project_name.name
            # 获取执行人名称
            user = manager.user_model.query.filter_by(id=item['create_user']).first()
            item['username'] = user.username
            item['create_time'] = int(round(item['create_time'].timestamp() * 1000))
        results.items = items
        data = paging(results)
        return data

    # 获取今日执行得测试次数、测试得工程数
    @classmethod
    def today(cls):

        execute_task = db.session.execute("SELECT * FROM `easy-test`.`task` where delete_time is null "
                                          "and DATE_FORMAT(create_time,'%Y-%m-%d') = DATE_FORMAT(NOW(),'%Y-%m-%d')")

        execute_project = db.session.execute("SELECT project_id, count(*) FROM `easy-test`.`task` WHERE delete_time IS "
                                             "NULL AND DATE_FORMAT( create_time, '%Y-%m-%d' ) = "
                                             "DATE_FORMAT( NOW( ), '%Y-%m-%d' ) GROUP BY project_id")

        return len(list(execute_task)), len(list(execute_project))
