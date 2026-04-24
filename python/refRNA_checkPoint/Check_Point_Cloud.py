"""
兼容旧调用方式：等价于

    python Check_Point.py <工作目录> --product cloud
"""
import sys

from Check_Point import main


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python Check_Point_Cloud.py <工作目录>", file=sys.stderr)
        sys.exit(2)
    workdir = sys.argv[1]
    extra = sys.argv[2:]
    raise SystemExit(main([workdir, "--product", "cloud", *extra]))
