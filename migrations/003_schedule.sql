-- Этап 3: расписание дня (повторяющиеся пункты + категории + дата без времени).

alter table tasks
  add column if not exists category text
    check (category in ('routine','lesson','trip','other'));

-- Локальное время суток для повторяющихся пунктов расписания: 'HH:MM'.
-- Для разовых задач остаётся NULL, а время живёт в due_at.
alter table tasks
  add column if not exists time_local text;

-- Отметка «у задачи есть точное время». При false — задача показывается
-- в блоке «Без времени» под основным таймлайном.
-- Существующие задачи получают true (как и было).
alter table tasks
  add column if not exists due_has_time boolean not null default true;

create index if not exists idx_tasks_recurrence on tasks(recurrence)
  where recurrence is not null;

create index if not exists idx_tasks_category on tasks(category)
  where category is not null;
