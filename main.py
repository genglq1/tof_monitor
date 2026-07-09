import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
# 过滤 xlrd 读取旧版 xls 的 OLE2 stream WARNING 输出（是 print，非 warnings）
class _OLE2Filter:
    def write(self, text):
        if "OLE2 stream" in text:
            return
        sys.__stdout__.write(text)
    def flush(self):
        sys.__stdout__.flush()

sys.stdout = _OLE2Filter()
sys.stderr = _OLE2Filter()

from utils.config import load_config
from utils.logger import setup_logger
from core.registry import registry
from parsers.asset_overview import AssetOverviewParser
from parsers.holding_detail import HoldingDetailParser
from collectors.email_collector import EmailCollector
from collectors.file_collector import FileCollector
from collectors.file_classifier import FileClassifier


def _run_classifier(project_file, raw_dir, classifier_output, since, before):
    classifier = FileClassifier(
        project_file=project_file,
        source_dir=raw_dir / "_原始邮件",
        output_base=classifier_output,
        filename_keyword="估值表",
        start_date=since,
        end_date=before,
        short_name_col="简称"
    )
    return classifier.run()
from core.pipeline import Pipeline
from reporters.excel_reporter import ExcelReporter
from storage.file_store import FileStore

def main():
    parser = argparse.ArgumentParser(description="信托TOF投后管理系统")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--mode", choices=["email", "local", "holding", "penetration", "classify", "nav"], default="holding")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--since", help="邮件起始日期 (YYYYMMDD)")
    parser.add_argument("--before", help="邮件结束日期 (YYYYMMDD)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logger = setup_logger(cfg["paths"]["logs"])

    # 注册解析器
    registry.register("asset_overview", AssetOverviewParser())
    registry.register("holding_detail", HoldingDetailParser())

    # 采集文件
    if args.mode == "email":
        ec = EmailCollector(cfg["email"])
        ec.connect()

        # 确定起始和结束日期
        # 优先级：命令行参数 > search_days(相对) > search_since/search_before(绝对)
        days = cfg.get("email", {}).get("search_days")
        if days:
            # 相对日期模式：search_days 优先
            since = (datetime.now() - timedelta(days=int(days))).strftime("%Y%m%d")
            before = datetime.now().strftime("%Y%m%d")
        else:
            # 绝对日期模式
            since = args.since or cfg.get("email", {}).get("search_since", "")
            before = args.before or cfg.get("email", {}).get("search_before", "")
            if not since and not before:
                since = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                before = datetime.now().strftime("%Y%m%d")
            elif not since:
                since = "20200101"
            elif not before:
                before = datetime.now().strftime("%Y%m%d")

        # 阶段1：获取邮件列表
        mail_list = ec.fetch_mail_list(since_date=since, before_date=before)
        if not mail_list:
            logger.warning("无新邮件")
            ec.disconnect()
            return

        # 保存邮件列表到Excel
        cache_dir = Path(cfg["paths"]["cache_dir"])
        cache_dir.mkdir(parents=True, exist_ok=True)
        mail_list_path = cache_dir / "邮件列表.xlsx"
        ec.export_mail_list(mail_list, mail_list_path)

        # 阶段2：断点续传下载附件（下载器内部会自动跳过已存在的文件夹）
        # 下载落点：cache_dir/_原始邮件（邮件原始缓存，与源数据分离）
        all_uids = [m['uid'] for m in mail_list]
        logger.info(f"开始下载附件，共 {len(all_uids)} 封，下载器会自动跳过已存在的文件夹")
        trust_files = ec.download_attachments_by_uids(all_uids, cache_dir, mail_list)

        ec.disconnect()

        # 阶段3：文件分类（按投资标的分类）→ 底层估值表目录（穿透用）
        classifier_output = Path(cfg["paths"]["underlying_data"])
        project_file = Path(cfg["paths"]["holding_std"])
        newly_copied = _run_classifier(project_file, cache_dir, classifier_output, since, before)

        # 阶段4：将本次新复制的文件构造为 ValuationFile 列表
        trust_files = []
        if newly_copied:
            from core.models import ValuationFile
            from utils.helpers import extract_project_info
            from datetime import date
            for f in newly_copied:
                code, name, vdate = extract_project_info(f.name)
                if vdate is None:
                    vdate = date.today()
                trust_files.append(ValuationFile(
                    file_path=str(f),
                    project_code=code,
                    project_name=name,
                    file_date=vdate,
                    level="trust"
                ))
            logger.info(f"本次共 {len(trust_files)} 个新文件待处理")
        underlying_files = []
    elif args.mode == "classify":
        # 仅分类：已有附件，只做分类
        # 源：cache_dir/_原始邮件；输出：底层估值表目录
        cache_dir = Path(cfg["paths"]["cache_dir"])
        cache_dir.mkdir(parents=True, exist_ok=True)
        classifier_output = Path(cfg["paths"]["underlying_data"])
        project_file = Path(cfg["paths"]["holding_std"])

        days = cfg.get("email", {}).get("search_days")
        if days:
            since = (datetime.now() - timedelta(days=int(days))).strftime("%Y%m%d")
            before = datetime.now().strftime("%Y%m%d")
        else:
            since = args.since or cfg.get("email", {}).get("search_since", "")
            before = args.before or cfg.get("email", {}).get("search_before", "")

        _run_classifier(project_file, cache_dir, classifier_output, since, before)
        logger.success("分类完成")
        return
    elif args.mode == "nav":
        # 净值分析：扫描净值表目录，输出净值分析结果.xlsx + 曲线图
        from core.nav_analyzer import NavAnalyzer as _NavAnalyzer
        from reporters.nav_reporter import NavReporter as _NavReporter
        nav_input = Path(cfg["paths"].get("nav_input", "data/input/净值表"))
        nav_out_dir = Path(cfg["paths"]["output"]) / "净值分析"
        if not nav_input.exists():
            logger.warning(f"净值表目录不存在，跳过净值分析: {nav_input}")
            return
        analyzer = _NavAnalyzer()
        metrics = analyzer.analyze_directory(str(nav_input), str(nav_out_dir))
        if not metrics:
            logger.warning(f"未从 {nav_input} 解析到任何净值数据")
            return
        out = _NavReporter().write_report(metrics, nav_out_dir)
        logger.success(f"净值分析完成: {out}（{len(metrics)} 条）")
        return
    elif args.mode in ("local", "holding"):
        # 持仓明细 + 估值统计 + 管理人回填（+ 可选归档）
        # local/holding 模式：扫描 raw_data 目录，跑完整解析管道（不含穿透报告）
        input_dir = Path(cfg["paths"]["raw_data"])
        collector = FileCollector(input_dir)
        trust_files = collector.collect()
        underlying_files = []

        # 底层文件采集（如果配置了 underlying_data 目录）
        underlying_dir = cfg["paths"].get("underlying_data")
        if underlying_dir:
            underlying_path = Path(underlying_dir)
            if underlying_path.exists():
                underlying_collector = FileCollector(underlying_path, pattern="*.xls*")
                u_files = underlying_collector.collect()
                for uf in u_files:
                    uf.level = "underlying"
                underlying_files.extend(u_files)
                logger.info(f"已采集 {len(u_files)} 个底层估值表")

        if not trust_files and not underlying_files:
            logger.warning("无任何估值文件可处理")
            return

        # 执行管道（传入信托层和底层文件）
        pipeline = Pipeline(trust_files, underlying_files, Path(cfg["paths"]["output"]))
        result = pipeline.run()

        # 生成报表
        reporter = ExcelReporter(Path(cfg["paths"]["output"]))
        if result["overviews"]:
            reporter.report_overviews(result["overviews"], args.date)
        if result["holdings"]:
            reporter.report_holdings(result["holdings"], args.date)
            # 产出持仓明细工作表（完整表 + 标准表），供下游 classify/管理人回填/穿透 消费
            from reporters.holding_reporter import HoldingReporter as _HoldingReporter
            from core.manager import ManagerFiller as _ManagerFiller
            hr = _HoldingReporter()
            full_path = Path(cfg["paths"]["holding_full"])
            std_path = Path(cfg["paths"]["holding_std"])
            hr.write_full(result["holdings"], full_path)
            hr.write_std(result["holdings"], std_path)
            # 管理人回填：读完整表 -> 填 产品类型/管理人名称 -> 写回（下游穿透/分类强依赖）
            mapping_file = Path(cfg["paths"].get("manager_mapping"))
            if mapping_file.exists():
                _ManagerFiller().fill_file(full_path, mapping_file)
                logger.info(f"管理人回填完成（映射: {mapping_file}）")
            else:
                logger.warning(f"管理人映射文档不存在，跳过回填: {mapping_file}")
            logger.info(f"持仓完整表: {full_path}")
            logger.info(f"持仓标准表: {std_path}")

        # 产出估值统计工作表（下游穿透强依赖），供 classify/穿透 消费
        from parsers.valuation_stats import ValuationStatsParser as _ValuationStatsParser
        from reporters.valuation_reporter import ValuationReporter as _ValuationReporter
        vs_path = Path(cfg["paths"]["valuation_stats"])
        vparser = _ValuationStatsParser()
        vstats, vempty = vparser.parse(Path(cfg["paths"]["raw_data"]))
        if vstats:
            _ValuationReporter().write_stats(vstats, vs_path, vempty)
            logger.info(f"估值统计表: {vs_path}")
        else:
            logger.warning("未生成估值统计表（无有效估值文件）")

        # 文件归档（可选）
        if cfg.get("paths", {}).get("archive_base"):
            fs = FileStore(Path(cfg["paths"]["archive_base"]))
            fs.organize_from_classification(
                result["holdings"],
                trust_files,
                Path(cfg["paths"]["archive_base"])
            )

        if result["errors"]:
            logger.error(f"处理完成，但存在 {len(result['errors'])} 个错误")
        else:
            logger.success("持仓明细/估值统计/管理人回填 处理完成")

    elif args.mode == "penetration":
        # 穿透报告：仅基于已有的 持仓标准表 + 估值统计表 + 底层估值表 生成
        # 不重新解析信托层估值表，适用于已跑过 holding 后单独补跑/重跑穿透
        from parsers.penetration import PenetrationParser as _PenetrationParser
        from reporters.penetration_reporter import PenetrationReporter as _PenetrationReporter
        holding_std_file = Path(cfg["paths"]["holding_std"])
        valuation_stats_file = Path(cfg["paths"]["valuation_stats"])
        pen_out_dir = Path(cfg["paths"]["output"]) / "穿透报告"
        if holding_std_file.exists() and valuation_stats_file.exists():
            # 信托目录搜索顺序：config 路径优先，旧默认目录兜底
            pen_search = []
            underlying = cfg["paths"].get("underlying_data")
            if underlying:
                pen_search.append(Path(underlying))  # data/input/底层估值表
            pen_search.append(Path(cfg["paths"].get("archive_base", "data/archive")))
            cache_dir = Path(cfg["paths"].get("cache_dir", "data/cache"))
            pen_search.append(cache_dir / "_原始邮件" / "文件分类")
            pen_search.append(cache_dir / "文件分类")
            raw = Path(cfg["paths"]["raw_data"])
            pen_search.append(raw / "_原始邮件" / "文件分类")
            pen_search.append(raw / "文件分类")
            try:
                hs = pd.read_excel(holding_std_file)
                codes = [c for c in hs['项目代码'].astype(str).str.upper().unique().tolist() if c]
            except Exception as e:
                codes = []
                logger.warning(f"读取标准表失败，跳过穿透: {e}")
            pparser = _PenetrationParser()
            prep = _PenetrationReporter()
            for code in codes:
                res = pparser.generate(code, args.date, holding_std_file, valuation_stats_file, pen_search)
                if res.success:
                    out = prep.write_report(res, pen_out_dir)
                    logger.info(f"穿透报告: {out}")
                else:
                    logger.warning(f"项目 {code} 未生成穿透报告（无信托目录或持仓）")
            logger.success("穿透报告生成完成")
        else:
            logger.warning("标准表或估值统计表缺失，跳过穿透报告（请先运行 holding 模式）")

    else:
        logger.error(f"未知模式: {args.mode}")

if __name__ == "__main__":
    main()