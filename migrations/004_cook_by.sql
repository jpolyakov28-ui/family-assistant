-- Этап 4: дежурный по дням недели у повторяющегося пункта расписания.
-- Структура: {"MO":"<user_uuid>", "TU":"<user_uuid>", ...}. Ключи отсутствуют — нет дежурного.

alter table tasks
  add column if not exists cook_by jsonb;
