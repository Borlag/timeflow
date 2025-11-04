from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Float,
    Text,
    UniqueConstraint,
    func,
)
from db import Base
import enum
import datetime as dt

class Role(str, enum.Enum):
    employee = "employee"
    manager = "manager"
    admin = "admin"

class TaskStatus(str, enum.Enum):
    in_progress = "in_progress"
    on_pause = "on_pause"
    waiting = "waiting"
    done = "done"
    canceled = "canceled"

class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class LeaveType(str, enum.Enum):
    remote = "remote"
    sick = "sick"
    personal = "personal"
    business_trip = "business_trip"
    vacation = "vacation"
    admin_leave = "admin_leave"

class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class ProjectMember(Base):
    __tablename__ = "project_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    department: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.employee)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
    )
    time_entries: Mapped[list["TimeEntry"]] = relationship(
        "TimeEntry",
        back_populates="user",
        foreign_keys="TimeEntry.user_id",
    )
    member_projects: Mapped[list["ProjectMember"]] = relationship(backref="user", cascade="all, delete-orphan")

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), index=True)  # e.g., C7И**** or other code
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    is_project: Mapped[bool] = mapped_column(Boolean, default=True)  # False = non-project bucket
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/closed
    planned_hours: Mapped[float] = mapped_column(Float, default=0.0)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    date_created: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    planned_due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    owner: Mapped["User"] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")

    __table_args__ = (UniqueConstraint("code", name="uq_project_code"),)
    members: Mapped[list["ProjectMember"]] = relationship(
        backref="project", cascade="all, delete-orphan"
    )
    task_links: Mapped[list["ProjectTaskLink"]] = relationship(
        "ProjectTaskLink",
        back_populates="project",
        cascade="all, delete-orphan",
    )

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.in_progress)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.medium)
    percent_complete: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    assignee: Mapped["User"] = relationship(
        "User",
        back_populates="tasks",
        foreign_keys=[assignee_id],
    )
    created_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by_id],
    )
    comments: Mapped[list["TaskComment"]] = relationship(back_populates="task")
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="task")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    collaborators: Mapped[list["TaskCollaborator"]] = relationship(
        "TaskCollaborator",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    status_logs: Mapped[list["TaskStatusLog"]] = relationship(
        "TaskStatusLog",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStatusLog.created_at",
    )

class TaskComment(Base):
    __tablename__ = "task_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()

class TaskStatusLog(Base):
    __tablename__ = "task_status_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50))
    percent_complete: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="status_logs")
    author: Mapped["User"] = relationship()

class TaskCollaborator(Base):
    __tablename__ = "task_collaborators"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="collaborators", foreign_keys=[task_id])
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    added_by: Mapped["User"] = relationship(foreign_keys=[added_by_id])

    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_collaborator"),
    )

class ProjectTaskLink(Base):
    __tablename__ = "project_task_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="task_links")
    task: Mapped["Task"] = relationship("Task")

    __table_args__ = (
        UniqueConstraint("project_id", "task_id", name="uq_project_task_link"),
    )

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    hours: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)  # if backfilled beyond policy, set False until approved
    locked: Mapped[bool] = mapped_column(Boolean, default=False)   # Admin can lock entries after payroll/period close
    entry_type: Mapped[str] = mapped_column(String(30), default="work")  # work/leave/admin_adjustment
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow
    )
    leave_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_requests.id"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="time_entries")
    task: Mapped["Task"] = relationship(back_populates="time_entries")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    project: Mapped["Project"] = relationship("Project")
    leave_request: Mapped["LeaveRequest"] = relationship(
        "LeaveRequest", back_populates="time_entries"
    )

class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    date: Mapped[dt.date] = mapped_column(Date, index=True, default=dt.date.today)
    check_in: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[LeaveType] = mapped_column(Enum(LeaveType))
    date_from: Mapped[dt.date] = mapped_column(Date)
    date_to: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[LeaveStatus] = mapped_column(Enum(LeaveStatus), default=LeaveStatus.pending)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    approver: Mapped["User"] = relationship(foreign_keys=[approver_id])
    time_entries: Mapped[list["TimeEntry"]] = relationship(
        back_populates="leave_request", cascade="all, delete-orphan"
    )
