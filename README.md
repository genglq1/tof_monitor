# 信托TOF投后管理系统

信托 TOF（Trust of Funds）投后管理工具：解析估值表 → 持仓明细 → 估值统计 →
管理人回填 → 穿透报告，并支持独立的**净值分析**。所有功能统一通过 `main.py`
的 `--mode` 参数驱动，旧版独立脚本（`run_holding.py` / `run_valuation.py` /
`run_penetration.py` / `analyze_nav.py` / `manager_pipeline.py`）已全部废弃移除，
其逻辑已收敛进 `core` / `parsers` / `reporters` 模块并由 `main.py` 统一调度。
统一入口请用 `main.py`。

## 项目结构

```
tof_monitor/
├── main.py                      # 唯一入口：--mode email|local|classify|nav
├── config.yaml                  # 配置文件（路径契约 + 邮件配置）
├── README.md                    # 本文档
│
├── core/                       # 核心模块
│   ├── models.py               # 数据模型（HoldingDetail / ValuationStat / PenetrationItem ...）
│   ├── pipeline.py              # 处理管道（资产概览 + 持仓明细）
│   ├── registry.py              # 解析器注册表
│   ├── rules.py                 # 规则收口（产品类型识别 / 文件名解析 / 简称提取）
│   ├── manager.py               # 管理人全称回填（P3）
│   └── nav_analyzer.py          # 净值分析器（P5）
│
├── parsers/                    # 估值表解析器
│   ├── base.py                 # 基类
│   ├── asset_overview.py        # 资产概览解析
│   ├── holding_detail.py        # 持仓明细解析（完整表 + 标准表）
│   ├── valuation_stats.py       # 估值统计解析（P2）
│   └── penetration.py           # 穿透计算解析（P4）
│
├── collectors/                  # 文件采集器
│   ├── email_collector.py       # 邮件采集
│   ├── file_collector.py        # 本地文件采集
│   ├── file_classifier.py       # 文件分类器
│   ├── mail_downloader.py       # 邮件附件下载
│   └── mail_list.py             # 邮件列表获取
│
├── reporters/                   # 报表生成
│   ├── excel_reporter.py        # 展示报告（资产概览 / 持仓明细报告）
│   ├── holding_reporter.py      # 持仓完整表 / 标准表写出（P1）
│   ├── valuation_reporter.py    # 估值统计表写出（P2）
│   ├── penetration_reporter.py  # 穿透报告写出（P4）
│   └── nav_reporter.py          # 净值分析结果写出（P5）
│
├── storage/                    # 文件存储
│   └── file_store.py            # 归档整理
│
├── utils/                      # 工具函数
│   ├── config.py                # 配置加载
│   ├── helpers.py               # 辅助函数
│   └── logger.py                # 日志配置
│
└── data/                       # 数据目录（运行时生成）
    ├── input/                   # 源数据（只读输入，手工 / 邮件放入）
    │   ├── 信托层估值表/           # 信托计划层估值表（local 扫描 / 估值统计扫描）
    │   ├── 底层估值表/           # 证券投资基金估值表（穿透用，classify 输出落点）
    │   ├── 净值表/               # 净值表文件（nav 模式输入，与估值表不同）
    │   └── 管理人全量池/
    │       └── MANAGER_FULLNAME.xlsx  # 管理人全称映射表（需人工维护）
    ├── work/                    # 中间工作表（程序生成，可重建）
    │   ├── 信托计划持仓_完整.xlsx  # 持仓明细（完整，含管理人回填）
    │   ├── 信托计划持仓_标准.xlsx  # 持仓明细（标准，下游穿透/分类强依赖）
    │   └── 信托产品估值统计结果.xlsx  # 估值统计结果（下游穿透强依赖）
    ├── output/                  # 最终报告（程序生成）
    │   ├── 持仓明细_{date}.xlsx   # 展示报告
    │   ├── 穿透报告/             # 穿透报告输出目录
    │   └── 净值分析/             # 净值分析结果输出目录
    ├── cache/                   # 下载 / 临时缓存（可清理重建）
    │   ├── _原始邮件/            # 邮件下载原始附件
    │   └── mail_hash.json       # 下载去重哈希
    └── archive/                 # 历史归档（体积大，已 gitignore）
```

---

## 六种运行模式

`main.py` 通过 `--mode` 选择运行模式，默认 `holding`（持仓明细 + 估值统计 + 管理人回填）；`local` 作为组合模式（holding + penetration）保留但需显式指定：

