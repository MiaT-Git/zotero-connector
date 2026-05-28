import re
from datetime import datetime
from typing import Optional

from znlm.models import ZoteroItem


class ItemProcessor:
    def process(
        self,
        raw_item: dict,
        collections_map: dict[str, str],
    ) -> ZoteroItem:
        data = raw_item.get("data", {})
        collection_keys: list[str] = data.get("collections", [])
        collection_names = self._resolve_collection_names(collection_keys, collections_map)
        if not collection_names:
            collection_names = ["Uncategorized"]

        return ZoteroItem(
            item_key=raw_item["key"],
            title=data.get("title") or "Untitled",
            authors=self._extract_authors(data.get("creators", [])),
            year=self._parse_year(data.get("date", "")),
            abstract=data.get("abstractNote") or None,
            doi=data.get("DOI") or None,
            url=data.get("url") or None,
            tags=self._extract_tags(data.get("tags", [])),
            collections=collection_keys,
            collection_names=collection_names,
            pdf_path=None,
            date_added=datetime.fromisoformat(
                data["dateAdded"].replace("Z", "+00:00")
            ),
            date_modified=datetime.fromisoformat(
                data["dateModified"].replace("Z", "+00:00")
            ),
        )

    def _extract_authors(self, creators: list[dict]) -> list[str]:
        authors = []
        for c in creators:
            if c.get("creatorType") not in ("author", "editor"):
                continue
            if "name" in c:
                authors.append(c["name"])
            elif "lastName" in c or "firstName" in c:
                first = c.get("firstName", "").strip()
                last = c.get("lastName", "").strip()
                if first and last:
                    authors.append(f"{first} {last}")
                elif last:
                    authors.append(last)
                elif first:
                    authors.append(first)
        return authors

    def _parse_year(self, date_str: str) -> Optional[int]:
        if not date_str:
            return None
        match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date_str)
        return int(match.group(1)) if match else None

    def _extract_tags(self, tags: list[dict]) -> list[str]:
        return [t["tag"] for t in tags if "tag" in t]

    def _resolve_collection_names(
        self,
        collection_keys: list[str],
        collections_map: dict[str, str],
    ) -> list[str]:
        return [collections_map[k] for k in collection_keys if k in collections_map]
