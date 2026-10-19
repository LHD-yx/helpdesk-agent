-- HelpDesk Agent · 数据层表结构
--
-- 五条设计原则（面试要能讲出来）：
--   1. 主键用业务可读编号（E001 / T1001 / P001）——人和模型都读得懂，
--      Day4 让模型生成工具参数时，它传的就是这种编号，不需要额外查一次映射。
--   2. 时间统一存 ISO8601 文本（SQLite 没有原生日期类型），
--      格式固定为 'YYYY-MM-DD HH:MM'，字符串比较等于时间比较。
--   3. 取值有限的字段用 CHECK 收口：错别字在入库那一刻就被拒绝，
--      而不是等到 Day6 做意图路由时才发现「状态值对不上」。
--   4. 关系用外键表达，但 SQLite 的外键默认是关的 —— 见 app/db/seed.py 的 connect()。
--      注意：PRAGMA foreign_keys 不要在下面写，它在事务里是空操作，必须设在连接上。
--   5. DROP 顺序从"被引用方"往"引用方"倒着来：先删 tickets，再删 employees。

DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS policies;

-- ============================================================ 员工
CREATE TABLE employees (
    employee_id  TEXT PRIMARY KEY,                 -- E001
    name         TEXT NOT NULL,
    department   TEXT NOT NULL,
    email        TEXT,
    phone        TEXT,
    -- 自引用外键：主管也是员工。允许为空 = 这个人没有上级（比如部门负责人）。
    manager_id   TEXT REFERENCES employees(employee_id)
);

-- ============================================================ 工单
CREATE TABLE tickets (
    ticket_id    TEXT PRIMARY KEY,                 -- T1001
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',

    -- 状态机：open → in_progress → resolved → closed
    -- 用字符串而不是 1/2/3，因为日志、SQL 查询、模型输出都能直接读懂。
    status       TEXT NOT NULL
                 CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    priority     TEXT NOT NULL
                 CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

    -- 分类用中文：这是业务分类，模型直接匹配用户说的"财务""行政"更准。
    -- （注意：这和 policies.category 不是同一套分类，见下方说明。）
    category     TEXT NOT NULL
                 CHECK (category IN ('IT', '行政', '财务', '人事', '采购', '其他')),

    requester_id TEXT NOT NULL REFERENCES employees(employee_id),   -- 提单人，必然有
    assignee_id  TEXT REFERENCES employees(employee_id),            -- 处理人，可能还没分配

    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,

    -- 升级记录：NULL 表示从未升级。
    -- 为什么不只改 priority：只看 priority 分不清"创建时就填高了"还是"后来被升级了"，
    -- 而且丢了"谁在什么时候、因为什么升级的"这条信息。
    -- 局限：这里只存最近一次升级。要完整历史需要再加一张 status_history 表，
    -- 两周版不做 —— 面试被问到就如实说这是刻意的简化。
    escalated_at      TEXT,
    escalation_reason TEXT,

    -- 业务不变式交给数据库守：要么都没升级，要么两个字段都有值。
    -- 防止出现"有升级时间但不知道原因"这种半截数据。
    CHECK ((escalated_at IS NULL) = (escalation_reason IS NULL))
);

CREATE INDEX idx_tickets_status    ON tickets(status);
CREATE INDEX idx_tickets_requester ON tickets(requester_id);
CREATE INDEX idx_tickets_assignee  ON tickets(assignee_id);

-- ============================================================ 政策
CREATE TABLE policies (
    policy_id      TEXT PRIMARY KEY,               -- P001
    title          TEXT NOT NULL,
    -- 政策按"主题"分类（报销 / 休假 / 考勤 / 采购 / IT），
    -- 工单按"处理部门"分类。两者维度不同，所以故意不对齐。
    category       TEXT NOT NULL
                   CHECK (category IN ('报销', '休假', '考勤', '采购', 'IT')),
    summary        TEXT NOT NULL,                  -- 一句话结论，供快速查询
    effective_date TEXT NOT NULL,                  -- 生效日期，用于冲突裁决
    version        TEXT NOT NULL DEFAULT 'v1',
    department     TEXT,                           -- NULL = 适用全公司

    -- Day5 的 RAG 靠这个字段做引用溯源：答案末尾要能标出"出自哪份原文"。
    -- 文件名必须和 data/policies/ 下的实际文件一一对应。
    source_file    TEXT NOT NULL
);

-- policies 只有几行，全表扫描比走索引还快，所以故意不建索引。