| 模式 | 作用 | 输入 | 输出 |
|------|------|------|------|
| `email` | 下载邮件附件 + 自动分类 | 邮件系统 | `data/cache/_原始邮件/` + `data/cache/邮件列表.xlsx` + `data/input/底层估值表/` |
| `local` | 持仓明细 + 估值统计 + 管理人回填 + 穿透报告（= `holding` + `penetration`） | `data/input/信托层估值表/` + `data/input/底层估值表/` | 同下两者合计 |
| `holding` | 持仓明细 + 估值统计 + 管理人回填（不含穿透） | `data/input/信托层估值表/` | `work/` 持仓明细 + 估值统计表 + 归档 |
| `penetration` | 仅穿透报告（基于已有工作表，轻量独立） | `work/信托计划持仓_标准.xlsx` + `work/信托产品估值统计结果.xlsx` + `data/input/底层估值表/` | `output/穿透报告/` |
| `classify` | 仅对已有附件重新分类 | `data/cache/_原始邮件/` + 标准表 | `data/input/底层估值表/` |
| `nav` | 净值分析（独立于估值管道） | `data/input/净值表/` | `data/output/净值分析/` |

> 说明：`local` 为组合模式（先 `holding` 后 `penetration`），适合一次性全跑；
> 若只想重跑穿透报告（标准表/估值统计表已存在），可单独执行 `python main.py --mode penetration`，无需重新解析信托层估值表。

---

## 推荐工作流

```
data/input/信托层估值表/（邮件附件解压 / 手工放入的信托层估值表）
    │
    ├─[可选] 第一步：下载邮件附件 + 自动分类
    │       python main.py --mode email
    │           ↓ 下载到 data/cache/_原始邮件/，分类到 data/input/底层估值表/
    │
    ├─ 第二步：本地解析，生成持仓明细 + 估值统计 + 管理人回填
    │       python main.py --mode holding
    │           ↓ 依次产出：
    │           1) work/信托计划持仓_完整.xlsx + 信托计划持仓_标准.xlsx
    │           2) 管理人回填（写入完整表，依赖 MANAGER_FULLNAME.xlsx）
    │           3) work/信托产品估值统计结果.xlsx
    │           4) 归档（若配置了 archive_base）
    │
    ├─ 第三步：穿透报告（可单独重跑，依赖第二步产出的工作表）
    │       python main.py --mode penetration
    │           ↓ 产出：
    │           output/穿透报告/{项目代码}_{信托名称}_{日期}_穿透报告.xlsx
    │
    │   （以上两步等价于一步：python main.py --mode local）
    │
    ├─[可选] 仅重新分类（无需重新下载）
    │       python main.py --mode classify
    │
    └─[独立] 净值分析（与估值管道解耦，可随时单独跑）
            python main.py --mode nav
```

> 说明：`local` 模式一步产出持仓明细、估值统计、管理人回填、穿透报告，无需再
> 分别运行旧版 `run_holding.py` / `run_valuation.py` / `run_penetration.py`。
> 这些旧脚本已废弃移除，统一入口请用 `main.py`。

---

## 第一步：下载邮件附件（可选）

```bash
python main.py --mode email
```

- 读取 `config.yaml` 的 `email` 段配置（服务器 / 账号 / 搜索范围）。
- 搜索范围两种模式：相对天数 `search_days` 优先；为空则使用绝对日期
  `search_since` / `search_before`（命令行 `--since` / `--before` 可覆盖）。
- 断点续传：下载器自动跳过已存在的文件夹。
- 下载完成后自动按「投资标的」分类到 `data/input/底层估值表/`。

---

## 第二步：本地解析，生成全部报告

```bash
python main.py --mode local [--date 20260430]
```

输入：`data/input/信托层估值表/`（及配置的可选底层估值表目录 `underlying_data` = `data/input/底层估值表/`）
输出（按依赖顺序，全部写入 `config.yaml` 固定路径）：

1. **持仓明细**：`data/work/信托计划持仓_完整.xlsx`（含管理人回填）
   + `信托计划持仓_标准.xlsx`（下游穿透 / 分类强依赖）。
2. **管理人回填**：读取完整表 → 按 `data/input/管理人全量池/MANAGER_FULLNAME.xlsx`
   回填「产品类型」「管理人名称」→ 写回完整表。映射文档缺失则告警跳过。
