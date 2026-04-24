import os
import re
import sys
import argparse
import subprocess
import pandas as pd

"""
命令行参数1: 工作路径
"""
# ========================== 创建命令行参数 =========================
# 初始化argparse对象
parser = argparse.ArgumentParser(
                    prog='DataCheck',
                    description='This Program Is Checking Data Quality',
                    epilog='Text at the bottom of help')
# 创建实例对象
parser.add_argument('workDir', help='please provide a work path')  # 工作路径
parser.add_argument('--itemType', help='please provide this project type')  # 项目类型--可选
parser.add_argument('--outDir', default=os.getcwd(), help='please provide a path for output')  # 结果文件输出路径--可选

# 解析参数
args = parser.parse_args()

# 导出参数
itemPath = args.workDir

# 判断项目类型
itemType_pattern = re.compile('.+/(.+)_lims/.+')
itemType = itemType_pattern.match(itemPath).group(1)

# 输出文件路径
pattern = r'(LC-P|USA-)[0-9]+(-[0-9]){0,1}(_LC-P[0-9]+){0,1}_[0-9]+'
itemNumbers = re.search(pattern, itemPath).group()
output_name = '{0}/checkPoint/data_Stat.txt'.format(args.outDir)
xlsx_name = '{0}/checkPoint/data_Stat.xlsx'.format(args.outDir)

"""
     第二部分：构建对象
"""

