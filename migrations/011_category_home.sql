-- Этап 11: новая категория задач — «Дом».

alter table tasks drop constraint if exists tasks_category_check;

alter table tasks add constraint tasks_category_check
  check (category in (
    'routine','lesson','trip','other','work','congrats','shopping','home'
  ));
