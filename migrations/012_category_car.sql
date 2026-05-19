-- Этап 12: новая категория задач — «Машина».

alter table tasks drop constraint if exists tasks_category_check;

alter table tasks add constraint tasks_category_check
  check (category in (
    'routine','lesson','trip','other','work','congrats','shopping','home','car'
  ));
