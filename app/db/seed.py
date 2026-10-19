"""Day2：建库 → 建表 → 灌模拟数据。

用法（必须在项目根目录执行）：
    python -m app.db.seed

为什么用 -m：让 Python 把 app 当成包来加载，`import app.config` 才找得到。
直接 `python app/db/seed.py` 会因为找不到 app 包而报 ModuleNotFoundError。

这个脚本是幂等的：每次都 DROP → CREATE → INSERT，跑多少遍结果都一样。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "helpdesk.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# ---------------------------------------------------------------- 员工
# 字段顺序：(员工号, 姓名, 部门, 邮箱, 电话, 直属主管)
EMPLOYEES = [
    ("E001", "张明", "IT部",   "zhangming@example.com", "13800000001", None),
    ("E002", "李婷", "行政部", "liting@example.com",    "13800000002", None),
    ("E003", "王强", "财务部", "wangqiang@example.com", "13800000003", None),
    ("E004", "赵敏", "人事部", "zhaomin@example.com",   "13800000004", None),
    ("E005", "陈磊", "销售部", "chenlei@example.com",   "13800000005", None),
    ("E006", "刘洋", "IT部",   "liuyang@example.com",   "13800000006", "E001"),
    ("E007", "孙悦", "市场部", "sunyue@example.com",    "13800000007", "E005"),
    ("E008", "周涛", "采购部", "zhoutao@example.com",   "13800000008", "E003"),
]

# ---------------------------------------------------------------- 工单
# 字段顺序：(工单号, 标题, 描述, 状态, 优先级, 分类, 提单人, 处理人,
#            创建时间, 更新时间, 升级时间, 升级原因)
#
# 这份数据是刻意设计过的，Day4 的每个工具都能在里头找到可用样本：
#   - 四种状态齐全：open 4 条 / in_progress 4 条 / resolved 2 条 / closed 2 条
#   - T1005、T1009 没有处理人 → 演示「查工单」时要能正确显示"待分配"
#   - T1007、T1012 升级过 → 演示「升级工单」和"为什么是高优先级"
#   - updated_at 一律 >= created_at，升级时间落在两者之间
TICKETS = [
    ("T1001", "3楼打印机无法连接",
     "办公室3楼打印机显示离线，重启打印机和电脑都无效",
     "in_progress", "high", "IT", "E005", "E006",
     "2026-10-08 09:12", "2026-10-09 14:30", None, None),
    ("T1002", "VPN 客户端登录失败",
     "出差期间 VPN 一直提示认证失败，换网络也一样",
     "resolved", "normal", "IT", "E007", "E006",
     "2026-09-28 10:05", "2026-09-29 16:20", None, None),
    ("T1003", "9月差旅报销单审批卡住",
     "报销单提交三天，状态一直显示待审批",
     "open", "normal", "财务", "E005", "E003",
     "2026-10-10 09:40", "2026-10-10 09:40", None, None),
    ("T1004", "新员工工位安排",
     "下周一有新同事入职，需要提前安排工位和电脑",
     "in_progress", "normal", "行政", "E004", "E002",
     "2026-10-09 11:15", "2026-10-11 10:00", None, None),
    ("T1005", "会议室投影仪画面偏色",
     "501 会议室投影画面整体发黄，影响演示",
     "open", "low", "行政", "E007", None,
     "2026-10-12 15:30", "2026-10-12 15:30", None, None),
    ("T1006", "邮箱容量已满无法收信",
     "邮箱提示超出配额，收不到新邮件",
     "resolved", "normal", "IT", "E003", "E006",
     "2026-09-20 08:50", "2026-09-21 09:10", None, None),
    ("T1007", "采购审批权限异常",
     "采购系统里看不到待我审批的单据",
     "in_progress", "high", "采购", "E008", "E001",
     "2026-10-11 13:20", "2026-10-13 09:05",
     "2026-10-12 09:00", "影响采购流程，部门负责人要求当日闭环"),
    ("T1008", "考勤记录缺失申诉",
     "10月2日加班打卡记录丢失，需要补录",
     "open", "normal", "人事", "E005", "E004",
     "2026-10-13 09:15", "2026-10-13 09:15", None, None),
    ("T1009", "申请测试环境数据库权限",
     "项目需要访问测试库做联调，申请只读权限",
     "open", "normal", "IT", "E006", None,
     "2026-10-13 10:40", "2026-10-13 10:40", None, None),
    ("T1010", "办公电脑运行缓慢",
     "开机需要五分钟以上，打开表格经常卡顿",
     "closed", "low", "IT", "E002", "E006",
     "2026-09-15 09:00", "2026-09-18 17:30", None, None),
    ("T1011", "名片印制申请",
     "需要印制新版名片200张",
     "closed", "low", "行政", "E007", "E002",
     "2026-09-25 14:00", "2026-09-30 11:20", None, None),
    ("T1012", "工资条查询不到",
     "9月工资条没有收到，同事都能查到",
     "in_progress", "high", "财务", "E005", "E003",
     "2026-10-12 16:10", "2026-10-13 08:40",
     "2026-10-13 08:35", "涉及工资发放，财务主管升级处理"),
]

# ---------------------------------------------------------------- 政策元数据
# 字段顺序：(政策号, 标题, 分类, 一句话结论, 生效日期, 版本, 适用部门, 原文文件)
#
# 注意 source_file：文件名必须和 data/policies/ 下的实际文件完全一致，
# 否则 Day5 建索引时会找不到原文（check_db.py 会替你查这件事）。
POLICIES = [
    ("P001", "差旅报销标准", "报销",
     "住宿按职级分档上限（普通员工一线城市450元/晚），餐补100元/天，出差结束后15个工作日内提交",
     "2025-01-01", "v2", None, "P001-travel-expense.md"),
    ("P002", "年假与调休规则", "休假",
     "入职满1年享5天年假，周末加班1:1调休、法定节假日1:2，调休当年有效",
     "2024-07-01", "v1", None, "P002-leave.md"),
    ("P003", "办公用品采购流程", "采购",
     "单笔500元以下主管审批，500至5000元部门负责人审批，5000元以上分管副总审批",
     "2025-03-01", "v1", None, "P003-procurement.md"),
    ("P004", "信息系统账号与权限管理", "IT",
     "普通系统权限主管审批，生产库权限需双签，权限有效期90天，离职当日回收",
     "2024-01-15", "v3", None, "P004-it-account.md"),
]


def connect() -> sqlite3.Connection:
    """连 SQLite，并把两个容易被忘掉的地方一次性配置好。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # 查询结果可以用列名取值
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite 默认不开外键，每条连接都要手动开
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def seed(conn: sqlite3.Connection) -> None:
    # 先员工、再工单：工单有指向员工的外键。
    # 列名全部显式写出来，不用 INSERT INTO x VALUES (?,?) 这种位置绑定 ——
    # 位置绑定在表结构变动时不会报错，只会把数据悄悄插错列。
    conn.executemany(
        """INSERT INTO employees
               (employee_id, name, department, email, phone, manager_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        EMPLOYEES,
    )
    conn.executemany(
        """INSERT INTO tickets
               (ticket_id, title, description, status, priority, category,
                requester_id, assignee_id, created_at, updated_at,
                escalated_at, escalation_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        TICKETS,
    )
    conn.executemany(
        """INSERT INTO policies
               (policy_id, title, category, summary, effective_date,
                version, department, source_file)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        POLICIES,
    )
    conn.commit()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"[1/3] 数据库文件：{DB_PATH}")
    conn = connect()

    print("[2/3] 建表 ...")
    create_tables(conn)

    print("[3/3] 灌数据 ...")
    seed(conn)

    for table in ("employees", "tickets", "policies"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"      {table:<10} {count} 行")

    conn.close()
    print("")
    print("建库完成。补完数据后重跑本脚本即可（幂等，会整库重建）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
