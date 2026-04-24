# 创建时间: 20240411 | 更新时间: 2025
# 面向对象编程
# 包含特征筛选算法: NoSelect、Lasso(L1逻辑回归CV)、RF、RFE(递归消除)
# 包含分类算法: SVM、LR、RF、XGBoost、MLP
# 针对极小样本量(20-40个)二分类任务进行防过拟合优化

import os
import sys
import argparse
import logging
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 非交互式后端，避免无显示器环境报错
import matplotlib.pyplot as plt
from sklearn.base import clone
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold, cross_val_score, learning_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectFromModel

# ========================== 日志配置 ==========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ========================== 创建命令行参数 ==========================
parser = argparse.ArgumentParser(
    prog='ML_OOP',
    description='Machine Learning Pipeline with Feature Selection (Optimized for small samples)',
    epilog='特征筛选: NoSelect, Lasso(L1逻辑回归CV), RF, RFE | 算法: SVM, LR, RF, XGB, MLP'
)
parser.add_argument('workDir',              help='工作路径（结果输出目录）')
parser.add_argument('input',               help='输入数据文件路径（TSV格式，最后一列为Label）')
parser.add_argument('select_algorithm',    help='特征筛选: NoSelect | Lasso(L1逻辑回归) | RF | RFE')

args = parser.parse_args()
workDir              = args.workDir
input_data_path      = args.input          
select_algorithm_opt = args.select_algorithm

# ========================== 数据加载 ==========================
logger.info(f'读取数据: {input_data_path}')
inputData = pd.read_excel(input_data_path, header=0)
X = inputData.iloc[:, :-1].values
y = inputData.iloc[:, -1].values
feature_names = inputData.columns[:-1].tolist()

# ========================== 工具函数 ==========================
def ensure_dir(path: str):
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)

def save_fig(path: str):
    """统一保存图片并清理画布"""
    plt.tight_layout()
    plt.savefig(path, bbox_inches='tight')
    plt.clf()
    plt.close()

