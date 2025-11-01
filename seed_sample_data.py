"""Populate the database with a realistic demo dataset.

Run `python seed_sample_data.py` once after configuring the project. The script is
idempotent: running it again will update existing records and add missing ones
without duplicating data.
"""
from __future__ import annotations

import datetime as dt
from sqlalchemy import Select, select

from auth import get_password_hash
from db import SessionLocal, init_db
from models import (
    Attendance,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Priority,
    Project,
    ProjectMember,
    Role,
    Task,
    TaskStatus,
    TimeEntry,
    User,
)


def _first(session, stmt: Select):
    return session.scalars(stmt).first()


def ensure_user(session, *, username: str, password: str, **fields) -> User:
    user = _first(session, select(User).where(User.username == username))
    if user:
        for key, value in fields.items():
            setattr(user, key, value)
        if password:
            user.hashed_password = get_password_hash(password)
    else:
        user = User(username=username, hashed_password=get_password_hash(password), **fields)
        session.add(user)
    session.flush()
    return user


def ensure_project(session, *, code: str, **fields) -> Project:
    project = _first(session, select(Project).where(Project.code == code))
    if project:
        for key, value in fields.items():
            setattr(project, key, value)
    else:
        project = Project(code=code, **fields)
        session.add(project)
    session.flush()
    return project


def ensure_project_member(session, project: Project, user: User):
    exists = _first(
        session,
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        ),
    )
    if not exists:
        session.add(ProjectMember(project_id=project.id, user_id=user.id))


def ensure_task(session, *, title: str, assignee: User, **fields) -> Task:
    fields = dict(fields)
    created_by_id = fields.pop("created_by_id", assignee.id)
    task = _first(
        session,
        select(Task).where(Task.title == title, Task.assignee_id == assignee.id),
    )
    if task:
        for key, value in fields.items():
            setattr(task, key, value)
        task.created_by_id = created_by_id
    else:
        task = Task(title=title, assignee_id=assignee.id, created_by_id=created_by_id, **fields)
        session.add(task)
    session.flush()
    return task


def ensure_time_entry(session, *, user: User, date: dt.date, hours: float, **fields) -> TimeEntry:
    fields = dict(fields)
    task_id = fields.get("task_id")
    project_id = fields.get("project_id")
    entry = _first(
        session,
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            TimeEntry.date == date,
            TimeEntry.task_id == task_id,
            TimeEntry.project_id == project_id,
        ),
    )
    if entry:
        entry.hours = hours
        for key, value in fields.items():
            setattr(entry, key, value)
    else:
        entry = TimeEntry(user_id=user.id, date=date, hours=hours, **fields)
        session.add(entry)
    session.flush()
    return entry


def ensure_attendance(session, *, user: User, date: dt.date, check_in: dt.datetime, check_out: dt.datetime | None = None):
    record = _first(
        session,
        select(Attendance).where(Attendance.user_id == user.id, Attendance.date == date),
    )
    if record:
        record.check_in = check_in
        record.check_out = check_out
    else:
        session.add(Attendance(user_id=user.id, date=date, check_in=check_in, check_out=check_out))


def ensure_leave(session, *, user: User, date_from: dt.date, date_to: dt.date, **fields) -> LeaveRequest:
    leave = _first(
        session,
        select(LeaveRequest).where(
            LeaveRequest.user_id == user.id,
            LeaveRequest.date_from == date_from,
            LeaveRequest.date_to == date_to,
        ),
    )
    if leave:
        for key, value in fields.items():
            setattr(leave, key, value)
    else:
        leave = LeaveRequest(user_id=user.id, date_from=date_from, date_to=date_to, **fields)
        session.add(leave)
    session.flush()
    return leave


