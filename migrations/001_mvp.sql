-- Family Assistant — MVP schema (Этап 1)

-- Пользователи семьи
create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  name text not null,
  role text not null default 'member',
  timezone text not null default 'Europe/Moscow',
  created_at timestamptz default now()
);

-- Группы (Родители, Дети, Все...)
create table if not exists groups (
  id uuid primary key default gen_random_uuid(),
  name text not null
);

create table if not exists user_groups (
  user_id uuid references users(id) on delete cascade,
  group_id uuid references groups(id) on delete cascade,
  primary key (user_id, group_id)
);

-- Универсальные задачи
create table if not exists tasks (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('todo','reminder','event')),
  title text not null,
  notes text,
  due_at timestamptz,
  recurrence text,
  status text not null default 'open' check (status in ('open','done','snoozed')),
  visibility text not null default 'assignees' check (visibility in ('private','assignees','family')),
  created_by uuid references users(id),
  created_at timestamptz default now()
);

create table if not exists task_assignees (
  task_id uuid references tasks(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  primary key (task_id, user_id)
);

-- Индексы для быстрого поиска "что у меня сегодня"
create index if not exists idx_tasks_due_at on tasks(due_at);
create index if not exists idx_tasks_status on tasks(status);
create index if not exists idx_task_assignees_user on task_assignees(user_id);

-- Базовая группа "Все"
insert into groups (name)
select 'Все' where not exists (select 1 from groups where name = 'Все');
