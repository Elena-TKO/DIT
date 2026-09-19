"""Заглушка pydantic.BaseModel: значения по умолчанию и model_dump — для проверки связки роутов."""
import copy


class _FieldInfo:
    def __init__(self, default=None, default_factory=None):
        self.default, self.default_factory = default, default_factory


def Field(default=None, default_factory=None, **_):
    return _FieldInfo(default, default_factory)


class BaseModel:
    def __init__(self, **data):
        names = []
        for klass in reversed(type(self).__mro__):
            names += [n for n in getattr(klass, "__annotations__", {}) if n not in names]
        unknown = set(data) - set(names)
        if unknown:
            raise TypeError(f"{type(self).__name__}: лишние поля {unknown}")
        for n in names:
            if n in data:
                value = data[n]
            else:
                default = getattr(type(self), n, ...)
                if default is ...:
                    raise TypeError(f"{type(self).__name__}: не передано обязательное поле {n}")
                if isinstance(default, _FieldInfo):
                    value = default.default_factory() if default.default_factory else default.default
                else:
                    value = copy.copy(default)
            setattr(self, n, value)
        self._fields = names

    def model_dump(self):
        return {n: (getattr(self, n).model_dump() if isinstance(getattr(self, n), BaseModel) else getattr(self, n))
                for n in self._fields}
