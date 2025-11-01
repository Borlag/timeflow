import datetime as dt
from collections import defaultdict

from fastapi import FastAPI, Depends, Request, Form, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, func, or_, text

from db import init_db, SessionLocal, engine
from models import *
from auth import get_db, get_current_user, require_roles, install_session_middleware, get_password_hash, verify_password
from config import APP_NAME, ORG_NAME, SHIFT_HOURS, ALLOW_BACKFILL_DAYS, ENABLE_SIGNUP

app = FastAPI(title=APP_NAME)
install_session_middleware(app)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals.update(datetime=dt)

@app.on_event("startup")
def startup():
    init_db()
    # --- миграция: добавить project_id, если его ещё нет ---
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info('time_entries')")).fetchall()]
        if "project_id" not in cols:
            conn.execute(text("ALTER TABLE time_entries ADD COLUMN project_id INTEGER"))
            conn.commit()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/auth/login", status_code=302)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/auth/login")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# ---------- AUTH ----------

@app.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "app_name": APP_NAME, "org_name": ORG_NAME, "enable_signup": ENABLE_SIGNUP})

@app.post("/auth/login")
def login(request: Request, db: Session = Depends(get_db),
          username: str = Form(...), password: str = Form(...)):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль", "app_name": APP_NAME, "org_name": ORG_NAME, "enable_signup": ENABLE_SIGNUP}, status_code=400)
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login")

@app.get("/auth/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if not ENABLE_SIGNUP:
        raise HTTPException(404)
    return templates.TemplateResponse("signup.html", {"request": request, "app_name": APP_NAME})

@app.post("/auth/signup")
def signup(request: Request, db: Session = Depends(get_db),
           username: str = Form(...), full_name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    if not ENABLE_SIGNUP:
        raise HTTPException(404)
    existing = db.scalar(select(User).where(or_(User.username == username, User.email == email)))
    if existing:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Пользователь с таким логином или email уже существует.", "app_name": APP_NAME}, status_code=400)
    user = User(username=username, full_name=full_name, email=email, role=Role.employee, hashed_password=get_password_hash(password))
    db.add(user); db.commit()
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)

# ---------- DASHBOARD ----------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), horizon: str = "today"):
    today = dt.date.today()
    start, end = today, today
    if horizon == "week":
        start = today - dt.timedelta(days=today.weekday())  # Monday
        end = start + dt.timedelta(days=6)
    elif horizon == "month":
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        end = next_month - dt.timedelta(days=1)

    tasks = db.scalars(
        select(Task).where(Task.assignee_id == user.id).order_by(Task.priority.desc(), Task.due_date.nulls_last())
    ).all()

    # Attendance for today
    att = db.scalar(select(Attendance).where(Attendance.user_id == user.id, Attendance.date == today))
    hours_logged_today = db.scalar(select(func.coalesce(func.sum(TimeEntry.hours), 0.0)).where(TimeEntry.user_id == user.id, TimeEntry.date == today)) or 0.0
    recommended_leave = None
    if att and att.check_in:
        recommended_leave = att.check_in + dt.timedelta(hours=SHIFT_HOURS)

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "tasks": tasks,
        "today": today, "start": start, "end": end,
        "attendance": att, "hours_logged_today": hours_logged_today,
        "recommended_leave": recommended_leave, "app_name": APP_NAME
    })

# --- Helpers ---
def allowed_projects_for(user: User, db: Session):
    if user.role in (Role.manager, Role.admin):
        return db.scalars(select(Project).where(Project.status == "active").order_by(Project.code)).all()
    return db.scalars(
        select(Project)
        .where(
            (Project.status == "active") &
            (
                (Project.owner_id == user.id) |
                (Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)))
            )
        ).order_by(Project.code)
    ).all()

# ---------- ATTENDANCE ----------

@app.post("/attendance/checkin")
def attendance_checkin(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = dt.date.today()
    att = db.scalar(select(Attendance).where(Attendance.user_id == user.id, Attendance.date == today))
    now = dt.datetime.now()
    if not att:
        att = Attendance(user_id=user.id, date=today, check_in=now)
        db.add(att)
    else:
        att.check_in = att.check_in or now
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)

