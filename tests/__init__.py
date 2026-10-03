"""测试包只为共享辅助模块提供稳定导入路径"""

import pytest

pytest.register_assert_rewrite("tests.support")
