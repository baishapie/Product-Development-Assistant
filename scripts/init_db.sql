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
--   - 脚本幂等（IF NOT EXISTS / COMMENT 覆盖设置）。
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
--    作用：保存一次工作流运行的任务信息与状态，用于历史任务列表、状态查询、
--          产物定位与异常恢复（配合检查点表）。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    idea          TEXT NOT NULL,
    status        TEXT NOT NULL,
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

COMMENT ON TABLE runs IS '运行元数据：一次工作流运行的任务信息、状态、进度与产物路径（供列表/查看/恢复）';
COMMENT ON COLUMN runs.run_id       IS '运行唯一标识（同时用作 LangGraph 的 thread_id）';
COMMENT ON COLUMN runs.thread_id    IS 'LangGraph 检查点线程 ID，等于 run_id，用于断点续跑';
COMMENT ON COLUMN runs.idea         IS '用户输入的产品想法（原始需求文本）';
COMMENT ON COLUMN runs.status       IS '运行状态：running=执行中 / awaiting_review=等待人工确认 / done=已完成 / failed=失败';
COMMENT ON COLUMN runs.current_task IS '当前执行的节点标识（如 supervisor/product/architect/reviewer/document）';
COMMENT ON COLUMN runs.plan         IS 'Supervisor 规划的任务顺序，JSON 数组，元素为 product/architect';
COMMENT ON COLUMN runs.completed    IS '已完成的任务列表，JSON 数组，元素为 product/architect';
COMMENT ON COLUMN runs.error        IS '失败信息；成功时为 NULL';
COMMENT ON COLUMN runs.output_path  IS '生成文档的落盘路径（output/{run_id}/product_document.md）';
COMMENT ON COLUMN runs.review       IS '待人工确认的视图数据，JSON：stage/round/max_rounds/artifact；无待确认时为 NULL';
COMMENT ON COLUMN runs.created_at   IS '创建时间（UTC）';
COMMENT ON COLUMN runs.updated_at   IS '最近更新时间（UTC），每次状态变更刷新';


-- -----------------------------------------------------------------------------
-- 2) LangGraph 检查点表（对齐 langgraph-checkpoint-postgres 3.1.2）
--    作用：按 thread_id 保存图状态快照，使 interrupt() 暂停后与进程重启后
--          都能从最近检查点继续执行（断点续跑）。
-- -----------------------------------------------------------------------------

-- 迁移版本表
CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);
COMMENT ON TABLE  checkpoint_migrations    IS 'LangGraph 检查点迁移版本记录表（PostgresSaver.setup() 维护）';
COMMENT ON COLUMN checkpoint_migrations.v  IS '已应用的迁移版本号（单调递增，对应库内 MIGRATIONS 列表下标）';

-- 检查点主表
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
COMMENT ON TABLE  checkpoints                        IS 'LangGraph 检查点快照：每个线程/命名空间下的图状态快照（断点续跑的核心）';
COMMENT ON COLUMN checkpoints.thread_id              IS '线程 ID（与 runs.run_id 相同，一次运行为一个线程）';
COMMENT ON COLUMN checkpoints.checkpoint_ns          IS '检查点命名空间，用于区分主图与子图（默认空字符串）';
COMMENT ON COLUMN checkpoints.checkpoint_id          IS '检查点 ID（按时间单调递增，用于排序与回放）';
COMMENT ON COLUMN checkpoints.parent_checkpoint_id   IS '父检查点 ID，形成检查点链（NULL 表示首检查点）';
COMMENT ON COLUMN checkpoints.type                   IS '检查点序列化类型标识';
COMMENT ON COLUMN checkpoints.checkpoint             IS '检查点内容（JSONB）：含 channel_versions/channel_values/versions_seen 等';
COMMENT ON COLUMN checkpoints.metadata               IS '检查点元数据（JSONB）：如 source/step/writes 等执行信息';

-- 通道值块表
CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL,
    version       TEXT NOT NULL,
    type          TEXT NOT NULL,
    blob          BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);
COMMENT ON TABLE  checkpoint_blobs               IS 'LangGraph 通道值块：按（线程, 命名空间, 通道, 版本）存储的状态值二进制块';
COMMENT ON COLUMN checkpoint_blobs.thread_id     IS '线程 ID';
COMMENT ON COLUMN checkpoint_blobs.checkpoint_ns IS '检查点命名空间';
COMMENT ON COLUMN checkpoint_blobs.channel       IS '状态通道名（对应图的 state 字段，如 results/completed）';
COMMENT ON COLUMN checkpoint_blobs.version       IS '该通道值的版本号（由检查点引用）';
COMMENT ON COLUMN checkpoint_blobs.type          IS '值的类型标识（serializer 用，如 json/msgpack）';
COMMENT ON COLUMN checkpoint_blobs.blob          IS '序列化后的值字节（可为 NULL，表示空值占位）';

-- 待写/中间写入表
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
COMMENT ON TABLE  checkpoint_writes               IS 'LangGraph 检查点写入：记录某检查点下各任务的通道写入（含 pending writes / 子任务发送）';
COMMENT ON COLUMN checkpoint_writes.thread_id     IS '线程 ID';
COMMENT ON COLUMN checkpoint_writes.checkpoint_ns IS '检查点命名空间';
COMMENT ON COLUMN checkpoint_writes.checkpoint_id IS '所属检查点 ID';
COMMENT ON COLUMN checkpoint_writes.task_id       IS '产生该写入的任务（节点）ID';
COMMENT ON COLUMN checkpoint_writes.task_path     IS '任务路径（用于子图/嵌套任务的定位）';
COMMENT ON COLUMN checkpoint_writes.idx           IS '同一任务内写入序号（保证顺序）';
COMMENT ON COLUMN checkpoint_writes.channel       IS '被写入的状态通道名';
COMMENT ON COLUMN checkpoint_writes.type          IS '值的类型标识（可为空）';
COMMENT ON COLUMN checkpoint_writes.blob          IS '序列化后的写入值字节';

-- 检查点查询索引（库内迁移使用 CONCURRENTLY；此处用普通方式，便于脚本整体执行）
CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx        ON checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx   ON checkpoint_blobs(thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx  ON checkpoint_writes(thread_id);
