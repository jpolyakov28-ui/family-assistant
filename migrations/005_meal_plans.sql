-- Этап 5: продуктовое меню на неделю (обед + ужин на каждый день).
-- Завтрак не храним.

create table if not exists meal_plans (
  weekday text not null check (weekday in ('MO','TU','WE','TH','FR','SA','SU')),
  meal text not null check (meal in ('lunch','dinner')),
  dish text,
  ingredients text[] not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (weekday, meal)
);