3. **估值统计**：`data/work/信托产品估值统计结果.xlsx`（下游穿透强依赖）。
4. **穿透报告**：`data/output/穿透报告/{项目代码}_{信托名称}_{日期}_穿透报告.xlsx`
   对每个标准表中的项目代码，基于标准表 + 估值统计表 + 底层估值表生成；
   无信托目录或持仓则告警跳过。

> 公募基金：持仓明细提取阶段已支持公募基金（父行科目名含「基金」且不含
> 「资产管理」「私募」即判为公募），其他阶段保持现状。

---

## 仅重新分类

```bash
python main.py --mode classify
```

已有附件、无需重新下载时，仅按「投资标的」重新分类到 `data/input/底层估值表/`。
依赖标准表（`holding_std`）已存在。

---

## 净值分析（独立模式）

```bash
python main.py --mode nav
```

- 输入：`data/input/净值表/`（由 `config.yaml` 的 `nav_input` 指定，与估值表**不同**目录）。
- 输出：`data/output/净值分析/净值分析结果.xlsx` + 各产品净值曲线图 PNG。
- 该模式与估值管道**完全解耦**，单独运行，不触发持仓 / 估值 / 穿透。

### 净值表输入约定

`nav_input` 目录下的每个 `.xlsx` / `.xls` / `.csv` 文件代表**一个产品、多日序列**。
推荐文件命名：`{任意前缀}_{产品代码}_{产品名称}_{日期}.xlsx`（产品代码形如
`ZY0NV1`，会被解析器用作产品标识）。

单文件内需包含以下列（列名含关键字即可被识别，大小写不敏感）：

| 列关键字 | 含义 | 识别规则 |
|----------|------|----------|
| `日期` / `date` | 净值日期 | 列名含「日期」或「date」 |
| `累计净值` / `累计NAV` | 累计单位净值 | 列名同时含「累计」与「净值」/「nav」 |
| `产品名称` / `产品代码`（可选） | 产品标识 | 用于报告展示；缺失时回退到文件名中的产品代码 |

> 注：净值分析按「单文件 = 单产品多日序列」处理；同目录下每个文件各产出一行
> 指标（年化收益、最大回撤、夏普、卡玛等），并按自然年拆分「{年份}年收益」列。

---

## 配置（config.yaml）

`paths` 段为路径契约，下游模块强依赖固定路径，请勿随意改动：

```yaml
paths:
  raw_data: "data/input/信托层估值表"             # 信托层估值表目录（local 扫描 / 估值统计扫描）
  cache_dir: "data/cache"                       # 邮件下载与临时缓存（_原始邮件/、mail_hash.json）
  output: "data/output"                         # 报告输出根目录
  archive_base: "data/archive"                  # 归档根目录（可选）
  logs: "logs"
  holding_full: "data/work/信托计划持仓_完整.xlsx"   # 下游强依赖
  holding_std:  "data/work/信托计划持仓_标准.xlsx"   # 下游强依赖
  valuation_stats: "data/work/信托产品估值统计结果.xlsx"   # 下游强依赖
  underlying_data: "data/input/底层估值表"        # 底层估值表目录（穿透用，classify 输出），未配置则不跑穿透
  manager_mapping: "data/input/管理人全量池/MANAGER_FULLNAME.xlsx"  # 管理人回填映射（需人工维护）
  nav_input: "data/input/净值表"                 # 净值表目录（nav 模式）
```

`email` 段配置邮件服务器与搜索范围（详见文件内注释）。

---

## 依赖

```bash
pip install openpyxl pandas loguru matplotlib numpy
```

- `matplotlib` / `numpy`：净值分析绘图与指标计算（无头环境自动使用 `Agg` 后端）。
- `loguru`：日志（本机若缺失需 `pip install loguru`）。

---

## 注意

- 文件名含「提示函」的附件会被自动跳过。
- 分类（`classify`）依赖标准表（`holding_std`）已生成。
- 穿透报告依赖标准表 + 估值统计表 + 底层估值表（信托目录）均已就绪。
- 管理人回填依赖 `MANAGER_FULLNAME.xlsx` 映射文档，缺失则跳过（不影响其他报告）。
- 净值分析（`nav`）与估值管道解耦，可独立于其他步骤运行。
- 旧版独立脚本（`run_holding.py` / `run_valuation.py` / `run_penetration.py` /
  `analyze_nav.py` / `manager_pipeline.py`）已废弃移除，统一入口请用 `main.py`。
