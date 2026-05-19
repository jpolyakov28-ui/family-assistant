-- Этап 10: «будильник» на задаче — настойчивое напоминание, пока задача не закрыта.

-- Будильник включён?
alter table tasks
  add column if not exists alarm boolean not null default false;

-- Когда будильник звонил последний раз (для повтора каждые ~10 минут).
alter table tasks
  add column if not exists alarm_last_ring timestamptz;
