-- Этап 7: самоочистка чата — сообщения удаляются через час.
-- Храним id отправленных/полученных сообщений, фоновый job чистит старое.

create table if not exists ephemeral_messages (
  id uuid primary key default gen_random_uuid(),
  chat_id bigint not null,
  message_id bigint not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_ephemeral_created_at on ephemeral_messages(created_at);
