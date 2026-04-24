import argparse
import datetime
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

import qc_params

REPORT_PATHS = {
    "standard": {
        "industrial_pl": "final_report/ACGT101_lncRNA_report_refRNA_multiple_samples_industrial_customer.pl",
        "customer_pl": "final_report/ACGT101_lncRNA_report_refRNA_multiple_samples_customer.pl",
        "report_html": "final_report/RNA-seq-report.html",
        "logo": "final_report/src/pics/logo1.png",
    },
    "cloud": {
        "industrial_pl": "final_report/ACGT101_lncRNA_report_refRNA_Lite_multiple_samples_industrial_customer.pl",
        "customer_pl": "final_report/ACGT101_lncRNA_report_refRNA_Lite_multiple_samples_customer.pl",
        "report_html": "final_report/RNA-seq-os-report.html",
        "logo": "final_report/src/pics/logo1.png",
    },
}


def _interval_fail_indices(series: pd.Series, spec: Any) -> List:
    if not isinstance(spec, Mapping):
        raise TypeError(f"阈值格式错误: {spec!r}")
    lo = spec.get("min")
    hi = spec.get("max")
    bad = pd.Series(False, index=series.index)
    if lo is not None:
        bad |= series < lo
    if hi is not None:
        bad |= series > hi
    return list(series.index[bad])


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="转录组质控检查（标准版 / 云 Lite 版）")
    p.add_argument("workdir", help="分析工作目录")
    p.add_argument(
        "--product",
        choices=("standard", "cloud"),
        default="standard",
        help="产品类型：standard 为完整分析，cloud 为 Lite 云分析（文件清单不同）",
    )
    p.add_argument(
        "--config",
        default=None,
        help="params.toml 路径（默认与脚本同目录下的 params.toml）",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    os.chdir(args.workdir)

    species_df = pd.read_csv("project_info/03_species.txt", sep="\t")
    group_stat_df = pd.read_csv("project_info/02_groups.txt").drop_duplicates()
    species = species_df.iloc[0, 0]
    group_num = group_stat_df.shape[0]
    profile_key = qc_params.resolve_profile_key(species, group_num)

    thresholds = qc_params.get_thresholds(args.config)
    file_need_check_list = qc_params.get_file_check_list(
        args.product, profile_key, args.config
    )
    diff_gene_n = int(thresholds["DiffGeneNum"])

    metric_specs = {k: v for k, v in thresholds.items() if k != "DiffGeneNum"}

    data = pd.read_csv(r"checkPoint/data_Stat.txt", sep="\t", index_col=0)
    diff_gene = pd.read_csv(
        r"Output/summary/3.DiffExpression/differentially_expressed_genes.txt", sep="\t"
    )

    data["Read1WithAdapter"] = data["Read1WithAdapter"].apply(lambda x: float(x.rstrip("%")))
    data["Read2WithAdapter"] = data["Read2WithAdapter"].apply(lambda x: float(x.rstrip("%")))
    data["PairsThatWereTooShort"] = data["PairsThatWereTooShort"].apply(
        lambda x: float(x.rstrip("%"))
    )
    data["RawData"] = data["RawData"].apply(lambda x: float(x.rstrip("G")))
    data["CleanData"] = data["CleanData"].apply(lambda x: float(x.rstrip("G")))

    Read1WithAdapterError = _interval_fail_indices(
        data["Read1WithAdapter"], metric_specs["Read1WithAdapter"]
    )
    Read2WithAdapterError = _interval_fail_indices(
        data["Read2WithAdapter"], metric_specs["Read2WithAdapter"]
    )
    PairsThatWereTooShortError = _interval_fail_indices(
        data["PairsThatWereTooShort"], metric_specs["PairsThatWereTooShort"]
    )
    RawDataError = _interval_fail_indices(data["RawData"], metric_specs["RawData"])
    CleanDataError = _interval_fail_indices(data["CleanData"], metric_specs["CleanData"])
    Q20Error = _interval_fail_indices(data["Q20"], metric_specs["Q20"])
    Q30Error = _interval_fail_indices(data["Q30"], metric_specs["Q30"])
    GCError = _interval_fail_indices(data["GC"], metric_specs["GC"])
    MappedreadsError = _interval_fail_indices(data["Mappedreads"], metric_specs["Mappedreads"])
    UniqueMappedreadsError = _interval_fail_indices(
        data["UniqueMappedreads"], metric_specs["UniqueMappedreads"]
    )
    MultiMappedreadsError = _interval_fail_indices(
        data["MultiMappedreads"], metric_specs["MultiMappedreads"]
    )
    exonError = _interval_fail_indices(data["exon"], metric_specs["exon"])
    intronError = _interval_fail_indices(data["intron"], metric_specs["intron"])
    intergenicError = _interval_fail_indices(data["intergenic"], metric_specs["intergenic"])

    CorrelationOfSample = data["CorrelationOfSample"].apply(
        lambda x: [float(t) for t in x.split(";")]
    )
    data["CorrelationOfSampleDelta"] = CorrelationOfSample.apply(
        lambda x: max(x) - min(x) if x else 0.0
    )
    CorrelationOfSampleError = _interval_fail_indices(
        data["CorrelationOfSampleDelta"], metric_specs["CorrelationOfSample"]
    )

    check_result_dict = dict(
        Read1接头比例=Read1WithAdapterError,
        Read2接头比例=Read2WithAdapterError,
        短片段比例=PairsThatWereTooShortError,
        RawData=RawDataError,
        CleanData=CleanDataError,
        Q20=Q20Error,
        Q30=Q30Error,
        GC=GCError,
        基因组比对率=MappedreadsError,
        唯一比对率=UniqueMappedreadsError,
        多重比对率=MultiMappedreadsError,
        外显子比例=exonError,
        内含子占比=intronError,
        基因间区=intergenicError,
        样本相关性=CorrelationOfSampleError,
    )

    dataframe_list = []
    for k, v in check_result_dict.items():
        if v:
            dataframe_list.append(pd.DataFrame({"质控检查": k, "检查结果": v}))
        else:
            dataframe_list.append(pd.DataFrame({"质控检查": k, "检查结果": ["正常"]}))

    all_files = [
        os.path.join(root, file)
        for root, dirs, files in os.walk("Output/summary")
        for file in files
    ]
    all_files_df = pd.DataFrame(
        {"文件检查": all_files, "文件大小": [os.path.getsize(x) / 1024 for x in all_files]}
    )

    file_check_df = []
    for tmp in file_need_check_list:
        file_exits_bool_index = all_files_df["文件检查"].str.contains(tmp)
        if file_exits_bool_index.any():
            file_df = all_files_df[file_exits_bool_index].copy()
            file_df.loc[:, "是否存在"] = "存在"
            file_check_df.append(file_df)
        else:
            file_df = pd.DataFrame({"文件检查": [tmp], "文件大小": 0.00, "是否存在": "不存在"})
            file_check_df.append(file_df)
    error_file_exist = pd.concat(file_check_df, axis=0)

    txt_check = error_file_exist.query('文件检查.str.contains(".txt")').query(
        '文件大小 == 0 | 是否存在 == "不存在"'
    )
    pdf_check = error_file_exist.query('文件检查.str.contains(".png")').query(
        '文件大小 <= 4 | 是否存在 == "不存在"'
    )
    file_check_result = pd.concat([txt_check, pdf_check], axis=0)
    file_check_result["检查结果"] = "异常"

    diff_gene_num_error = diff_gene.query(
        "上调基因 < @diff_gene_n & 下调基因 < @diff_gene_n"
    ).shape[0]
    all_group_num = diff_gene.shape[0]

    if all_group_num == 0:
        RegulationErrorDf = pd.DataFrame({"差异检查": ["差异基因数量"], "检查结果": "正常"})
    elif (diff_gene_num_error / all_group_num) > 0.5:
        RegulationErrorDf = pd.DataFrame({"差异检查": ["差异基因数量"], "检查结果": "异常"})
    else:
        RegulationErrorDf = pd.DataFrame({"差异检查": ["差异基因数量"], "检查结果": "正常"})

    rp = REPORT_PATHS[args.product]
    industrial_pl = rp["industrial_pl"]
    customer_pl = rp["customer_pl"]
    report_html = rp["report_html"]
    logo_path = rp["logo"]

    if os.path.exists(industrial_pl) and not os.path.exists(logo_path):
        contact_num = None
        species_report = None
        with open(report_html, "r", encoding="utf-8") as reader:
            text = reader.read()
            try:
                species_report = re.search(
                    r'<p class="paragraph3">拉丁名：(.*)</p><br/><br/>', text
                ).group(1)
                contact_num = re.search("样本分组信息表", text).group()
                report_info_collection = pd.DataFrame(
                    {
                        "报告检查": ["客户姓名", "客户单位", "项目编号", "销售姓名", "物种信息", "Logo"],
                        "检查结果": "正常",
                    }
                )
            except Exception:
                report_info_collection = pd.DataFrame(
                    {
                        "报告检查": ["客户姓名", "客户单位", "项目编号", "销售姓名", "物种信息", "Logo"],
                        "检查结果": "异常",
                    }
                )

        project_info = pd.read_csv(r"project_info/04_report.txt", sep="\t", header=None)
        species_info = project_info.iloc[17, 1]
        if contact_num and species_report == species_info:
            report_df2 = pd.DataFrame({"报告检查": ["报告是否完整"], "检查结果": ["正常"]})
            report_check_result = pd.concat([report_info_collection, report_df2], axis=0)
        else:
            report_check_result = pd.DataFrame(
                {
                    "报告检查": [
                        "客户姓名",
                        "客户单位",
                        "项目编号",
                        "销售姓名",
                        "物种信息",
                        "Logo",
                        "报告是否完整",
                    ],
                    "检查结果": "异常",
                }
            )

    elif os.path.exists(customer_pl) and os.path.exists(logo_path):
        contact_num = None
        species_report = None
        with open(report_html, "r", encoding="utf-8") as reader:
            text = reader.read()
            try:
                customer_name = re.search(
                    r"<th><b>客户姓名</b></th><th><b>(.*)</b></th></tr>", text
                ).group(1)
                customer_add = re.search(
                    r"<th><b>客户单位</b></th><th><b>(.*)</b></th></tr>", text
                ).group(1)
                customer_id = re.search(
                    r"<th><b>项目编号</b></th><th><b>(.*)</b></th></tr>", text
                ).group(1)
                sale_name = re.search(
                    r"<th><b>销售姓名</b></th><th><b>(.*)</b></th></tr>", text
                ).group(1)
                species_report = re.search(
                    r'<p class="paragraph3">拉丁名：(.*)</p><br/><br/>', text
                ).group(1)
                contact_num = re.search("地址", text).group()
                report_info_collection = pd.DataFrame(
                    {
                        "报告检查": ["客户姓名", "客户单位", "项目编号", "销售姓名", "物种信息"],
                        "检查结果": [customer_name, customer_add, customer_id, sale_name, species_report],
                    }
                )
            except Exception:
                report_info_collection = pd.DataFrame(
                    {
                        "报告检查": ["客户姓名", "客户单位", "项目编号", "销售姓名", "物种信息"],
                        "检查结果": "异常",
                    }
                )

        project_info = pd.read_csv(r"project_info/04_report.txt", sep="\t", header=None)
        project_info.iloc[3, 0] = "项目编号"
        project_info.columns = ["项目检查", "检查结果"]
        check_staus = report_info_collection["检查结果"].isin(project_info["检查结果"])
        species_info = project_info.iloc[17, 1]

        if check_staus.all() and contact_num and species_report == species_info:
            report_df2 = pd.DataFrame({"报告检查": ["报告是否完整", "Logo"], "检查结果": ["正常", "正常"]})
            report_check_result = pd.concat([report_info_collection, report_df2], axis=0)
        else:
            report_check_result = pd.DataFrame(
                {
                    "报告检查": [
                        "客户姓名",
                        "客户单位",
                        "项目编号",
                        "销售姓名",
                        "物种信息",
                        "报告是否完整",
                        "Logo",
                    ],
                    "检查结果": "异常",
                }
            )
    else:
        report_check_result = pd.DataFrame(
            {
                "报告检查": [
                    "客户姓名",
                    "客户单位",
                    "项目编号",
                    "销售姓名",
                    "物种信息",
                    "报告是否完整",
                    "Logo",
                ],
                "检查结果": "异常",
            }
        )

    lims_wk_nums = pd.read_csv("project_info/06_wkInfo.txt", header=0, sep="\t")
    analysis_wk_nums = pd.read_csv(r"project_info/01_samples.txt", header=0, sep="\t")
    item_type = lims_wk_nums.iloc[1, 1]
    wk_check = set(lims_wk_nums.iloc[:, 2]) == set(analysis_wk_nums.iloc[:, 1])

    if wk_check:
        wk_check_result = pd.DataFrame({"文库检查": ["数量核对"], "检查结果": "正常"})
    else:
        wk_check_result = pd.DataFrame({"文库检查": ["数量核对"], "检查结果": "异常"})

    with pd.ExcelWriter(r"checkPoint/check_Result.xlsx", engine="openpyxl") as writer:
        error_result = pd.concat(dataframe_list, axis=0)
        error_result_grouped = error_result.groupby(["质控检查", "检查结果"])
        error_result_grouped.count().to_excel(writer, sheet_name="质控报告", startrow=-1, startcol=0)

        start_row_1 = error_result.shape[0] + 3
        file_check_result.to_excel(
            writer, sheet_name="质控报告", startrow=start_row_1, startcol=0, index=False
        )

        start_row_2 = start_row_1 + file_check_result.shape[0] + 3
        RegulationErrorDf.to_excel(
            writer, sheet_name="质控报告", startrow=start_row_2, startcol=0, index=False
        )

        start_row_3 = start_row_2 + RegulationErrorDf.shape[0] + 3
        report_check_result.to_excel(
            writer, sheet_name="质控报告", startrow=start_row_3, startcol=0, index=False
        )

        start_row_4 = start_row_3 + report_check_result.shape[0] + 3
        wk_check_result.to_excel(
            writer, sheet_name="质控报告", startrow=start_row_4, startcol=0, index=False
        )

    check_record = open("checkPoint/checkPoint.txt", "w")
    if error_result["检查结果"].str.contains("正常").all():
        cond1 = 0
    else:
        cond1 = 1
    cond2 = file_check_result["检查结果"].str.contains("异常").any()
    cond3 = report_check_result["检查结果"].str.contains("异常").any()
    cond4 = RegulationErrorDf["检查结果"].str.contains("异常").any()

    time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workdir = args.workdir
    if sum([cond1, cond2, cond3, cond4]) >= 1 and wk_check:
        check_record.write(
            f"{workdir}\tNoPass\t{item_type}\t质控检查不通过\t样本数量正确\t{time}"
        )
    elif sum([cond1, cond2, cond3, cond4]) >= 1 and not wk_check:
        check_record.write(
            f"{workdir}\tNoPass\t{item_type}\t质控检查不通过\t样本数量不正确\t{time}"
        )
    elif sum([cond1, cond2, cond3, cond4]) == 0 and not wk_check:
        check_record.write(
            f"{workdir}\tNoPass\t{item_type}\t质控检查通过\t样本数量不正确\t{time}"
        )
    elif sum([cond1, cond2, cond3, cond4]) == 0 and wk_check:
        check_record.write(f"{workdir}\tPass\t{item_type}\t质控检查通过\t样本数量正确\t{time}")
    check_record.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
