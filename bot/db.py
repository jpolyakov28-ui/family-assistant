"""Тонкая обёртка вокруг supabase-py для нашего бота."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client, create_client

from bot.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# Фиксированный список членов семьи (для лекарств/БАДов и списков покупок).
FAMILY_MEMBERS = [
    "Юрий", "Светлана", "Леонид", "Полина",
    "Тамара", "Михаил", "Захар", "Антонина",
]

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


# ---------- users ----------

def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    res = (
        get_client()
        .table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def create_user(telegram_id: int, name: str, timezone: str = "Europe/Moscow") -> dict:
    res = (
        get_client()
        .table("users")
        .insert({"telegram_id": telegram_id, "name": name, "timezone": timezone})
        .execute()
    )
    return res.data[0]


_USER_DISPLAY_ORDER = ["Папа", "Мама", "Леня", "Полина", "Тамара", "Михаил", "Захар", "Антонина"]


def list_users() -> list[dict]:
    res = get_client().table("users").select("*").execute()
    users = res.data or []
    return sorted(
        users,
        key=lambda u: _USER_DISPLAY_ORDER.index(u["name"]) if u["name"] in _USER_DISPLAY_ORDER else len(_USER_DISPLAY_ORDER),
    )


# ---------- tasks ----------

def create_task(
    *,
    task_type: str,
    title: str,
    created_by: str,
    visibility: str = "assignees",
    due_at: datetime | None = None,
    due_has_time: bool = True,
    notes: str | None = None,
    recurrence: str | None = None,
    category: str | None = None,
    time_local: str | None = None,
    assignee_user_ids: list[str] | None = None,
    lead_minutes: list[int] | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "type": task_type,
        "title": title,
        "created_by": created_by,
        "visibility": visibility,
        "due_has_time": due_has_time,
    }
    if due_at is not None:
        payload["due_at"] = due_at.isoformat()
    if notes:
        payload["notes"] = notes
    if recurrence:
        payload["recurrence"] = recurrence
    if category:
        payload["category"] = category
    if time_local:
        payload["time_local"] = time_local
    if lead_minutes:
        payload["lead_minutes"] = sorted(set(lead_minutes), reverse=True)

    task = get_client().table("tasks").insert(payload).execute().data[0]

    if assignee_user_ids:
        get_client().table("task_assignees").insert(
            [{"task_id": task["id"], "user_id": uid} for uid in assignee_user_ids]
        ).execute()

    return task


def get_task(task_id: str) -> dict | None:
    res = get_client().table("tasks").select("*").eq("id", task_id).limit(1).execute()
    return res.data[0] if res.data else None


def snooze_task(task_id: str, new_due_at: datetime) -> None:
    """Перенести задачу: новый срок, статус снова open, sent_offsets обнуляем."""
    get_client().table("tasks").update(
        {
            "due_at": new_due_at.isoformat(),
            "status": "open",
            "sent_offsets": [],
        }
    ).eq("id", task_id).execute()


def mark_offset_sent(task_id: str, offset: int) -> None:
    """Добавить offset в sent_offsets, чтобы не дублировать напоминание."""
    client = get_client()
    res = client.table("tasks").select("sent_offsets").eq("id", task_id).limit(1).execute()
    if not res.data:
        return
    sent = list(res.data[0].get("sent_offsets") or [])
    if offset in sent:
        return
    sent.append(offset)
    client.table("tasks").update({"sent_offsets": sent}).eq("id", task_id).execute()


def list_tasks_for_user(
    user_id: str,
    *,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    include_family: bool = True,
    only_open: bool = True,
) -> list[dict]:
    """
    Возвращает задачи, видимые конкретному пользователю:
      - назначенные ему (через task_assignees)
      - + общесемейные (visibility='family') если include_family
    """
    client = get_client()

    # 1) задачи, где user в assignees
    assigned_ids_resp = (
        client.table("task_assignees")
        .select("task_id")
        .eq("user_id", user_id)
        .execute()
    )
    assigned_task_ids = [r["task_id"] for r in (assigned_ids_resp.data or [])]

    q = client.table("tasks").select("*")
    if due_from is not None:
        q = q.gte("due_at", due_from.isoformat())
    if due_to is not None:
        q = q.lt("due_at", due_to.isoformat())
    if only_open:
        q = q.eq("status", "open")

    # Видимость: назначено пользователю ИЛИ семейная ИЛИ приватная+created_by=user
    # (дублирует логику list_schedule_for_user для единообразия)
    private_filter = f"and(visibility.eq.private,created_by.eq.{user_id})"
    if include_family and assigned_task_ids:
        ids_csv = ",".join(assigned_task_ids)
        q = q.or_(f"id.in.({ids_csv}),visibility.eq.family,{private_filter}")
    elif include_family:
        q = q.or_(f"visibility.eq.family,{private_filter}")
    elif assigned_task_ids:
        ids_csv = ",".join(assigned_task_ids)
        q = q.or_(f"id.in.({ids_csv}),{private_filter}")
    else:
        q = q.or_(private_filter)

    return q.order("due_at").execute().data or []


def mark_task_done(task_id: str) -> None:
    get_client().table("tasks").update({"status": "done"}).eq("id", task_id).execute()


def set_task_alarm(task_id: str, on: bool) -> None:
    """Включить/выключить «будильник» задачи. При включении — сбросить метку звонка."""
    fields: dict[str, Any] = {"alarm": on}
    if on:
        fields["alarm_last_ring"] = None
    get_client().table("tasks").update(fields).eq("id", task_id).execute()


def set_task_assignees(task_id: str, user_ids: list[str]) -> None:
    client = get_client()
    client.table("task_assignees").delete().eq("task_id", task_id).execute()
    if user_ids:
        client.table("task_assignees").insert(
            [{"task_id": task_id, "user_id": uid} for uid in user_ids]
        ).execute()


# ---------- schedule ----------

def _parse_hhmm(value: str) -> time | None:
    try:
        hh_str, mm_str = value.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hh, mm)
    except (ValueError, AttributeError):
        pass
    return None


def list_schedule_for_user(user_id: str, target_date: date, tz: str) -> dict[str, list[dict]]:
    """
    Возвращает пункты расписания на дату target_date для пользователя.

    Структура:
      {
        "timed":   [{... task fields ..., "local_dt": datetime, "is_recurring": bool}, ...]
                   — отсортировано по времени.
        "untimed": [{... task fields ...}, ...]
                   — задачи на эту дату без точного времени.
      }

    Включает:
      • разовые tasks с due_at внутри суток (status='open');
      • повторяющиеся events, где recurrence содержит код дня недели target_date,
        с time_local в качестве времени старта.

    Видимость: family-задачи, назначенные пользователю, либо его собственные private.
    """
    client = get_client()
    tzinfo = ZoneInfo(tz)
    day_start_local = datetime.combine(target_date, time(0, 0), tzinfo=tzinfo)
    day_end_local = day_start_local + timedelta(days=1)
    weekday_code = WEEKDAY_CODES[target_date.weekday()]

    # task_ids, где пользователь — assignee
    assigned_resp = (
        client.table("task_assignees")
        .select("task_id")
        .eq("user_id", user_id)
        .execute()
    )
    assigned_task_ids = [r["task_id"] for r in (assigned_resp.data or [])]

    # 1) разовые в окне суток
    q_oneoff = (
        client.table("tasks")
        .select("*")
        .is_("recurrence", "null")
        .eq("status", "open")
        .gte("due_at", day_start_local.isoformat())
        .lt("due_at", day_end_local.isoformat())
    )
    visibility_or = "visibility.eq.family"
    if assigned_task_ids:
        ids_csv = ",".join(assigned_task_ids)
        visibility_or = f"visibility.eq.family,id.in.({ids_csv})"
    # видимость: family ИЛИ user assigned ИЛИ private+created_by=user
    q_oneoff = q_oneoff.or_(f"{visibility_or},and(visibility.eq.private,created_by.eq.{user_id})")
    oneoff_rows = q_oneoff.execute().data or []

    # 2) повторяющиеся
    q_rec = (
        client.table("tasks")
        .select("*")
        .not_.is_("recurrence", "null")
        .ilike("recurrence", f"%{weekday_code}%")
    )
    q_rec = q_rec.or_(f"{visibility_or},and(visibility.eq.private,created_by.eq.{user_id})")
    recurring_rows = q_rec.execute().data or []

    timed: list[dict] = []
    untimed: list[dict] = []

    for row in oneoff_rows:
        due_iso = row.get("due_at")
        if not due_iso:
            continue
        dt = datetime.fromisoformat(due_iso.replace("Z", "+00:00")).astimezone(tzinfo)
        item = dict(row)
        item["local_dt"] = dt
        item["is_recurring"] = False
        if row.get("due_has_time", True):
            timed.append(item)
        else:
            untimed.append(item)

    for row in recurring_rows:
        t = _parse_hhmm(row.get("time_local") or "")
        if t is None:
            continue
        dt = datetime.combine(target_date, t, tzinfo=tzinfo)
        item = dict(row)
        item["local_dt"] = dt
        item["is_recurring"] = True
        timed.append(item)

    timed.sort(key=lambda x: x["local_dt"])
    untimed.sort(key=lambda x: x.get("created_at") or "")
    return {"timed": timed, "untimed": untimed}


def list_family_routine_events() -> list[dict]:
    """Возвращает все семейные routine-события (для проверки в /init_routine)."""
    res = (
        get_client()
        .table("tasks")
        .select("*")
        .eq("visibility", "family")
        .eq("category", "routine")
        .execute()
    )
    return res.data or []


def update_task_fields(task_id: str, **fields: Any) -> None:
    """Обновить произвольные поля задачи."""
    if not fields:
        return
    get_client().table("tasks").update(fields).eq("id", task_id).execute()


def delete_task(task_id: str) -> None:
    get_client().table("tasks").delete().eq("id", task_id).execute()


def set_cook_for_weekday(task_id: str, weekday: str, user_id: str | None) -> None:
    """
    Назначить дежурного на конкретный день недели у пункта расписания.
    Если user_id is None — снять дежурство.
    Структура tasks.cook_by: {"MO":"<uuid>", "TU":"<uuid>", ...}
    """
    if weekday not in WEEKDAY_CODES:
        raise ValueError(f"Bad weekday: {weekday}")
    task = get_task(task_id)
    if not task:
        return
    cooks: dict[str, str] = dict(task.get("cook_by") or {})
    if user_id is None:
        cooks.pop(weekday, None)
    else:
        cooks[weekday] = user_id
    update_task_fields(task_id, cook_by=cooks or None)


# ---------- meal plans ----------

MEALS = ("lunch", "dinner", "chef")


def list_meal_plans() -> list[dict]:
    res = get_client().table("meal_plans").select("*").execute()
    return res.data or []


def get_meal_plan(weekday: str, meal: str) -> dict | None:
    res = (
        get_client()
        .table("meal_plans")
        .select("*")
        .eq("weekday", weekday)
        .eq("meal", meal)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_meal_plan(
    weekday: str,
    meal: str,
    *,
    dish: str | None = None,
    ingredients: list[str] | None = None,
) -> None:
    if weekday not in WEEKDAY_CODES:
        raise ValueError(f"Bad weekday: {weekday}")
    if meal not in MEALS:
        raise ValueError(f"Bad meal: {meal}")
    payload: dict[str, Any] = {
        "weekday": weekday,
        "meal": meal,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if dish is not None:
        payload["dish"] = dish
    if ingredients is not None:
        payload["ingredients"] = ingredients
    get_client().table("meal_plans").upsert(payload, on_conflict="weekday,meal").execute()


def clear_meal_plan(weekday: str, meal: str) -> None:
    get_client().table("meal_plans").delete().eq("weekday", weekday).eq("meal", meal).execute()


# ---------- cleaning plans ----------

def list_cleaning_plans() -> list[dict]:
    res = get_client().table("cleaning_plans").select("*").execute()
    return res.data or []


def get_cleaning_plan(weekday: str) -> dict | None:
    res = (
        get_client()
        .table("cleaning_plans")
        .select("*")
        .eq("weekday", weekday)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def set_cleaning_items(weekday: str, items: list[str]) -> None:
    if weekday not in WEEKDAY_CODES:
        raise ValueError(f"Bad weekday: {weekday}")
    get_client().table("cleaning_plans").upsert(
        {
            "weekday": weekday,
            "items": items,
            "updated_at": datetime.utcnow().isoformat(),
        },
        on_conflict="weekday",
    ).execute()


def add_cleaning_item(weekday: str, item: str) -> None:
    plan = get_cleaning_plan(weekday)
    current = list((plan or {}).get("items") or [])
    current.append(item)
    set_cleaning_items(weekday, current)


def remove_cleaning_item(weekday: str, index: int) -> None:
    plan = get_cleaning_plan(weekday)
    current = list((plan or {}).get("items") or [])
    if 0 <= index < len(current):
        current.pop(index)
        set_cleaning_items(weekday, current)


# ---------- ephemeral messages (самоочистка чата) ----------

def add_ephemeral_message(chat_id: int, message_id: int) -> None:
    get_client().table("ephemeral_messages").insert(
        {"chat_id": chat_id, "message_id": message_id}
    ).execute()


def list_expired_ephemeral(before: datetime) -> list[dict]:
    res = (
        get_client()
        .table("ephemeral_messages")
        .select("*")
        .lt("created_at", before.isoformat())
        .execute()
    )
    return res.data or []


def delete_ephemeral_records(ids: list[str]) -> None:
    if not ids:
        return
    get_client().table("ephemeral_messages").delete().in_("id", ids).execute()


# ---------- med plans (лекарства и БАДы) ----------

MED_MEALS = ("breakfast", "lunch", "dinner")


def list_med_plans() -> list[dict]:
    res = get_client().table("med_plans").select("*").execute()
    return res.data or []


def get_med_plan(person: str, meal: str) -> dict | None:
    res = (
        get_client()
        .table("med_plans")
        .select("*")
        .eq("person", person)
        .eq("meal", meal)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def set_med_items(person: str, meal: str, items: list[str]) -> None:
    if meal not in MED_MEALS:
        raise ValueError(f"Bad meal: {meal}")
    get_client().table("med_plans").upsert(
        {
            "person": person,
            "meal": meal,
            "items": items,
            "updated_at": datetime.utcnow().isoformat(),
        },
        on_conflict="person,meal",
    ).execute()


# ---------- shopping lists (списки покупок) ----------

def list_shopping_lists() -> list[dict]:
    res = get_client().table("shopping_lists").select("*").execute()
    return res.data or []


def get_shopping_list(owner: str) -> dict | None:
    res = (
        get_client()
        .table("shopping_lists")
        .select("*")
        .eq("owner", owner)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def set_shopping_items(owner: str, items: list[str]) -> None:
    get_client().table("shopping_lists").upsert(
        {
            "owner": owner,
            "items": items,
            "updated_at": datetime.utcnow().isoformat(),
        },
        on_conflict="owner",
    ).execute()


def add_shopping_item(owner: str, item: str) -> None:
    lst = get_shopping_list(owner)
    current = list((lst or {}).get("items") or [])
    current.append(item)
    set_shopping_items(owner, current)


def remove_shopping_item(owner: str, index: int) -> None:
    lst = get_shopping_list(owner)
    current = list((lst or {}).get("items") or [])
    if 0 <= index < len(current):
        current.pop(index)
        set_shopping_items(owner, current)


# ---------- recipes (книга рецептов) ----------

RECIPE_CATEGORIES = ("soup", "hot", "salad", "baking")


def list_recipes(category: str | None = None) -> list[dict]:
    q = get_client().table("recipes").select("*").order("name")
    if category:
        q = q.eq("category", category)
    return q.execute().data or []


def get_recipe(recipe_id: str) -> dict | None:
    res = get_client().table("recipes").select("*").eq("id", recipe_id).limit(1).execute()
    return res.data[0] if res.data else None


def upsert_recipe(
    *,
    recipe_id: str | None = None,
    name: str | None = None,
    category: str | None = None,
    ingredients: list[str] | None = None,
    instructions: str | None = None,
) -> dict:
    payload: dict[str, Any] = {"updated_at": datetime.utcnow().isoformat()}
    if name is not None:
        payload["name"] = name
    if category is not None:
        payload["category"] = category
    if ingredients is not None:
        payload["ingredients"] = ingredients
    if instructions is not None:
        payload["instructions"] = instructions
    if recipe_id:
        res = get_client().table("recipes").update(payload).eq("id", recipe_id).execute()
    else:
        res = get_client().table("recipes").insert(payload).execute()
    return res.data[0]


def delete_recipe(recipe_id: str) -> None:
    get_client().table("recipes").delete().eq("id", recipe_id).execute()