class RefRNA_Check:
    def __init__(self, itemPath):
        self.itemPath = itemPath
        self.sample_info =  pd.read_csv(r'{0}/sample_info.txt'.format(self.itemPath),sep='\t').drop_duplicates()
        self.sample_info.rename(columns = {'#SampleID':'Sample','COND1':'COND1'}, inplace=True)

    def path_exists(self):
        sample = self.sample_info.iloc[0, 0]
        self.sample_path = os.path.exists(r'{0}/sample_info.txt'.format(self.itemPath))
        self.project_info_path = os.path.exists(r'{0}/project_info/04_report.txt'.format(itemPath))
        self.clean_data_path = os.path.exists('{0}/{1}/{2}/{2}_delete_adapter.summary'.format(self.itemPath,'CleanData', sample))
        self.sampleCor_path = os.path.exists('{0}/Output/merged_result/correlation_cluster.txt'.format(self.itemPath))
        self.dataStat_path = os.path.exists('{0}/Output/stat_out.txt'.format(self.itemPath))
        self.mappedStat_path = os.path.exists('{0}/Output/mapped_stat_out.txt'.format(self.itemPath))
        self.mappedRegion_path = '{0}/Output/mapped_region_stat.txt'.format(self.itemPath)
        self.strandStat_path = os.path.exists('{0}/Output/{1}/RSeQC_result/{1}_Strand_specific.log'.format(self.itemPath, sample))
        self.marcb_path = os.path.exists('{0}/CleanData/{1}/{1}_bowtie_abundance_1.log'.format(self.itemPath, sample))

    def read_library(self):
        samples = pd.read_csv(r'{0}/project_info/01_samples.txt'.format(self.itemPath),sep='\t').drop_duplicates()
        projectInfo = samples.iloc[:, [1, 2]]
        projectInfo.columns = ['文库名称', 'Sample']
        self.libInfo = pd.merge(self.sample_info, projectInfo, on='Sample')
        return self.libInfo
                
    def read_short_read(self, sample):
        dics = {}
        patternOne = re.compile(r'  Read 1 with adapter:\s+.+\s+(.+%)')
        patternTwo = re.compile(r'  Read 2 with adapter:\s+.+\s+(.+%)')
        patternThree = re.compile(r'Pairs that were too short:\s+.+\s+(.+%)')
        cleanDataPath = r'{0}/{1}/{2}/{3}_delete_adapter.summary'.format(self.itemPath,'CleanData', sample, sample)
        with open(cleanDataPath, 'r') as input_buffez:
            dics['Sample'] = sample
            for line in input_buffez.readlines():
            
                matchedOne = patternOne.search(line.strip('\n'))
                if matchedOne:
                    adapterOneRatio = matchedOne.group(1)
                    dics['Read1WithAdapter'] = [adapterOneRatio.strip('(')]

                matchedTwo = patternTwo.search(line.strip('\n'))
                if matchedTwo:
                    adapterTwoRatio = matchedTwo.group(1)
                    dics['Read2WithAdapter'] = [adapterTwoRatio.strip('(')]

                matchedThree = patternThree.search(line.strip('\n'))
                if matchedThree:
                    shortSeqRatio = matchedThree.group(1)
                    dics['PairsThatWereTooShort'] = [shortSeqRatio.strip('(')]
        self.df_merge = pd.DataFrame(dics)
        return self.df_merge
    
    def sampleCor(self, group_name):
        corData = pd.read_csv(r'{0}/Output/merged_result/correlation_cluster.txt'.format(self.itemPath), sep='\t', index_col=0)
        group_name_bool = self.sample_info.iloc[:,1] == group_name # 筛选组名所在的行，返回布尔值
        sample_index = self.sample_info.iloc[:, 0][group_name_bool] # 根据组名返回的布尔值，筛选与组名对应的样本名
        rowData = corData.loc[list(sample_index.values), list(sample_index.values)]

        # 按照样本筛选每个样本与其他样本的相关性
        sampleData = rowData.columns.map(lambda x: ';'.join(rowData.loc[:, x].values.astype(str)))
        self.sampleCorInfoResult = pd.DataFrame(sampleData, index=rowData.columns, columns=['CorrelationOfSample'])
        return self.sampleCorInfoResult 

    def stat_out(self):
        statData = pd.read_csv(r'{0}/Output/stat_out.txt'.format(self.itemPath), sep='\t', header=0)
        self.newstatData = statData.iloc[1:, [0, 2, 4, 5, 6, 7, 8]]
        self.newstatData.columns = ['Sample', 'RawData', 'CleanData', 'ValidRatio', 'Q20', 'Q30', 'GC']
        return self.newstatData
    
    def mapped_stat(self):
        statData = pd.read_csv('{0}/Output/mapped_stat_out.txt'.format(self.itemPath), sep='\t', header=0)
        selectData = statData.loc[:, ['Sample', 'Mapped reads', 'Unique Mapped reads', 'Multi Mapped reads']]
        selectData['Mappedreads'] = selectData['Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
        selectData['UniqueMappedreads'] = selectData['Unique Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
        selectData['MultiMappedreads'] = selectData['Multi Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
        self.mapped_stat_result = selectData.loc[:, ['Sample', 'Mappedreads', 'UniqueMappedreads', 'MultiMappedreads']]
        return self.mapped_stat_result

    def mapped_region(self):
        regionData = pd.read_csv('{0}/Output/mapped_region_stat.txt'.format(self.itemPath), sep='\t', header=0, index_col=0)
        self.regionDataTranspose = regionData.transpose()
        self.regionDataTranspose['Sample'] = self.regionDataTranspose.index
        return self.regionDataTranspose


    def strand_info(self):
        try:
            cmd1 = "cut -f1 sample_info.txt | grep -v '#'"
            stdout = subprocess.Popen(cmd1, shell=True, stdout=subprocess.PIPE, encoding='utf-8')
            strand_data = []
            for sample in stdout.stdout.readlines():
                sample = sample.strip('\n')
                cmd2 = "grep '1+-,1-+,2++,2--' Output/{0}/RSeQC_result/{0}_Strand_specific.log".format(sample)
                strand_cmd_out = subprocess.Popen(cmd2, shell=True, stdout=subprocess.PIPE, encoding='utf-8')
                strand_specific_info = strand_cmd_out.stdout.readlines()
                strand_specific_ratio = strand_specific_info[0][-7:-1]
                result = [sample, strand_specific_ratio]
                strand_data.append(result)
            self.strand_out = pd.DataFrame(strand_data,columns=['Sample', 'StrandInfo'])
            return self.strand_out
        except IndexError:
            self.strand_out = pd.DataFrame({'Sample': self.sample_info.iloc[:,0],'链特异性': None})
            return self.strand_out

    def marcb_info(self):
        try:
            pattern = '.+/(.+)/.+:([0-9]+.[0-9]+%) .+'
            cmd = 'grep overall {0}/CleanData/*/*_bowtie_abundance_1.log'.format(self.itemPath)
            marcb_cmd_out = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, encoding='utf-8')
            df_list = []
            for line in marcb_cmd_out.stdout.readlines():
                result = re.findall(pattern, line)
                df = pd.DataFrame({'Sample':result[0][0], 'marcbRatio': [result[0][1]]})
                df_list.append(df)
            self.marcb_out = pd.concat(df_list, axis=0)
            return self.marcb_out
        except ValueError:
            self.marcb_out = pd.DataFrame({'Sample': self.sample_info.iloc[:,0],'marcbRatio': None})
            return self.marcb_out
    
    def item_info(self):
        reportData = pd.read_csv('{0}/project_info/04_report.txt'.format(self.itemPath), sep='\t', header=None)
        customer_name = reportData.iloc[0, 1]
        itemNum = reportData.iloc[3, 1]
        self.itemInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], '姓名': customer_name, '项目编号': itemNum, '项目路径': itemPath})
        return self.itemInfo, itemNum
        
        
    def output(self):
        """输出文库信息"""
        empty_libInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], '文库名称': None})
        if self.project_info_path:
            libStat = self.read_library()
            if not libStat.empty:
                libInfo = libStat.iloc[:,[0,2]]
            else:
                libInfo = empty_libInfo
        else:
            libInfo = empty_libInfo

        """短片段比例"""
        empty_cleanDataStatInfo = pd.DataFrame({'Sample':  self.sample_info.iloc[:,0], 'Read1WithAdapter': None,
                                     'Read2WithAdapter': None, 'PairsThatWereTooShort': None})
        if self.clean_data_path:
            samples = self.sample_info.iloc[:,0]
            cleanDataInfoResult = samples.map(self.read_short_read)
            cleanDataStat = pd.concat(cleanDataInfoResult.values)
            if not cleanDataStat.empty:
                cleanDataStatInfo = cleanDataStat
            else:
                cleanDataStatInfo = empty_cleanDataStatInfo
        else:
            cleanDataStatInfo = empty_cleanDataStatInfo
        
        """样本相关性"""
        empty_CorrelationInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], 'CorrelationOfSample': None})
        if self.sampleCor_path:
            groups = self.sample_info.iloc[:,1].unique()
            sampleCorResult = pd.Series(groups).map(self.sampleCor)
            CorrelationData = pd.concat(sampleCorResult.values)
            CorrelationData['Sample'] = CorrelationData.index
            if not CorrelationData.empty:
                CorrelationInfo = CorrelationData
            else:
                CorrelationInfo = empty_CorrelationInfo
        else:
            CorrelationInfo = empty_CorrelationInfo

        """样本数据量统计"""
        empty_dataStatInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], 'RawData': None, 'CleanData': None,
                                        'Q20': None, 'Q30': None, 'GC': None})
        if self.dataStat_path:
            dataStat = self.stat_out()
            if not dataStat.empty:
                dataStatInfo = dataStat
            else:
                dataStatInfo = empty_dataStatInfo
        else:
            dataStatInfo = empty_dataStatInfo

        """基因组比对统计"""
        empty_mappedStatInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], 'Mappedreads': None, 
                                          'UniqueMappedreads': None, 'MultiMappedreads': None})
        if self.mappedStat_path:
            mappedStat = self.mapped_stat()
            if not mappedStat.empty:
                mappedStatInfo = mappedStat
            else:
                mappedStatInfo = empty_mappedStatInfo
        else:
            mappedStatInfo = empty_mappedStatInfo
        
        """基因区间比对区域统计"""
        empty_mappedRegionInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], 'exon': None, 'intron': None, 'intergenic': None})
        if self.mappedRegion_path:
            mappedRegionStat = self.mapped_region()
            if not mappedRegionStat.empty:
                mappedRegionInfo = mappedRegionStat
            else:
                mappedRegionInfo = empty_mappedRegionInfo
        else:
            mappedRegionInfo = empty_mappedRegionInfo


        """链特异性"""
        empty_strandStatInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0],'链特异性': None})
        if self.strandStat_path:
            strandStat = self.strand_info()
            if not strandStat.empty:
                strandStatInfo = strandStat
            else:
                strandStatInfo = empty_strandStatInfo
        else:
            strandStatInfo = empty_strandStatInfo

        """核糖体占比"""
        empty_marcbStatInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0],'marcbRatio': None})
        if self.marcb_path:
            marcbStat = self.marcb_info()
            if not marcbStat.empty:
                marcbStatInfo = marcbStat
            else:
                marcbStatInfo = empty_marcbStatInfo
        else:
            marcbStatInfo = empty_marcbStatInfo

        """项目信息"""
        empty_itemStatInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], '项目编号': None, '项目路径': None})
        
        if self.project_info_path:
            itemStat = self.item_info()
            if not itemStat[0].empty:
                itemStatInfo = itemStat[0]
            else:
                itemStatInfo = empty_itemStatInfo
        else:
            itemStatInfo = empty_itemStatInfo


        """文件输出"""
        allDataOut = pd.DataFrame({'Sample': self.sample_info.iloc[:,0]})

        for tmp in [libInfo, cleanDataStatInfo, CorrelationInfo, dataStatInfo, mappedStatInfo,
                    mappedRegionInfo, strandStatInfo, marcbStatInfo, itemStatInfo]:
            allDataOut = pd.merge(allDataOut, tmp, on='Sample')
        
        allDataOut.to_csv(output_name, sep='\t', index=False)
        allDataOut.to_excel(xlsx_name, index=False, engine='openpyxl')
        

