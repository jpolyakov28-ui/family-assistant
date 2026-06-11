-- Allow family members without Telegram accounts (virtual users)
ALTER TABLE users ALTER COLUMN telegram_id DROP NOT NULL;

-- Add virtual family members
INSERT INTO users (name)
SELECT t.name
FROM (VALUES ('Мама'), ('Миша'), ('Захар'), ('Антонина')) AS t(name)
WHERE NOT EXISTS (
    SELECT 1 FROM users u WHERE u.name = t.name AND u.telegram_id IS NULL
);