@app.post("/attendance/checkout")
def attendance_checkout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = dt.date.today()
    att = db.scalar(select(Attendance).where(Attendance.user_id == user.id, Attendance.date == today))
    now = dt.datetime.now()
    if not att:
        att = Attendance(user_id=user.id, date=today, check_in=now, check_out=now)
        db.add(att)
    else:
        att.check_out = now
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)

# ---------- TASKS ----------

@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), mine: int = 1):
    q = select(Task).order_by(Task.priority.desc(), Task.due_date.nulls_last())
    if mine:
        q = q.where(Task.assignee_id == user.id)
    tasks = db.scalars(q).all()
    projects = db.scalars(select(Project).where(Project.status == "active").order_by(Project.code)).all()
    users = db.scalars(select(User).order_by(User.full_name)).all(); return templates.TemplateResponse("tasks.html", {"request": request, "user": user, "tasks": tasks, "projects": projects, "users": users, "app_name": APP_NAME})

@app.post("/tasks/update_status")
def update_task_status(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                       task_id: int = Form(...), status_v: TaskStatus = Form(...), percent: int = Form(...), comment: str = Form("")):
    task = db.get(Task, task_id)
    if not task or (user.role == Role.employee and task.assignee_id != user.id):
        raise HTTPException(403, "Нет доступа к задаче")
    task.status = status_v
    task.percent_complete = max(0, min(100, percent))
    if comment.strip():
        db.add(TaskComment(task_id=task.id, author_id=user.id, content=comment.strip()))
    db.commit()
    return RedirectResponse("/tasks?mine=1", status_code=302)

@app.post("/tasks/new")
def create_task(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                title: str = Form(...), description: str = Form(""), assignee_id: int = Form(...), project_id: int = Form(None),
                priority: Priority = Form(Priority.medium), start_date: str = Form(None), due_date: str = Form(None)):
    sd = dt.date.fromisoformat(start_date) if start_date else None
    dd = dt.date.fromisoformat(due_date) if due_date else None
    # if employee creates -> requires approval
    needs_approval = (user.role == Role.employee)
    task = Task(title=title, description=description, assignee_id=assignee_id, project_id=project_id, priority=priority,
                start_date=sd, due_date=dd, created_by_id=user.id, approved=(not needs_approval),
                status=(TaskStatus.waiting if needs_approval else TaskStatus.in_progress))
    db.add(task); db.commit()
    return RedirectResponse("/tasks?mine=0", status_code=302)


# ---------- TIME ENTRIES ----------

@app.get("/timesheet", response_class=HTMLResponse)
def timesheet(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), date: str | None = None):
    d = dt.date.fromisoformat(date) if date else (dt.date.today() - dt.timedelta(days=1))
    entries = db.scalars(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.date == d).order_by(TimeEntry.created_at)).all()
    tasks = db.scalars(select(Task).where(Task.assignee_id == user.id).order_by(Task.title)).all()
    projects = allowed_projects_for(user, db)
    return templates.TemplateResponse("timesheet.html", {
        "request": request, "user": user, "date": d, "entries": entries,
        "tasks": tasks, "projects": projects,
        "allow_backfill_days": ALLOW_BACKFILL_DAYS, "app_name": APP_NAME
    })

@app.post("/timesheet/add")
def add_time_entry(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                   date: str = Form(...), hours: float = Form(...),
                   task_id: str = Form(""), project_id: str = Form(""), notes: str = Form("")):
    d = dt.date.fromisoformat(date)
    today = dt.date.today()
    delta_days = (today - d).days
    approved = not (delta_days > ALLOW_BACKFILL_DAYS or d > today)

    # аккуратно разбираем task_id / project_id
    def _to_int(s):
        s = (s or "").strip()
        if not s or s in {"0","None","none","null"}: return None
        try: return int(s)
        except: return None

    task_id_i = _to_int(task_id)
    project_id_i = None if task_id_i else _to_int(project_id)  # если выбрана задача — проект игнорируем

    te = TimeEntry(
        user_id=user.id, task_id=task_id_i, project_id=project_id_i,
        date=d, hours=float(hours), notes=notes.strip(),
        approved=approved, entry_type="work"
    )
    db.add(te); db.commit()
    return RedirectResponse(f"/timesheet?date={d.isoformat()}", status_code=302)


