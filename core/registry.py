from parsers.base import BaseParser
from typing import Dict

class ParserRegistry:
    def __init__(self):
        self._parsers: Dict[str, BaseParser] = {}

    def register(self, name: str, parser: BaseParser):
        self._parsers[name] = parser

    def get(self, name: str) -> BaseParser:
        if name not in self._parsers:
            raise KeyError(f"Parser '{name}' not registered")
        return self._parsers[name]

# 全局单例
registry = ParserRegistry()