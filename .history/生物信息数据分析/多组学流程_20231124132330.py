import pandas as pd
import numpy as np
import scipy
import subprocess
import os

# 分析路径
itemPath = r'/Users/yangpei/YangPei/after_sale/test_1/rawdata'
os.chdir(itemPath)

cond = 'HFDVSCD'

# =============================================================================
#                                        数据整理
# =============================================================================


# ========================== 1. 合并共同通路 ==========================
# 设置路径
mRNA_kegg_path = '{0}/KEGG_Enrichment.xlsx'.format(cond)
meta_kegg_path = '{0}/kegg.xlsx'.format(cond)


# 读取文件
mRNA_kegg_data = pd.read_excel(mRNA_kegg_path)
meta_kegg_data = pd.read_excel(meta_kegg_path)


# 选择通路并合并
mRNA_kegg_pathway_name = mRNA_kegg_data['Pathway_Name']
meta_kegg_pathway_name = meta_kegg_data['Pathway']

common_pathway = set(mRNA_kegg_pathway_name) & set(meta_kegg_pathway_name)
common_pathway_df = pd.DataFrame({'Pathway':list(common_pathway)})

# 输出共同同路表同时以供绘制图片
mRNA_kegg_pathway_selected_col = mRNA_kegg_data.loc[:, ['Pathway_Name', 'S', 'B', 'P.value']]
mRNA_kegg_pathway_selected_col.columns = ['Pathway', 'S', 'B', 'Pvalue']
mRNA_common_kegg_pathway = pd.merge(common_pathway_df, mRNA_kegg_pathway_selected_col, on='Pathway')
mRNA_common_kegg_pathway['type'] = 'mRNA'


meta_kegg_pathway_selected_col = meta_kegg_data.loc[:, ['Pathway', 'NumCompound', 'Background','Pvalue']]
meta_kegg_pathway_selected_col.rename(columns={'NumCompound': 'S', 'Background': 'B'}, inplace=True)
meta_common_kegg_pathway = pd.merge(common_pathway_df, meta_kegg_pathway_selected_col, on='Pathway')
meta_common_kegg_pathway['type'] = 'meta'

common_pathway_result = pd.concat([mRNA_common_kegg_pathway, meta_common_kegg_pathway])

output_name = '{0}/common_pathway_result.txt'.format('Output')
common_pathway_result.to_csv(output_name, sep='\t', index=False)


# ========================== 2. 差异基因和差异代谢物相关性分析 ==========================
diff_mRNA_path = 'mRNA/{0}/{1}_Gene_differential_expression.xlsx'.format(cond1, cond1)
diff_meta_path = 'meta/{0}/{1}.significant.idms2.xlsx'.format(cond2, cond2)

diff_mRNA_exp = pd.read_excel(diff_mRNA_path, index_col=0)
diff_meta_exp = pd.read_excel(diff_meta_path, index_col=0)

# 可根据sample_info整理成表达矩阵
diff_mRNA_exp_matrix = diff_mRNA_exp.filter(regex='FPKM.')
diff_meta_exp_matrix = diff_meta_exp.iloc[:,0:6]

# 根据表达矩阵，计算代谢物和基因的相关性，逐行扫描
def mRNA_extract_function(row_index):
    each_mRNA_exp = diff_mRNA_exp_matrix.iloc[row_index, :]
    
    def meta_extract_function():
        mRNA_meta_corr = diff_meta_exp_matrix.apply(scipy.stats.pearsonr, axis=1, args=(each_mRNA_exp, ))
        return mRNA_meta_corr
    
    return meta_extract_function


diff_mRNA_nums = 3
diff_meta_mums = 4
empty_corr_dataframe = []
for i in range(0, diff_mRNA_nums):
    mRNA_meta_corr = mRNA_extract_function(i)
    for n in range(0,diff_meta_mums):
        mRNA_name = diff_mRNA_exp_matrix.index[i]
        meta_name = diff_meta_exp_matrix.index[n]

        mRNA_meta_corr_matrix = mRNA_meta_corr()

        mRNA_meta_corr_coef = mRNA_meta_corr_matrix[n][0]
        mRNA_meta_corr_pvalue = mRNA_meta_corr_matrix[n][1]

        mRNA_meta_corr_dataframe = pd.DataFrame({'mRNA': [mRNA_name], 'meta':[meta_name], 
                                                 'corr_coef': [mRNA_meta_corr_coef],
                                                 'corr_pvalue': mRNA_meta_corr_pvalue})
        
        empty_corr_dataframe.append(mRNA_meta_corr_dataframe)

mRNA_meta_corr_result = pd.concat(empty_corr_dataframe)

# 相关性结果的输出
output_name = '{0}/mRNA_meta_corr_result.txt'.format('Output')
mRNA_meta_corr_result.to_csv(output_name, sep='\t', index=False)

# o2pls结果输出
diff_mRNA_exp_matrix.to_csv('Output/mRNA_exp_matrix.txt', sep='\t', index=False)
diff_meta_exp_matrix.to_csv('Output/meta_exp_matrix.txt', sep='\t', index=False)


# =============================================================================
#                                        绘图
# =============================================================================

# ========================== 1. 通路标色 ==========================
# 调用sh_diff_exp1.sh中的KEGG_pathwayview.pl

# ========================== 2. 使用R绘制共同通路图 ==========================
# R文件路径
common_pathway_plot_cmd = 'Rscript common_pathway_scatterplot.R'
subprocess.run(common_pathway_plot_cmd, shell=True, capture_output=True, encoding='utf-8')

# ========================== 3. 相关系数热图 ==========================
# R文件路径
corrcoef_heatmap_cmd = 'Rscript corr_heatmap.R'
subprocess.run(corrcoef_heatmap_cmd, shell=True, capture_output=True, encoding='utf-8')

# ========================== 4. 九象限图 =============================
corrcoef_heatmap_cmd = 'Rscript nine_quadrant.R'
subprocess.run(corrcoef_heatmap_cmd, shell=True, capture_output=True, encoding='utf-8')


# ========================== 5. O2PLS分析 ============================
# R文件路径
o2pls_analysis_cmd = 'Rscript O2PLS_analysis.R'
subprocess.run(o2pls_analysis_cmd, shell=True, capture_output=True, encoding='utf-8')