"""
                    第二部分：结果输出

"""

# refRNA or lncRNA
if itemType == 'refRNA' or itemType == 'lncRNA':
    refRNA_check = RefRNA_Check(itemPath=itemPath)
    refRNA_check.path_exists()
    refRNA_check.output()
    

# lncRNA_CircRNA
elif itemType == 'lncRNA_circRNA':
    class LncRNA_CircRNA_Check(RefRNA_Check):
        def __init__(self, itemPath):
            RefRNA_Check.__init__(self, itemPath + '/lncRNA')
        
        def read_library(self):
            samples = pd.read_csv(r'{0}/project_info/01_samples.txt'.format(itemPath), sep='\t').drop_duplicates()
            projectInfo = samples.iloc[:, [1, 2]]
            projectInfo.columns = ['文库名称', 'Sample']
            self.libInfo = pd.merge(self.sample_info, projectInfo, on='Sample')
            return self.libInfo

            
        def item_info(self):
            reportData = pd.read_csv('{0}/project_info/04_report.txt'.format(itemPath), sep='\t', header=None)
            customer_name = reportData.iloc[0, 1]
            itemNum = reportData.iloc[3, 1]
            self.itemInfo = pd.DataFrame({'Sample': self.sample_info.iloc[:,0], '姓名': customer_name, '项目编号': itemNum, '项目路径': itemPath})
            return self.itemInfo, itemNum
    
    lncRNA_circRNA_Check = LncRNA_CircRNA_Check(itemPath=itemPath)
    lncRNA_circRNA_Check.path_exists()
    lncRNA_circRNA_Check.output()
    
    
