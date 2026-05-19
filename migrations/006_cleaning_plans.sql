-- Этап 6: генеральная уборка — список действий на каждый день недели.

create table if not exists cleaning_plans (
  weekday text primary key check (weekday in ('MO','TU','WE','TH','FR','SA','SU')),
  items text[] not null default '{}',
  updated_at timestamptz not null default now()
);