@app.post("/timesheet/delete")
def delete_time_entry(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                      entry_id: int = Form(...)):
    te = db.get(TimeEntry, entry_id)
    if not te or te.user_id != user.id:
        raise HTTPException(403, "Нет доступа")
    if te.locked:
        raise HTTPException(400, "Запись заблокирована")
    db.delete(te); db.commit()
    return RedirectResponse(f"/timesheet?date={te.date.isoformat()}", status_code=302)

# --- NEW: Team calendar view (users x days) ---
@app.get("/calendar/team", response_class=HTMLResponse)
def calendar_team(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  start: str | None = None, days: int = 14):
    start_date = dt.date.fromisoformat(start) if start else dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    days_list = [start_date + dt.timedelta(days=i) for i in range(days)]
    users = db.scalars(select(User).where(User.is_active == True).order_by(User.department, User.full_name)).all()  # noqa: E712
    rows = []
    for u in users:
      # hours per day (approved work)
      qh = select(TimeEntry.date, func.coalesce(func.sum(TimeEntry.hours), 0.0))\
            .where(TimeEntry.user_id == u.id, TimeEntry.approved == True, TimeEntry.entry_type == "work",
                   TimeEntry.date >= days_list[0], TimeEntry.date <= days_list[-1])\
            .group_by(TimeEntry.date)
      hours = {d: 0.0 for d in days_list}
      for d, h in db.execute(qh):
          hours[d] = float(h or 0.0)
      # leave requests overlay
      ql = select(LeaveRequest).where(LeaveRequest.user_id == u.id,
                                      LeaveRequest.date_from <= days_list[-1],
                                      LeaveRequest.date_to >= days_list[0])
      marks = {d: "" for d in days_list}
      colors = {d: "" for d in days_list}
      for lr in db.scalars(ql).all():
          code = {"remote":"У","sick":"Б","personal":"О","business_trip":"К","vacation":"ОП","admin_leave":"АО"}[lr.type.value]
          rng = [lr.date_from + dt.timedelta(days=i) for i in range((lr.date_to - lr.date_from).days+1)]
          for d in rng:
              if d in marks:
                  marks[d] = code
                  colors[d] = "approved" if lr.status == LeaveStatus.approved else ("pending" if lr.status == LeaveStatus.pending else "rejected")
      rows.append(type("Row", (), {"user": u, "hours": hours, "marks": marks, "colors": colors}))
    return templates.TemplateResponse("calendar_team.html", {"request": request, "user": user, "rows": rows, "days_list": days_list, "app_name": APP_NAME})

# --- NEW: click cell to create leave for a single date (pending) ---
@app.post("/calendar/leave_cell")
def calendar_leave_cell(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                        date: str = Form(...), type: LeaveType = Form(...)):
    d = dt.date.fromisoformat(date)
    lr = LeaveRequest(user_id=user.id, type=type, date_from=d, date_to=d, status=LeaveStatus.pending, comment="Через календарь")
    db.add(lr); db.commit()
    return RedirectResponse(f"/calendar/team?start={(d - dt.timedelta(days=d.weekday())).isoformat()}", status_code=302)