def seed():
    init_db()
    session = SessionLocal()
    today = dt.date.today()
    start_of_week = today - dt.timedelta(days=today.weekday())

    try:
        # Users
        admin = ensure_user(
            session,
            username="a.ivanov",
            password="demo123",
            full_name="Алексей Иванов",
            email="alexey.ivanov@example.com",
            role=Role.admin,
            department="Operations",
        )
        manager = ensure_user(
            session,
            username="m.kuznetsova",
            password="demo123",
            full_name="Мария Кузнецова",
            email="maria.kuznetsova@example.com",
            role=Role.manager,
            department="Проектный офис",
        )
        designer = ensure_user(
            session,
            username="d.ermakova",
            password="demo123",
            full_name="Дарья Ермакова",
            email="daria.ermakova@example.com",
            role=Role.employee,
            department="Дизайн",
        )
        developer = ensure_user(
            session,
            username="i.petrov",
            password="demo123",
            full_name="Игорь Петров",
            email="igor.petrov@example.com",
            role=Role.employee,
            department="Разработка",
        )
        analyst = ensure_user(
            session,
            username="l.smirnova",
            password="demo123",
            full_name="Лидия Смирнова",
            email="lidia.smirnova@example.com",
            role=Role.employee,
            department="Аналитика",
        )

        # Projects
        tf_core = ensure_project(
            session,
            code="TF-CORE",
            name="TimeFlow Core Platform",
            description="Бэклог для базовых задач платформы и багфиксов.",
            owner_id=manager.id,
            planned_hours=1200,
        )
        tf_crm = ensure_project(
            session,
            code="TF-CRM",
            name="Интеграция с CRM",
            description="Запуск синхронизации лидов и сделок между CRM и TimeFlow.",
            owner_id=manager.id,
            planned_hours=680,
            planned_due_date=today + dt.timedelta(days=45),
        )
        ops_support = ensure_project(
            session,
            code="OPS-SUPPORT",
            name="Операционные задачи",
            description="Непроектные обращения и техдолг.",
            owner_id=admin.id,
            is_project=False,
        )

        for user in (manager, designer, developer, analyst):
            ensure_project_member(session, tf_core, user)
        for user in (manager, developer, analyst):
            ensure_project_member(session, tf_crm, user)
        ensure_project_member(session, ops_support, admin)
        ensure_project_member(session, ops_support, developer)

        # Tasks
        backlog_refinement = ensure_task(
            session,
            title="Проанализировать обратную связь пользователей",
            assignee=analyst,
            description="Собрать и структурировать обратную связь за последний релиз.",
            priority=Priority.medium,
            status=TaskStatus.in_progress,
            percent_complete=45,
            project_id=tf_core.id,
            created_by_id=manager.id,
            due_date=start_of_week + dt.timedelta(days=4),
        )
        redesign_dashboard = ensure_task(
            session,
            title="Подготовить обновлённые макеты дэшборда",
            assignee=designer,
            description="Сделать три варианта UI для согласования.",
            priority=Priority.high,
            status=TaskStatus.in_progress,
            percent_complete=60,
            project_id=tf_crm.id,
            created_by_id=manager.id,
            due_date=today + dt.timedelta(days=5),
        )
        api_sync = ensure_task(
            session,
            title="Реализовать webhooks CRM",
            assignee=developer,
            description="Обработка событий создания и изменения сделки.",
            priority=Priority.critical,
            status=TaskStatus.on_pause,
            percent_complete=35,
            project_id=tf_crm.id,
            created_by_id=manager.id,
            due_date=today + dt.timedelta(days=10),
        )
        ops_support_task = ensure_task(
            session,
            title="Разобрать обращения поддержки",
            assignee=developer,
            description="Закрыть приоритетные инциденты клиентов.",
            priority=Priority.medium,
            status=TaskStatus.waiting,
            percent_complete=10,
            project_id=ops_support.id,
            created_by_id=admin.id,
        )

        # Attendance for the current week
        for offset in range(0, 4):
            day = start_of_week + dt.timedelta(days=offset)
            check_in = dt.datetime.combine(day, dt.time(hour=9, minute=30))
            check_out = dt.datetime.combine(day, dt.time(hour=18, minute=5))
            for user in (manager, designer, developer, analyst):
                ensure_attendance(session, user=user, date=day, check_in=check_in, check_out=check_out)

        # Time entries (two days of entries per person)
        notes_cycle = {
            manager.id: "Планирование релиза",
            designer.id: "Макеты и визуальные концепции",
            developer.id: "Разработка API и фиксы",
            analyst.id: "Интервью пользователей",
        }
        for offset, hours in ((0, 6.5), (1, 7.0), (2, 6.0)):
            day = today - dt.timedelta(days=offset)
            ensure_time_entry(
                session,
                user=designer,
                date=day,
                hours=hours,
                task_id=redesign_dashboard.id,
                project_id=tf_crm.id,
                notes=notes_cycle[designer.id],
            )
            ensure_time_entry(
                session,
                user=developer,
                date=day,
                hours=7.5 if offset == 0 else 6.5,
                task_id=api_sync.id if offset < 2 else ops_support_task.id,
                project_id=tf_crm.id if offset < 2 else ops_support.id,
                notes=notes_cycle[developer.id],
            )
            ensure_time_entry(
                session,
                user=analyst,
                date=day,
                hours=6.0,
                task_id=backlog_refinement.id,
                project_id=tf_core.id,
                notes=notes_cycle[analyst.id],
            )
            ensure_time_entry(
                session,
                user=manager,
                date=day,
                hours=5.5,
                project_id=tf_core.id,
                notes=notes_cycle[manager.id],
            )

        # Planned leave
        ensure_leave(
            session,
            user=designer,
            date_from=today + dt.timedelta(days=14),
            date_to=today + dt.timedelta(days=18),
            type=LeaveType.vacation,
            status=LeaveStatus.approved,
            approver_id=manager.id,
            comment="Утвержденный отпуск, замена согласована.",
        )

        session.commit()
        print("Demo dataset loaded successfully.")
        print("Созданные логины: a.ivanov, m.kuznetsova, d.ermakova, i.petrov, l.smirnova (пароль demo123).")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
