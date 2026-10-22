"""pytest 全局配置：确保项目根目录在 sys.path 上。

否则 `import api.xxx` 会失败——pytest 默认只把测试文件所在目录加入路径。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