# --- NEW: Personal timesheet grid (tasks x days) ---
@app.get("/timesheet/grid", response_class=HTMLResponse)
def timesheet_grid(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                   start: str | None = None, days: int = 14):
    start_date = dt.date.fromisoformat(start) if start else dt.date.today() - dt.timedelta(days=13)
    days_list = [start_date + dt.timedelta(days=i) for i in range(days)]
    # Recent tasks assigned to user (last 60 days touches or assigned)
    tasks = db.scalars(select(Task).where(Task.assignee_id == user.id).order_by(Task.priority.desc(), Task.due_date.nulls_last())).all()
    rows = []
    for t in tasks:
        q = select(TimeEntry.date, func.sum(TimeEntry.hours)).where(TimeEntry.user_id == user.id, TimeEntry.task_id == t.id,
                                                                    TimeEntry.date >= days_list[0], TimeEntry.date <= days_list[-1],
                                                                    TimeEntry.approved == True).group_by(TimeEntry.date)
        hours_map = {d: 0.0 for d in days_list}
        for d, h in db.execute(q):
            hours_map[d] = float(h or 0.0)
        rows.append(type("Row", (), {"task": t, "hours": hours_map}))
    return templates.TemplateResponse("timesheet_grid.html", {"request": request, "user": user, "rows": rows, "days_list": days_list, "app_name": APP_NAME})

# ---------- LEAVES / CALENDAR ----------

@app.get("/leaves", response_class=HTMLResponse)
def leaves_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    my_requests = db.scalars(select(LeaveRequest).where(LeaveRequest.user_id == user.id).order_by(LeaveRequest.created_at.desc())).all()
    return templates.TemplateResponse("leaves.html", {"request": request, "user": user, "my_requests": my_requests, "app_name": APP_NAME})

@app.post("/leaves/request")
def request_leave(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  type: LeaveType = Form(...), date_from: str = Form(...), date_to: str = Form(...), comment: str = Form("")):
    df = dt.date.fromisoformat(date_from); dt_to = dt.date.fromisoformat(date_to)
    lr = LeaveRequest(user_id=user.id, type=type, date_from=df, date_to=dt_to, comment=comment.strip())
    db.add(lr); db.commit()
    return RedirectResponse("/leaves", status_code=302)

# ---------- PROJECTS (Admin/Manager) ----------

@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.scalars(select(Project).order_by(Project.status.desc(), Project.code)).all()
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return templates.TemplateResponse("projects.html", {"request": request, "user": user, "projects": projects, "users": users, "app_name": APP_NAME})

@app.post("/projects/new")
def new_project(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                code: str = Form(...), name: str = Form(...), description: str = Form(""), is_project: int = Form(1),
                planned_hours: float = Form(0.0), owner_id: int | None = Form(None), planned_due_date: str | None = Form(None)):
    p = Project(code=code.strip(), name=name.strip(), description=description.strip(), is_project=bool(is_project),
                planned_hours=float(planned_hours), owner_id=owner_id if owner_id else None,
                planned_due_date=(dt.date.fromisoformat(planned_due_date) if planned_due_date else None))
    db.add(p); db.commit()
    return RedirectResponse("/projects", status_code=302)

@app.post("/projects/close")
def close_project(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                  project_id: int = Form(...)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Проект не найден")
    p.status = "closed"
    db.commit()
    return RedirectResponse("/projects", status_code=302)

@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "Проект не найден")
    tasks = db.scalars(select(Task).where(Task.project_id == p.id).order_by(Task.priority.desc(), Task.due_date.nulls_last())).all()
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == p.id)).all()
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return templates.TemplateResponse("project_detail.html", {"request": request, "user": user, "project": p, "tasks": tasks, "members": members, "users": users, "app_name": APP_NAME})

@app.post("/projects/{project_id}/members/add")
def project_add_member(request: Request, project_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                       user_id: int = Form(...)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "Проект не найден")
    exists = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    if not exists:
        db.add(ProjectMember(project_id=project_id, user_id=user_id)); db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=302)

@app.post("/projects/{project_id}/members/remove")
def project_remove_member(request: Request, project_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                          member_id: int = Form(...)):
    m = db.get(ProjectMember, member_id)
    if m: db.delete(m); db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=302)

# ---------- APPROVALS (Manager/Admin) ----------