# circRNA
elif itemType == 'circRNA':
    class CircRNA_Check(RefRNA_Check):
        def __init__(self, itemPath):
            self.itemPath = itemPath
            self.sample_info =  pd.read_csv(r'{0}/sample_info.txt'.format(self.itemPath),sep='\t').drop_duplicates()        
            self.sample_info.rename(columns = {'Samples':'Sample','COND1':'COND1'}, inplace=True)
        
        def path_exists(self):
            sample = self.sample_info.iloc[0, 0]
            self.sample_path = os.path.exists(r'{0}/sample_info.txt'.format(self.itemPath))
            self.project_info_path = os.path.exists(r'{0}/project_info/04_report.txt'.format(self.itemPath))
            self.clean_data_path = os.path.exists('{0}/{1}/{2}/{2}_delete_adapter.summary'.format(self.itemPath,'CleanData', sample))
            self.sampleCor_path = os.path.exists('{0}/Output/merged_result/correlation_cluster.txt'.format(self.itemPath))
            self.dataStat_path = os.path.exists('{0}/Output/Data_stat_out/stat_out.txt'.format(self.itemPath))
            self.mappedStat_path = os.path.exists('{0}/Output/Mapping_stat_out/mapped_stat_out.txt'.format(self.itemPath))
            self.mappedRegion_path = '{0}/Output/Mapping_stat_out/mapped_region_stat.txt'.format(self.itemPath)
            self.strandStat_path = os.path.exists('{0}/Output/{1}/RSeQC_result/{1}_Strand_specific.log'.format(self.itemPath, sample))
            self.marcb_path = os.path.exists('{0}/CleanData/{1}/{1}_bowtie_abundance_1.log'.format(self.itemPath, sample))
        
        def stat_out(self):
            statData = pd.read_csv('{0}/Output/Data_stat_out/stat_out.txt'.format(self.itemPath), sep='\t', header=0)
            self.newstatData = statData.iloc[1:, [0, 2, 4, 5, 6, 7, 8]]
            self.newstatData.columns = ['Sample', 'RawData', 'CleanData', 'ValidRatio', 'Q20', 'Q30', 'GC']
            return self.newstatData
         
        def mapped_stat(self):
            statData = pd.read_csv('{0}/Output/Mapping_stat_out/mapped_stat_out.txt'.format(self.itemPath), index_col=0, sep='\t', header=0)
            statData = statData.transpose()
            statData['Sample'] = statData.index
            selectData = statData.loc[:, ['Sample', 'Mapped reads', 'Unique Mapped reads', 'Multi Mapped reads']]
            selectData['Mappedreads'] = selectData['Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
            selectData['UniqueMappedreads'] = selectData['Unique Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
            selectData['MultiMappedreads'] = selectData['Multi Mapped reads'].str.extract(r'([0-9]+.[0-9]+)%')
            self.mapped_stat_result = selectData.loc[:, ['Sample', 'Mappedreads', 'UniqueMappedreads', 'MultiMappedreads']]
            return self.mapped_stat_result
        
        def mapped_region(self):
            regionData = pd.read_csv('{0}/Output/Mapping_stat_out/mapped_region_stat.txt'.format(itemPath), sep='\t', header=0, index_col=0)
            self.regionDataTranspose = regionData.transpose()
            self.regionDataTranspose['Sample'] = self.regionDataTranspose.index
            return self.regionDataTranspose
            
    circRNA_Check = CircRNA_Check(itemPath=itemPath)
    circRNA_Check.path_exists()
    circRNA_Check.output()
