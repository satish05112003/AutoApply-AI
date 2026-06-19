import logging
from typing import Dict, Type, Optional
from app.crawlers.base_crawler import BaseCrawler

logger = logging.getLogger("autoapply_ai.crawlers.registry")

class CrawlerRegistry:
    def __init__(self):
        self._registry: Dict[str, Type[BaseCrawler]] = {}

    def register(self, source_name: str, crawler_cls: Type[BaseCrawler]):
        self._registry[source_name.lower()] = crawler_cls
        logger.info(f"Registered crawler for: '{source_name}'")

    def get_crawler(self, source_name: str) -> Optional[BaseCrawler]:
        cls = self._registry.get(source_name.lower())
        if cls:
            return cls()
        return None

    def list_sources(self) -> list:
        return list(self._registry.keys())

crawler_registry = CrawlerRegistry()
