"""为请求内敏感词集合记录变更，避免复用已经失效的匹配器"""


class PrivacyTerms(set):
    """保留集合调用方式，任何内容变化都会推进代次"""

    def __init__(self, values=()):
        """初始规则作为首个代次，后续重复登记不使缓存失效"""
        super().__init__(values)
        self.generation = 0

    def add(self, value):
        """只有新增值才使依赖的缓存失效"""
        if value not in self:
            super().add(value)
            self.generation += 1

    def update(self, *values):
        """逐个登记，兼容生成器及多个集合"""
        for group in values:
            for value in group:
                self.add(value)

    def discard(self, value):
        """删除现有规则时同样推进代次"""
        if value in self:
            super().discard(value)
            self.generation += 1

    def remove(self, value):
        """保留集合删除缺失值时的错误"""
        super().remove(value)
        self.generation += 1

    def pop(self):
        """移出规则后撤销依赖旧集合的缓存"""
        value = super().pop()
        self.generation += 1
        return value

    def clear(self):
        """清空非空集合时撤销缓存"""
        if self:
            super().clear()
            self.generation += 1

    def difference_update(self, *values):
        """差集删除通过相同的代次入口"""
        removed = self.intersection(set().union(*values))
        for value in removed:
            self.discard(value)

    def intersection_update(self, *values):
        """交集删除通过相同的代次入口"""
        self.difference_update(self.difference(self.intersection(*values)))

    def symmetric_difference_update(self, values):
        """先固定输入，兼容集合自身作为参数"""
        values = set(values)
        removed, added = self.intersection(values), values.difference(self)
        self.difference_update(removed)
        self.update(added)

    def __ior__(self, values):
        """原位并集保留当前集合及代次"""
        self.update(values)
        return self

    def __iand__(self, values):
        """原位交集保留当前集合及代次"""
        self.intersection_update(values)
        return self

    def __isub__(self, values):
        """原位差集保留当前集合及代次"""
        self.difference_update(values)
        return self

    def __ixor__(self, values):
        """原位对称差集保留当前集合及代次"""
        self.symmetric_difference_update(values)
        return self
