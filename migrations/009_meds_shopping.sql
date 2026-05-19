-- Этап 9: лекарства и БАДы по членам семьи + списки покупок.

-- Лекарства/БАДы: на каждого члена семьи — завтрак/обед/ужин.
create table if not exists med_plans (
  person text not null,
  meal text not null check (meal in ('breakfast','lunch','dinner')),
  items text[] not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (person, meal)
);

-- Списки покупок: 'family' (общий) либо имя члена семьи.
create table if not exists shopping_lists (
  owner text primary key,
  items text[] not null default '{}',
  updated_at timestamptz not null default now()
);