@app.get("/admin/approvals", response_class=HTMLResponse)
def approvals(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin))):
    pending_time = db.scalars(select(TimeEntry).where(TimeEntry.approved == False).order_by(TimeEntry.date.desc())).all()  # noqa: E712
    pending_leaves = db.scalars(select(LeaveRequest).where(LeaveRequest.status == LeaveStatus.pending).order_by(LeaveRequest.created_at.desc())).all()
    pending_tasks = db.scalars(select(Task).where(Task.approved == False).order_by(Task.created_at.desc())).all()
    return templates.TemplateResponse("admin.html", {"request": request, "user": user, "pending_time": pending_time, "pending_leaves": pending_leaves, "pending_tasks": pending_tasks, "app_name": APP_NAME})

@app.post("/admin/approve_task")
def approve_task(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                 task_id: int = Form(...), approve: int = Form(1)):
    t = db.get(Task, task_id)
    if not t: raise HTTPException(404, "Задача не найдена")
    t.approved = bool(approve)
    if approve and t.status == TaskStatus.waiting:
        t.status = TaskStatus.in_progress
    db.commit()
    return RedirectResponse("/admin/approvals", status_code=302)

@app.post("/admin/approve_time")
def approve_time(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                 entry_id: int = Form(...), approve: int = Form(1)):
    te = db.get(TimeEntry, entry_id)
    if not te:
        raise HTTPException(404, "Запись времени не найдена")
    if approve:
        te.approved = True
    else:
        # reject -> delete or set 0 hours
        te.approved = False
    db.commit()
    return RedirectResponse("/admin/approvals", status_code=302)

@app.post("/admin/approve_leave")
def approve_leave(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                  leave_id: int = Form(...), approve: int = Form(1)):
    lr = db.get(LeaveRequest, leave_id)
    if not lr:
        raise HTTPException(404, "Заявка не найдена")
    if approve:
        lr.status = LeaveStatus.approved
        lr.approver_id = user.id
        # Auto create time entries for leave days
        d = lr.date_from
        while d <= lr.date_to:
            db.add(TimeEntry(user_id=lr.user_id, task_id=None, date=d, hours=SHIFT_HOURS, notes=f"Leave: {lr.type}", approved=True, entry_type="leave"))
            d += dt.timedelta(days=1)
    else:
        lr.status = LeaveStatus.rejected
        lr.approver_id = user.id
    db.commit()
    return RedirectResponse("/admin/approvals", status_code=302)

# ---------- USERS (Admin) ----------

@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin))):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return templates.TemplateResponse("users.html", {"request": request, "user": user, "users": users, "app_name": APP_NAME})

@app.post("/admin/users/new")
def user_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin)),
             username: str = Form(...), full_name: str = Form(...), email: str = Form(...),
             department: str = Form(""), role: Role = Form(Role.employee), password: str = Form(...)):
    u = User(username=username.strip(), full_name=full_name.strip(), email=email.strip(), department=department.strip(),
             role=role, hashed_password=get_password_hash(password))
    db.add(u); db.commit()
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/reset_password")
def reset_user_password(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.admin)),
                        user_id: int = Form(...), new_password: str = Form(...)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.hashed_password = get_password_hash(new_password)
    db.commit()
    return RedirectResponse("/admin/users", status_code=302)

# ---------- TEAM VIEW ----------

@app.get("/team", response_class=HTMLResponse)
def team_view(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # For each user, show current top task and status
    users = db.scalars(select(User).where(User.is_active == True).order_by(User.department, User.full_name)).all()  # noqa: E712
    rows = []
    for u in users:
        task = db.scalar(select(Task).where(Task.assignee_id == u.id).order_by(Task.priority.desc(), Task.due_date.nulls_last()))
        att = db.scalar(select(Attendance).where(Attendance.user_id == u.id, Attendance.date == dt.date.today()))
        rows.append((u, task, att))
    return templates.TemplateResponse("team.html", {"request": request, "user": user, "rows": rows, "app_name": APP_NAME})

# ---------- METRICS (Manager/Admin) ----------

@app.get("/metrics", response_class=HTMLResponse)
def metrics_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin))):
    return templates.TemplateResponse("metrics.html", {"request": request, "user": user, "app_name": APP_NAME})

