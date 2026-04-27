#========= git操作===========
# 初始化
cd path/to/your/r_folder  # 替换成你电脑上 R 文件夹的真实路径
git init

# 关联python远程仓库
# git remote add origin https://ghp_BbfeqI0bhiU0ODGvD0EpYXlcYiGajH1p6kU7@github.com/yangpei12/python_scripts.git
git remote set-url origin https://github.com/yangpei12/python_scripts.git

# 关联R远程仓库
git remote add origin https://ghp_BbfeqI0bhiU0ODGvD0EpYXlcYiGajH1p6kU7@github.com/yangpei12/R_scripts.git
# 要推送哪个文件夹进入到那个文件夹下
git add .

git commit -m "update: 推送最新的 Python 代码"
# 如果远程已经有代码，先拉取合并一下
git pull origin master --rebase
# 推送
git push -u origin master
# 拉取
git pull origin master --rebase
