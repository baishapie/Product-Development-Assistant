-- =============================================================================
-- ProductMind AI — PostgreSQL 初始化脚本
--
-- 用途：
--   1) （可选）创建角色与数据库（示例，按需取消注释）
--   2) 应用运行元数据表 runs（任务列表/状态/产物路径）
--   3) LangGraph 检查点表（PostgresSaver 断点续跑所需）
--
-- 用法：
--   psql "host=<HOST> port=5432 dbname=<DB> user=<USER>" -f scripts/init_db.sql
--   或应用内直接启动：STORAGE_BACKEND=postgres 时 RunManager 会自动建 runs 表，
--   并由 PostgresSaver.setup() 建检查点表。
--
-- 说明：
--   - 脚本幂等（IF NOT EXISTS）。
--   - 检查点表 DDL 对齐 langgraph-checkpoint-postgres 3.1.2；
--     应用的 setup() 会幂等执行并记录迁移版本。
--   - 若走 SSH 隧道，先建好隧道再用本地端口连接（见 secrets/ssh/README.md）。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 0) 角色与数据库（示例；CREATE DATABASE 不能在事务中执行，请单独连接执行）
-- -----------------------------------------------------------------------------
-- CREATE ROLE productmind LOGIN PASSWORD 'change-me';
-- CREATE DATABASE productmind OWNER productmind ENCODING 'UTF8'
--     LC_COLLATE 'zh_CN.UTF-8' LC_CTYPE 'zh_CN.UTF-8' TEMPLATE template0;
-- \connect productmind
-- GRANT ALL PRIVILEGES ON DATABASE productmind TO productmind;
-- GRANT ALL ON SCHEMA public TO productmind;


-- -----------------------------------------------------------------------------
-- 1) 应用运行元数据：runs
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,                       -- 与 run_id 相同，对齐检查点
    idea          TEXT NOT NULL,
    status        TEXT NOT NULL,                       -- running|awaiting_review|done|failed
    current_task  TEXT,
    plan          JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed     JSONB NOT NULL DEFAULT '[]'::jsonb,
    error         TEXT,
    output_path   TEXT,
    review        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

COMMENT ON TABLE runs IS 'ProductMind AI 运行元数据（任务列表/状态/产物路径）';


-- -----------------------------------------------------------------------------
-- 2) LangGraph 检查点表（对齐 langgraph-checkpoint-postgres 3.1.2）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id            TEXT NOT NULL,
    checkpoint_ns        TEXT NOT NULL DEFAULT '',
    checkpoint_id        TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type                 TEXT,
    checkpoint           JSONB NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL,
    version       TEXT NOT NULL,
    type          TEXT NOT NULL,
    blob          BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    task_path     TEXT NOT NULL DEFAULT '',
    idx           INTEGER NOT NULL,
    channel       TEXT NOT NULL,
    type          TEXT,
    blob          BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- 检查点查询索引（库内迁移使用 CONCURRENTLY；此处用普通方式，便于脚本整体执行）
CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx        ON checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx   ON checkpoint_blobs(thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx  ON checkpoint_writes(thread_id);