# ========================== 特征筛选类 ==========================
class FeaturesSelector:
    """特征筛选器：L1 逻辑回归、随机森林重要性、RFE（兼容二分类与多分类）"""

    def __init__(self, X_train, X_test, y_train, y_test, feature_names, inputData):
        self.X_train       = X_train
        self.X_test        = X_test
        self.y_train       = y_train
        self.y_test        = y_test
        self.feature_names = feature_names
        self.inputData     = inputData

        # 在初始化时统一 fit scaler，避免各方法重复 fit 导致数据泄露
        self.scaler         = StandardScaler()
        self.X_train_scaled = self.scaler.fit_transform(X_train)
        self.X_test_scaled  = self.scaler.transform(X_test)

        # 记录分类数，供各方法使用
        self.n_classes = len(np.unique(y_train))
        logger.info(f'FeaturesSelector 初始化完成：{self.n_classes} 类分类任务')

    def _get_selected_df(self, support_mask):
        """根据布尔掩码提取原始数据的子集（含 Label 列）"""
        selected_cols = [col for col, selected in zip(self.feature_names, support_mask) if selected]
        selected_cols.append(self.inputData.columns[-1])
        return self.inputData[selected_cols]

    # -------------------- L1 逻辑回归 --------------------
    def lasso(self, out_dir: str, stability_repeats: int = 20):
        """
        L1 稀疏特征选择：LogisticRegressionCV + SelectFromModel。
        自动适配二分类与多分类
        """
        from sklearn.linear_model import LogisticRegressionCV
        import sklearn

        ensure_dir(out_dir)

        sk_version = tuple(int(x) for x in sklearn.__version__.split('.')[:2])
        use_multi_class_param = sk_version < (1, 2)

        if self.n_classes > 2:
            solver      = 'saga'
            multi_class = 'multinomial'
        else:
            solver      = 'saga'
            multi_class = 'ovr'

        logger.info(
            f'L1 LogisticRegressionCV：{self.n_classes} 类，'
            f'solver={solver}，multi_class={multi_class}，搜索最佳 C ...'
        )

        _, class_counts = np.unique(self.y_train, return_counts=True)
        min_class_count = int(class_counts.min())
        cv_splits = int(min(5, min_class_count))
        if cv_splits < 2:
            raise ValueError(
                f'样本量过小：最少类样本数={min_class_count}，无法进行 >=2 折的 Stratified CV。'
            )

        lr_cv_kwargs = dict(
            Cs=10,
            cv=cv_splits,
            penalty='l1',
            solver=solver,
            random_state=0,
            max_iter=10000,
            n_jobs=-1,
            scoring='balanced_accuracy',
        )
        if use_multi_class_param:
            lr_cv_kwargs['multi_class'] = multi_class

        lr_cv = LogisticRegressionCV(**lr_cv_kwargs)
        lr_cv.fit(self.X_train_scaled, self.y_train)

        c_array = np.ravel(lr_cv.C_)
        logger.info(f'各类最优 C：{c_array}')

        sfm     = SelectFromModel(lr_cv, max_features=500, prefit=True)
        support = sfm.get_support()
        selected_df = self._get_selected_df(support)
        logger.info(f'L1 逻辑回归选出特征数：{support.sum()}')

        try:
            stability_repeats = int(stability_repeats)
        except Exception:
            stability_repeats = 0

        if stability_repeats > 0:
            from sklearn.model_selection import StratifiedKFold

            counts = np.zeros(len(self.feature_names), dtype=int)
            for rep in range(stability_repeats):
                cv_obj = StratifiedKFold(n_splits=cv_splits, shuffle=True, random_state=rep)
                rep_kwargs = dict(lr_cv_kwargs)
                rep_kwargs['cv'] = cv_obj
                lr_cv_rep = LogisticRegressionCV(**rep_kwargs)
                lr_cv_rep.fit(self.X_train_scaled, self.y_train)
                sfm_rep = SelectFromModel(lr_cv_rep, max_features=500, prefit=True)
                counts += sfm_rep.get_support().astype(int)

            stability_df = pd.DataFrame(
                {
                    'feature': self.feature_names,
                    'selected_count': counts,
                    'selected_freq': counts / float(stability_repeats),
                }
            ).sort_values(['selected_freq', 'selected_count', 'feature'], ascending=[False, False, True])
            stability_df.to_csv(f'{out_dir}/l1_stability_selection.tsv', sep='\t', index=False)
            logger.info(
                'L1 Stability selection：重复次数=%d，结果已输出：%s',
                stability_repeats,
                f'{out_dir}/l1_stability_selection.tsv',
            )

        raw_scores = lr_cv.scores_
        if isinstance(raw_scores, dict):
            sc = np.asarray(next(iter(raw_scores.values())))
        else:
            sc = np.asarray(raw_scores)

        if sc.ndim == 3:
            fold_scores = sc.mean(axis=-1) 
        else:
            fold_scores = sc               

        mean_scores = fold_scores.mean(axis=0)             
        std_scores  = fold_scores.std(axis=0, ddof=1)      

        cs_grid  = np.asarray(lr_cv.Cs_).ravel()
        best_c_display = float(c_array.mean())
        
        self.lasso_lr_cv_ = lr_cv
        self.lasso_best_c_ = best_c_display
        self.lasso_cv_mean_scores_ = mean_scores
        self.lasso_cv_std_scores_ = std_scores

        best_idx_per_fold = np.argmax(fold_scores, axis=1)            
        best_c_per_fold   = cs_grid[best_idx_per_fold]                

        cv_table = pd.DataFrame(
            {
                'C': cs_grid,
                'mean_cv_accuracy': mean_scores,
                'std_cv_accuracy': std_scores,
            }
        )
        cv_table.to_csv(f'{out_dir}/lr_cv_scores_by_c.tsv', sep='\t', index=False)
        pd.DataFrame({'best_C_per_fold': best_c_per_fold}).to_csv(
            f'{out_dir}/lr_cv_best_c_per_fold.tsv', sep='\t', index=False
        )
        logger.info(
            'L1 LogisticRegressionCV 稳定性：cv=%d（少数类=%d），best_C_per_fold=%s',
            cv_splits,
            min_class_count,
            np.array2string(best_c_per_fold, precision=4, separator=', '),
        )

        plt.figure(figsize=(8, 5))
        plt.semilogx(cs_grid, mean_scores, 'o-', color='k', linewidth=2, label='Mean CV accuracy')
        plt.fill_between(
            cs_grid,
            mean_scores - std_scores,
            mean_scores + std_scores,
            color='gray',
            alpha=0.25,
            label='±1 std across folds',
        )
        plt.axvline(best_c_display, linestyle='--', color='r',
                    label=f'Mean best C={best_c_display:.4g}')
        plt.xlabel('C (inverse regularization strength)')
        plt.ylabel('Mean CV accuracy')
        plt.title('L1 Logistic Regression: CV accuracy vs C')
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.35)
        save_fig(f'{out_dir}/l1_logistic_cv.pdf')

        return selected_df

    # -------------------- Random Forest 重要性 --------------------
    def rf_importance(self, out_dir: str):
        """使用随机森林特征重要性进行筛选"""
        from sklearn.ensemble import RandomForestClassifier

        ensure_dir(out_dir)
        logger.info('RF 特征筛选：拟合随机森林 ...')
        clf = RandomForestClassifier(n_estimators=500, random_state=0, n_jobs=-1)
        clf.fit(self.X_train, self.y_train)

        sfm = SelectFromModel(clf, threshold='mean', prefit=True)
        sfm.fit(self.X_train, self.y_train)
        support = sfm.get_support()
        selected_df = self._get_selected_df(support)
        logger.info(f'RF 筛选阈值：{sfm.threshold_:.6f}')
        logger.info(f'RF 选出特征数：{support.sum()}')

        return selected_df

    # -------------------- RFE（递归特征消除） --------------------
    def rfe(
        self,
        out_dir: str,
        n_features_to_select=None,
        step=0.1,
        scoring: str = 'balanced_accuracy',
        class_weight: str | None = 'balanced',
        C: float = 1.0,
    ):
        from sklearn.feature_selection import RFECV, RFE
        from sklearn.linear_model import LogisticRegression
        import sklearn

        ensure_dir(out_dir)

        sk_version = tuple(int(x) for x in sklearn.__version__.split('.')[:2])
        use_multi_class_param = sk_version < (1, 2)

        base_kwargs = dict(
            penalty='l1',
            solver='saga',
            C=float(C),
            max_iter=10000,
            random_state=1,
            class_weight=class_weight,
        )
        if use_multi_class_param:
            base_kwargs['multi_class'] = 'multinomial' if self.n_classes > 2 else 'ovr'

        base_estimator = LogisticRegression(**base_kwargs)
        n_splits, min_class, _ = _choose_stratified_splits(self.y_train)
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=1)
        logger.info(
            'RFE/RFECV：scoring=%s，class_weight=%s，C=%.4g，cv=%d（少数类=%d）',
            scoring,
            class_weight,
            float(C),
            n_splits,
            min_class,
        )

        p = int(self.X_train_scaled.shape[1])
        if step == 1 and p >= 200:
            step = max(10, int(round(p * 0.05)))  
            logger.info('RFECV 自动加速：特征数=%d，已将 step 调整为 %d', p, step)

        if n_features_to_select is None:
            logger.info('RFECV：自动搜索最优特征数（L1 逻辑回归基学习器）...')
            selector = RFECV(
                estimator=base_estimator,
                step=step,
                cv=cv,
                scoring=scoring,
                min_features_to_select=1,
                n_jobs=-1,
            )
            selector.fit(self.X_train_scaled, self.y_train)
            n_selected = selector.n_features_
            logger.info(f'RFECV 最优特征数：{n_selected}')

            mean_scores = selector.cv_results_['mean_test_score']
            std_scores  = selector.cv_results_['std_test_score']
            if 'n_features' in selector.cv_results_:
                x_range = np.asarray(selector.cv_results_['n_features'], dtype=float)
            else:
                x_range = np.arange(1, len(mean_scores) + 1, dtype=float)

            plt.figure(figsize=(8, 5))
            plt.plot(x_range, mean_scores, marker='o', label=f'Mean CV {scoring}')
            plt.fill_between(x_range,
                             mean_scores - std_scores,
                             mean_scores + std_scores,
                             alpha=0.15)
            plt.axvline(n_selected, linestyle='--', color='r',
                        label=f'Optimal n={n_selected}')
            plt.xlabel('Number of features')
            plt.ylabel(f'CV {scoring}')
            plt.title(f'RFECV: Feature Count vs CV {scoring}')
            plt.legend()
            save_fig(f'{out_dir}/rfe_cv_score.pdf')

        else:
            logger.info(f'RFE：固定选取 {n_features_to_select} 个特征 ...')
            selector = RFE(
                estimator=base_estimator,
                n_features_to_select=n_features_to_select,
                step=step,
            )
            selector.fit(self.X_train_scaled, self.y_train)

        support     = selector.support_
        selected_df = self._get_selected_df(support)
        logger.info(f'RFE 选出特征数：{support.sum()}')

        ranking_df = pd.DataFrame({
            'feature' : self.feature_names,
            'ranking' : selector.ranking_,
            'selected': support,
        }).sort_values('ranking')
        ranking_df.to_csv(f'{out_dir}/rfe_feature_ranking.txt', sep='\t', index=False)
        logger.info(f'RFE 特征排名已保存至 {out_dir}/rfe_feature_ranking.txt')

        return selected_df


