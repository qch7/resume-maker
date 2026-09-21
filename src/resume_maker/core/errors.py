"""定义业务异常和记录存在性校验"""


class Problem(Exception):
    """携带可展示消息及状态码的业务错误"""

    def __init__(self, message: str, status: int = 400):
        """保存错误消息和状态，供接口层统一转换为响应"""
        self.message, self.status = message, status
        super().__init__(message)


def need(value, message="记录不存在"):
    """返回已有记录，空值统一报告不存在以免后续出现空引用错误"""
    if value is None:
        raise Problem(message, 404)
    return value
