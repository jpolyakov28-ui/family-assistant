-- Этап 2: предварительные напоминания + snooze + повторные триггеры

-- Минуты ДО due_at, в которые нужно прислать напоминание.
-- Пустой массив = только в момент due_at.
-- Пример: [60, 0] = за час и в момент. [30, 5, 0] = за 30, за 5, в момент.
alter table tasks
  add column if not exists lead_minutes int[] not null default '{}';

-- Какие из lead_minutes уже отправлены (чтобы не дублировать).
-- Значение -1 используем как маркер "напоминание в момент due_at отправлено".
alter table tasks
  add column if not exists sent_offsets int[] not null default '{}';

-- Раньше due_at-напоминание помечало задачу status='snoozed'.
-- Теперь отслеживаем через sent_offsets, статус снова 'open'.
update tasks set status = 'open' where status = 'snoozed';
