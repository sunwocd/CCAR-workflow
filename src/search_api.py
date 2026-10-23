#!/usr/bin/env python3
"""
CAAC 统一搜索（so-gov）客户端

背景：民航局原站内检索 `/was5/web/search` 已于 2026-10 停止响应（TCP/TLS 正常、首字节恒为 0）。
栏目页 `search.js` 的 `config.searchPageURL` 已改为政府网站统一检索平台：

    POST https://api.so-gov.cn/query/s       (form-urlencoded)
    siteCode=bm70000001 & tab=all & qt=<keyword> & page=N & pageSize=20
    可选：timeOption=1 & days=N   → 只返回最近 N 天发布的文档

已知契约（实测）：
  * `qt` 不能为空（否则 code=201 无搜索词）
  * `pageSize` 上限 20
  * `page` 上限由站点 tabs 配置写死 `maxPage=10` → 单次查询最多 200 条
  * 分类过滤参数（channelid/fl/column/L4/DOCNF…）全部无效，只能按返回的 URL 路径自行分类
  * 返回 `resultDocs[].data`：titleO / url / docDate / siteLabel.value / fileType
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlencode

import httpx
from loguru import logger

SEARCH_API = "https://api.so-gov.cn/query/s"
SITE_CODE = "bm70000001"
REFERER = "http://www.caac.gov.cn/so/s?tab=all&siteCode=bm70000001"

PAGE_SIZE = 20
MAX_PAGE = 10  # 站点 tabs 配置写死，超出会回到第 1 页

# 栏目代码 → 分类 ID（URL 里的 /XXGK/XXGK/<CODE>/）
COLUMN_CODE_TO_CATEGORY = {
    "MHGZ": "13",     # 民航规章
    "GFXWJ": "14",    # 规范性文件
    "BZGF": "15",     # 标准规范
    "TZTG": "9",      # 通知公告
    "ZCFB": "10",     # 政策发布
    "ZCFBJD": "10",
    "ZCJD": "11",     # 政策解读
    "TJSJ": "12",     # 统计数据
    "SBGX": "16",     # 对外关系（双边关系）
    "RSXX": "19",     # 人事信息
    "CZXX": "20",     # 财政信息
    "FZGH": "21",     # 发展规划
    "ZDXM": "22",     # 重大项目
    "XZQL": "23",     # 行政权力
    "ZFGW": "24",     # 政府公文
    "JGZN": "25",     # 机构职能
    "DWZC": "26",     # 对外政策
    "ZFDXAL": "27",   # 执法典型案例
    "FLFG": "47",     # 法律法规
}

UNCLASSIFIED = "0"

# 用于"拉全量"的宽关键词。检索 API 必须带 qt，没有"列出全部"的能力，
# 所以靠多关键词并集 + timeOption/days 窗口来覆盖近 N 天的更新。
DEFAULT_KEYWORDS = [
    "民航", "航空", "机场", "飞行", "运输", "空管", "航路", "空域",
    "通知", "规定", "办法", "标准", "规章", "通告", "公告", "意见",
    "安全", "运行", "管理", "技术", "维修", "执照", "训练", "审定",
]


@dataclass
class SearchHit:
    title: str
    url: str
    doc_date: str
    site_name: str
    file_type: str


def classify_url(url: str) -> str:
    """按 URL 路径把文档归到分类 ID；无法识别返回 UNCLASSIFIED。"""
    if not url:
        return UNCLASSIFIED
    marker = "/XXGK/XXGK/"
    if marker in url:
        tail = url.split(marker, 1)[1]
        code = tail.split("/", 1)[0].upper()
        return COLUMN_CODE_TO_CATEGORY.get(code, UNCLASSIFIED)
    return UNCLASSIFIED


def _valid_date(value: str) -> bool:
    """过滤 API 偶发返回的 1970-01-01 等占位日期。"""
    return bool(value) and value[:4].isdigit() and int(value[:4]) >= 2000


class SoGovSearch:
    """统一检索客户端：多关键词 + 时间窗口 → 去重后的 SearchHit 列表。"""

    def __init__(
        self,
        keywords: Optional[Iterable[str]] = None,
        timeout: float = 25.0,
        min_delay: float = 2.0,
        max_delay: float = 4.0,
    ) -> None:
        self.keywords = list(keywords or DEFAULT_KEYWORDS)
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=15.0, pool=10.0),
            headers={
                "Referer": REFERER,
                "Origin": "http://www.caac.gov.cn",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
        )
        self._last_request = 0.0
        self.request_count = 0

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- 底层请求 -------------------------------------------------------

    def _pace(self) -> None:
        """礼貌间隔，避免被统一检索平台限流/封禁。"""
        import random

        gap = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.time() - self._last_request
        if elapsed < gap:
            time.sleep(gap - elapsed)

    def _query(self, keyword: str, page: int, days: int) -> dict:
        self._pace()
        payload = {
            "siteCode": SITE_CODE,
            "tab": "all",
            "qt": keyword,
            "page": str(page),
            "pageSize": str(PAGE_SIZE),
        }
        if days and days > 0:
            payload["timeOption"] = "1"
            payload["days"] = str(days)

        # 必须用 form 编码并显式声明 Content-Type：httpx 的 content= 不会自动加
        # application/x-www-form-urlencoded，服务端会把 siteCode 读成 null 并报
        # "不存在的站点[null]"。用 data= 让它按表单编码发送。
        resp = self._client.post(
            SEARCH_API,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self._last_request = time.time()
        self.request_count += 1

        if resp.status_code != 200:
            raise RuntimeError(f"search HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("ok"):
            code = data.get("code")
            msg = data.get("msg") or ""
            if code == -101:
                raise RuntimeError(f"IP banned by so-gov: {msg}")
            raise RuntimeError(f"search rejected: code={code} msg={msg}")
        return data

    # ---- 对外接口 -------------------------------------------------------

    def fetch_keyword(self, keyword: str, days: int, max_pages: int = MAX_PAGE) -> list[SearchHit]:
        """按关键词翻页抓取，遇到空页/重复页即停。"""
        hits: list[SearchHit] = []
        seen_first: set[str] = set()

        for page in range(1, max_pages + 1):
            try:
                data = self._query(keyword, page, days)
            except Exception as exc:  # noqa: BLE001 —— 单关键词失败不拖垮整轮
                logger.warning(f"[so-gov] keyword={keyword} page={page} failed: {exc}")
                break

            docs = data.get("resultDocs") or []
            if not docs:
                break

            first_url = ((docs[0].get("data") or {}).get("url") or "")
            if page > 1 and first_url in seen_first:
                # 超过 maxPage 后服务端会回到第 1 页，说明已到上限
                logger.info(f"[so-gov] keyword={keyword} hit maxPage at page={page}, stop")
                break
            if first_url:
                seen_first.add(first_url)

            for item in docs:
                raw = item.get("data") or {}
                url = (raw.get("url") or "").strip()
                if not url:
                    continue
                doc_date = (raw.get("docDate") or "").strip()
                if not _valid_date(doc_date):
                    continue
                hits.append(
                    SearchHit(
                        title=(raw.get("titleO") or "").strip(),
                        url=url,
                        doc_date=doc_date,
                        site_name=((raw.get("siteLabel") or {}).get("value") or "").strip(),
                        file_type=(raw.get("fileType") or "").strip(),
                    )
                )

            if len(docs) < PAGE_SIZE:
                break

        return hits

    def fetch_recent(self, days: int, keywords: Optional[Iterable[str]] = None) -> list[SearchHit]:
        """多关键词并集，按 URL 去重。"""
        kws = list(keywords or self.keywords)
        merged: dict[str, SearchHit] = {}

        for idx, kw in enumerate(kws, 1):
            got = self.fetch_keyword(kw, days=days)
            new = 0
            for hit in got:
                if hit.url not in merged:
                    merged[hit.url] = hit
                    new += 1
            logger.info(
                f"[so-gov] {idx}/{len(kws)} kw={kw}: hits={len(got)} new={new} total={len(merged)}"
            )

        logger.info(
            f"[so-gov] done: {len(merged)} unique documents, {self.request_count} requests"
        )
        return list(merged.values())