@app.get("/api/metrics/utilization")
def api_utilization(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                    days: int = 28):
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    projects = {p.id: p for p in db.scalars(select(Project)).all()}
    data = {}
    q = select(TimeEntry, User.full_name, Task.id, Task.project_id).join(User, User.id == TimeEntry.user_id)\
        .join(Task, TimeEntry.task_id == Task.id, isouter=True)\
        .where(TimeEntry.date >= start, TimeEntry.date <= end, TimeEntry.approved == True)
    for te, full_name, task_id, task_project_id in db.execute(q):
        if full_name not in data:
            data[full_name] = {"project":0.0, "nonproject":0.0, "leave":0.0, "total":0.0}
        if te.entry_type == "leave":
            data[full_name]["leave"] += te.hours
            data[full_name]["total"] += te.hours
            continue
        # work entry
        proj_id = task_project_id or te.project_id
        if proj_id and projects.get(proj_id) and projects[proj_id].is_project:
            data[full_name]["project"] += te.hours
        else:
            data[full_name]["nonproject"] += te.hours
        data[full_name]["total"] += te.hours
    labels = list(data.keys())
    project_hours = [round(data[n]["project"],2) for n in labels]
    nonproject_hours = [round(data[n]["nonproject"],2) for n in labels]
    leave_hours = [round(data[n]["leave"],2) for n in labels]
    return JSONResponse({"labels": labels, "project_hours": project_hours, "nonproject_hours": nonproject_hours, "leave_hours": leave_hours})


@app.get("/api/metrics/project_load")
def api_project_load(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin))):
    # Planned vs logged per project (including project-level entries)
    # 1) by tasks
    q1 = select(Project.id, Project.code, func.coalesce(func.sum(TimeEntry.hours), 0.0))\
        .join(Task, Task.project_id == Project.id, isouter=True)\
        .join(TimeEntry, TimeEntry.task_id == Task.id, isouter=True)\
        .where(Project.status == "active", TimeEntry.approved == True)\
        .group_by(Project.id, Project.code)
    logged = {pid: hours for pid, code, hours in db.execute(q1)}
    # 2) direct project entries
    q2 = select(Project.id, func.coalesce(func.sum(TimeEntry.hours), 0.0))\
        .join(TimeEntry, TimeEntry.project_id == Project.id)\
        .where(Project.status == "active", TimeEntry.approved == True)\
        .group_by(Project.id)
    for pid, h in db.execute(q2):
        logged[pid] = (logged.get(pid, 0.0) + (h or 0.0))
    projects = db.scalars(select(Project).where(Project.status == "active").order_by(Project.code)).all()
    labels = [p.code for p in projects]
    planned = [round(p.planned_hours or 0.0, 2) for p in projects]
    actual = [round(logged.get(p.id, 0.0), 2) for p in projects]
    return JSONResponse({"labels": labels, "planned_hours": planned, "actual_hours": actual})

@app.get("/api/metrics/department_workload")
def api_department_workload(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.manager, Role.admin)),
                            days: int = 14):
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    q = select(User.department, func.coalesce(func.sum(TimeEntry.hours), 0.0))\
        .join(TimeEntry, TimeEntry.user_id == User.id)\
        .where(TimeEntry.date >= start, TimeEntry.date <= end, TimeEntry.approved == True)\
        .group_by(User.department)
    labels, values = [], []
    for dept, hrs in db.execute(q):
        labels.append(dept or "—")
        values.append(round(hrs or 0.0, 2))
    return JSONResponse({"labels": labels, "hours": values})

# ---------- STATIC PAGES ----------

def _users_for_form(db: Session):
    return db.scalars(select(User).order_by(User.full_name)).all()

templates.env.globals.update(Role=Role, TaskStatus=TaskStatus, Priority=Priority, LeaveType=LeaveType)
templates.env.globals.update(org_name=ORG_NAME, app_name=APP_NAME, SHIFT_HOURS=SHIFT_HOURS)
templates.env.globals.update(datetime=dt, date=dt.date)

