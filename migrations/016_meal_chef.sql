-- Расширяем допустимые значения поля meal для хранения дежурного по кухне
ALTER TABLE meal_plans DROP CONSTRAINT IF EXISTS meal_plans_meal_check;
ALTER TABLE meal_plans ADD CONSTRAINT meal_plans_meal_check
    CHECK (meal IN ('lunch', 'dinner', 'chef'));