def _choose_stratified_splits(y, max_splits_large=10, max_splits_small=3, small_n_threshold=80):
    """
    分层交叉验证折数（针对极小样本优化）：
    将 max_splits_small 由5降至3，避免小样本下单折验证集样本过少导致评估崩溃。
    """
    y = np.asarray(y)
    n = len(y)
    _, counts = np.unique(y, return_counts=True)
    min_class = int(counts.min())
    cap = max_splits_small if n < small_n_threshold else max_splits_large
    k = min(cap, min_class, n)
    if k >= 2:
        k = max(2, k)
    else:
        k = 2
        logger.warning(
            '少数类训练样本仅 %d 条，无法满足分层 K 折；已设 n_splits=2，若仍失败请合并类别或增广数据。',
            min_class,
        )
    return k, min_class, cap


# ========================== 机器学习类 ==========================
class MLAlgorithm:
    """
    机器学习算法封装类（针对极小样本量降维防过拟合）。
    支持: SVM、LR、RF、XGBoost、MLP
    """

    def __init__(self, X_train, X_test, y_train, y_test):
        self.X_train = X_train
        self.X_test  = X_test
        self.y_train = y_train
        self.y_test  = y_test
        n_splits, min_class, cap = _choose_stratified_splits(y_train)
        self.cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=1)
        logger.info(
            'StratifiedKFold: n_splits=%d（训练集 n=%d，少数类最少 %d 个；折数上限=%d）',
            n_splits, len(y_train), min_class, cap,
        )

    # ---------- 统一网格搜索封装 ----------
    def _grid_search(self, pipe, param_grid):
        """执行 GridSearchCV 并返回 (best_model, gs对象)"""
        gs = GridSearchCV(
            estimator=pipe,
            param_grid=param_grid,
            cv=self.cv,
            scoring='balanced_accuracy',
            n_jobs=-1,      
            refit=True
        )
        gs.fit(self.X_train, self.y_train)
        return gs.best_estimator_, gs

    # ==================== 模型定义 ====================

    def lr(self):
        """逻辑回归（L2 正则，多分类 softmax）"""
        from sklearn.linear_model import LogisticRegression
        pipe = make_pipeline(
            StandardScaler(),
            LogisticRegression(random_state=1, max_iter=10000,
                               penalty='l2', multi_class='multinomial', solver='lbfgs',
                               class_weight='balanced') 
        )
        param_grid = [{'logisticregression__C': [0.01, 0.1, 0.5, 1.0, 5.0, 10.0]}]
        return self._grid_search(pipe, param_grid)

    def svm(self):
        """支持向量机（RBF 核，缩小搜索范围防过拟合）"""
        from sklearn.svm import SVC
        pipe = make_pipeline(
            StandardScaler(),
            SVC(random_state=1, probability=True, class_weight='balanced') 
        )
        # 【优化】去掉极值 0.0001 和 1000.0，缩小搜索范围
        param_range = [0.01, 0.1, 1.0, 10.0]
        param_grid  = [{'svc__C': param_range, 'svc__kernel': ['rbf'], 'svc__gamma': param_range}]
        return self._grid_search(pipe, param_grid)

    def rf(self):
        """随机森林（极小样本优化：限制深度、提高分裂阈值、减少树数量）"""
        from sklearn.ensemble import RandomForestClassifier
        pipe = make_pipeline(
            StandardScaler(),
            RandomForestClassifier(random_state=1, class_weight='balanced') 
        )
        # 【优化】降低模型复杂度
        param_grid = [{
            'randomforestclassifier__max_depth':        [2, 3, 4],         # 原[3,4,5,6,7,8]
            'randomforestclassifier__min_samples_split':[5, 10],          # 原[2, 5]
            'randomforestclassifier__min_samples_leaf': [3, 5],           # 原[1, 2]
            'randomforestclassifier__n_estimators':     [50, 100]         # 原[200,300,400,500]
        }]
        return self._grid_search(pipe, param_grid)

    def xgb(self):
        """XGBoost 分类（极小样本优化：极浅树、极少树、更强正则）"""
        from xgboost import XGBClassifier
        pipe = make_pipeline(
            StandardScaler(),
            XGBClassifier(random_state=1, eval_metric='mlogloss', verbosity=0, device="cuda", tree_method="hist")
        )
        # 【优化】大幅削减模型容量，增强正则化
        param_grid = [{
            'xgbclassifier__learning_rate':    [0.1, 0.3],               # 原[0.01, 0.05, 0.1]
            'xgbclassifier__max_depth':        [2, 3],                   # 原[5, 6, 7, 8]
            'xgbclassifier__min_child_weight': [3, 5],                   # 原[1]
            'xgbclassifier__n_estimators':     [10, 20, 50],             # 原[200, 300, 400]
            'xgbclassifier__reg_alpha':        [1, 5, 10]                # 原[5, 6, 7, 8]
        }]
        return self._grid_search(pipe, param_grid)

    def mlp(self):
        """
        多层感知机（极小样本优化：极小隐藏层、增大L2正则）。
        """
        from sklearn.neural_network import MLPClassifier
        pipe = make_pipeline(
            StandardScaler(),
            MLPClassifier(
                random_state=1,
                max_iter=1000,
                early_stopping=True,    
                validation_fraction=0.1,
                n_iter_no_change=20,
                solver='adam'
            )
        )
        # 【优化】隐藏层大幅缩小，限制网络容量
        param_grid = [{
            'mlpclassifier__hidden_layer_sizes': [
                (4,), 
                (8,), 
                (4, 2)
            ], 
            'mlpclassifier__activation':  ['relu'],                    
            'mlpclassifier__alpha':       [0.01, 0.1, 1.0],           # 原[1e-4, 1e-3, 1e-2]
            'mlpclassifier__learning_rate_init': [1e-3]                # 原[1e-3, 5e-4]
        }]
        return self._grid_search(pipe, param_grid)

    # ==================== 模型评估 ====================

    def report_best_params(self, gs, report_fh):
        report_fh.write(f"Best params: {gs.best_params_}\n")

    def report_test_accuracy(self, model, report_fh):
        from sklearn.metrics import balanced_accuracy_score
        y_pred = model.predict(self.X_test)
        acc = model.score(self.X_test, self.y_test)
        bal_acc = balanced_accuracy_score(self.y_test, y_pred)
        report_fh.write(f"Test accuracy: {acc:.4f}\n")
        report_fh.write(f"Test balanced_accuracy: {bal_acc:.4f}\n")

    def report_cv_score(self, model, report_fh):
        scores = cross_val_score(
            model, self.X_train, self.y_train,
            scoring='balanced_accuracy', cv=self.cv, n_jobs=-1,
        )
        report_fh.write(f"CV balanced_accuracy: {scores.mean():.4f} +/- {scores.std():.4f}\n")

    def report_metrics(self, model, report_fh):
        """精确率、召回率、F1、MCC（小样本最稳健指标）"""
        from sklearn.metrics import precision_score, recall_score, f1_score, matthews_corrcoef
        y_pred = model.predict(self.X_test)
        report_fh.write(f"Precision (macro): {precision_score(self.y_test, y_pred, average='macro'):.4f}\n")
        report_fh.write(f"Recall    (macro): {recall_score   (self.y_test, y_pred, average='macro'):.4f}\n")
        report_fh.write(f"F1        (macro): {f1_score       (self.y_test, y_pred, average='macro'):.4f}\n")
        # 【优化】新增MCC指标
        report_fh.write(f"MCC:                {matthews_corrcoef(self.y_test, y_pred):.4f}\n")

    def plot_confusion_matrix(self, model, out_dir: str):
        from sklearn.metrics import confusion_matrix
        y_pred      = model.predict(self.X_test)
        conf_matrix = confusion_matrix(self.y_test, y_pred)

        fig, ax = plt.subplots(figsize=(max(3, conf_matrix.shape[0]), max(3, conf_matrix.shape[0])))
        im = ax.matshow(conf_matrix, cmap=plt.cm.Blues, alpha=0.7)
        plt.colorbar(im, ax=ax)
        for i in range(conf_matrix.shape[0]):
            for j in range(conf_matrix.shape[1]):
                ax.text(j, i, conf_matrix[i, j], va='center', ha='center', fontsize=10)
        ax.xaxis.set_ticks_position('bottom')
        plt.xlabel('Predicted label')
        plt.ylabel('True label')
        plt.title('Confusion Matrix')
        save_fig(f'{out_dir}/confusion_matrix.pdf')

    def plot_learning_curve(self, model, out_dir: str):
        train_sizes, train_scores, test_scores = learning_curve(
            model, self.X_train, self.y_train,
            train_sizes=np.linspace(0.1, 1.0, 10),
            cv=self.cv, n_jobs=-1
        )
        tm, ts = train_scores.mean(1), train_scores.std(1)
        vm, vs = test_scores.mean(1),  test_scores.std(1)

        plt.figure(figsize=(7, 5))
        plt.plot(train_sizes, tm, 'o-', color='blue',  label='Training accuracy')
        plt.fill_between(train_sizes, tm - ts, tm + ts, alpha=0.15, color='blue')
        plt.plot(train_sizes, vm, 's--', color='green', label='Validation accuracy')
        plt.fill_between(train_sizes, vm - vs, vm + vs, alpha=0.15, color='green')
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.xlabel('Training examples')
        plt.ylabel('Accuracy')
        plt.title('Learning Curve')
        plt.legend(loc='lower right')
        save_fig(f'{out_dir}/learning_curve.pdf')

    def plot_cv_scores(self, model, out_dir: str):
        from sklearn.model_selection import cross_validate

        METRICS = {
            'Balanced Acc':  'balanced_accuracy',
            'Precision':     'precision_macro',
            'Recall':        'recall_macro',
            'F1':            'f1_macro',
        }

        cv_results = cross_validate(
            model, self.X_train, self.y_train,
            scoring=list(METRICS.values()),
            cv=self.cv, n_jobs=-1,
        )

        score_dict = {label: cv_results[f'test_{key}']
                      for label, key in METRICS.items()}
        n_folds     = len(next(iter(score_dict.values())))
        fold_labels = [f'Fold {i+1}' for i in range(n_folds)]
        df = pd.DataFrame(score_dict, index=fold_labels)
        df.index.name = 'Fold'
        df.to_csv(f'{out_dir}/cv_scores.tsv', sep='\t', float_format='%.4f')

        metric_labels = list(METRICS.keys())
        n_metrics = len(metric_labels)
        bar_colors = ['#4C72B0', '#DD8452', '#55A868', '#C44E52']

        x      = np.arange(n_folds)
        width  = 0.18
        offset = np.linspace(-(n_metrics - 1) / 2, (n_metrics - 1) / 2, n_metrics) * width

        fig, ax = plt.subplots(figsize=(max(8, n_folds * 1.4), 5))

        for i, (label, color) in enumerate(zip(metric_labels, bar_colors)):
            vals = score_dict[label]
            bars = ax.bar(x + offset[i], vals, width=width,
                          label=label, color=color, edgecolor='white',
                          linewidth=0.6, zorder=3)
            mean_v = vals.mean()
            ax.axhline(mean_v, color=color, linestyle='--', linewidth=1.2,
                       alpha=0.7, zorder=2)
            for bar, val in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.004,
                        f'{val:.2f}', ha='center', va='bottom',
                        fontsize=7, color=color)

        ax.set_xticks(x)
        ax.set_xticklabels(fold_labels)
        ax.set_xlabel('Cross-Validation Fold')
        ax.set_ylabel('Score')
        ax.set_title(f'Cross-Validation Scores per Fold ({n_folds}-Fold Stratified)\n'
                     f'Dashed lines = per-metric mean')
        ax.set_ylim(0, 1.12)
        ax.legend(loc='lower right', framealpha=0.85)
        ax.grid(axis='y', linestyle='--', alpha=0.35, zorder=1)
        ax.spines[['top', 'right']].set_visible(False)
        save_fig(f'{out_dir}/cv_scores.pdf')

    def plot_roc_curve(self, model, out_dir: str):
        from sklearn.metrics import roc_curve, auc

        classes = np.unique(self.y_train)
        plt.figure(figsize=(7, 5))

        if len(classes) == 2:
            y_prob = model.predict_proba(self.X_test)[:, 1]
            fpr, tpr, _ = roc_curve(self.y_test, y_prob, pos_label=classes[1])
            roc_auc = auc(fpr, tpr)
            plt.plot(fpr, tpr, color='#4C72B0', lw=2,
                     label=f'Test ROC (AUC = {roc_auc:.3f})')
            plt.fill_between(fpr, tpr, alpha=0.10, color='#4C72B0')
        else:
            from sklearn.preprocessing import label_binarize
            y_bin  = label_binarize(self.y_test, classes=classes)
            y_prob = model.predict_proba(self.X_test)
            for i, cls in enumerate(classes):
                fpr, tpr, _ = roc_curve(y_bin[:, i], y_prob[:, i])
                plt.plot(fpr, tpr, label=f'Class {cls} (AUC={auc(fpr,tpr):.2f})')

        plt.plot([0,1],[0,1],'--', color='gray', label='Random (AUC=0.5)')
        plt.xlim([-0.02, 1.02]); plt.ylim([-0.02, 1.02])
        plt.xlabel('False Positive Rate'); plt.ylabel('True Positive Rate')
        # 【优化】增加小样本提示
        plt.title('ROC Curve (Test Set - Small Sample, expect step-wise)'); plt.legend(loc='lower right')
        save_fig(f'{out_dir}/roc_curve.pdf')

    def plot_shap(self, model, X_bg, feature_cols, out_dir: str):
        import shap
        explainer   = shap.KernelExplainer(model.predict, X_bg)
        shap_values = explainer.shap_values(X_bg)

        fi = np.abs(shap_values).mean(axis=0)
        order = np.argsort(fi)[::-1]
        with open(f'{out_dir}/shap_feature_importance.txt', 'w') as fh:
            fh.write('Rank\tFeature\tMeanAbsSHAP\n')
            for rank, idx in enumerate(order, 1):
                fh.write(f'{rank}\t{feature_cols[idx]}\t{fi[idx]:.6f}\n')

        plt.figure()
        shap.summary_plot(shap_values, X_bg, feature_names=feature_cols, show=False)
        save_fig(f'{out_dir}/shap_summary.pdf')


