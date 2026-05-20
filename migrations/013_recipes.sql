-- Книга рецептов: справочник блюд с ингредиентами и способом приготовления.
create table if not exists recipes (
    id           uuid primary key default gen_random_uuid(),
    name         text not null,
    category     text not null check (category in ('soup', 'hot', 'salad', 'baking')),
    ingredients  text[] not null default '{}',
    instructions text not null default '',
    updated_at   timestamptz not null default now()
);

create index if not exists idx_recipes_category on recipes(category);