# ========================== 统一运行函数 ==========================
def run_algorithm(name: str, model_fn, model_obj: MLAlgorithm,
                  X_bg, feature_cols, base_dir: str):
    out_dir = os.path.join(base_dir, name)
    ensure_dir(out_dir)
    logger.info(f'========== 开始训练: {name.upper()} ==========')

    best_model, gs = model_fn()

    with open(f'{out_dir}/report.txt', 'w') as report:
        report.write(f'===== {name.upper()} =====\n')
        model_obj.report_best_params(gs, report)
        model_obj.report_test_accuracy(best_model, report)
        model_obj.report_cv_score(best_model, report)
        model_obj.report_metrics(best_model, report)

    model_obj.plot_confusion_matrix(best_model, out_dir)
    model_obj.plot_cv_scores(best_model, out_dir)
    model_obj.plot_learning_curve(best_model, out_dir)
    model_obj.plot_roc_curve(best_model, out_dir)
    model_obj.plot_shap(best_model, X_bg, feature_cols, out_dir)

    logger.info(f'{name.upper()} 完成，结果保存至 {out_dir}')
    return best_model


# ========================== 主流程 ==========================
if __name__ == '__main__':
    os.chdir(workDir)
    ensure_dir(workDir)

    # ---------- 数据划分 ----------
    # 【优化】测试集比例由0.2提升至0.3，保证极小样本下测试集有足够数量(每组至少6个以上)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=1, stratify=y
    )

    # ---------- 特征筛选 ----------
    selector = FeaturesSelector(X_train, X_test, y_train, y_test, feature_names, inputData)

    if select_algorithm_opt == 'NoSelect':
        logger.info('跳过特征筛选，使用全部特征')
        selected_df = inputData

    elif select_algorithm_opt == 'Lasso':
        ensure_dir('lasso_select')
        selected_df = selector.lasso('lasso_select')
        best_c = float(getattr(selector, 'lasso_best_c_', float('nan')))
        selected_df.to_csv('lasso_select/selected_features.txt', sep='\t', index=False)
        logger.info(f'L1 逻辑回归最佳 C={best_c:.4g}')

    elif select_algorithm_opt == 'RF':
        ensure_dir('rf_select')
        selected_df = selector.rf_importance('rf_select')
        selected_df.to_csv('rf_select/selected_features.txt', sep='\t', index=False)

    elif select_algorithm_opt == 'RFE':
        ensure_dir('rfe_select')
        selected_df = selector.rfe('rfe_select', n_features_to_select=None, step=1)
        selected_df.to_csv('rfe_select/selected_features.txt', sep='\t', index=False)

    else:
        logger.error(f'未知特征筛选方法: {select_algorithm_opt}')
        sys.exit(1)

    # 用筛选后特征重新划分
    X_sel = selected_df.iloc[:, :-1].values
    y_sel = selected_df.iloc[:, -1].values
    sel_feature_names = selected_df.columns[:-1].tolist()

    # 【优化】测试集比例由0.2提升至0.3
    X_train, X_test, y_train, y_test = train_test_split(
        X_sel, y_sel, test_size=0.3, random_state=1, stratify=y_sel
    )

    # SHAP 背景数据
    rng = np.random.default_rng(1)
    bg_idx = rng.choice(len(X_train), size=min(100, len(X_train)), replace=False)
    X_bg   = X_train[bg_idx]

    # ---------- 模型训练与评估 ----------
    model_obj = MLAlgorithm(X_train, X_test, y_train, y_test)

    algorithm_items = [
        ('svm', model_obj.svm),
        ('lr', model_obj.lr),
        ('rf', model_obj.rf),
    ]
    try:
        import xgboost  
    except Exception as exc:
        logger.warning(
            '跳过 XGBoost（库无法加载；macOS 可尝试: conda install -c conda-forge libomp）: %s',
            exc,
        )
    else:
        algorithm_items.append(('xgb', model_obj.xgb))
    algorithm_items.append(('mlp', model_obj.mlp))

    for alg_name, alg_fn in algorithm_items:
        run_algorithm(
            name=alg_name,
            model_fn=alg_fn,
            model_obj=model_obj,
            X_bg=X_bg,
            feature_cols=sel_feature_names,
            base_dir=workDir
        )

    logger.info('全部算法运行完毕。')
