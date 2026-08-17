"""Collect public YouTube video metadata into a review CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv


DEFAULT_HANDLE = "Bodeumofficial"
DEFAULT_OUTPUT = Path("data/reviews/bodeum_youtube_metadata.csv")
API_BASE = "https://www.googleapis.com/youtube/v3"
METADATA_FIELDS = [
    "video_id", "title", "description", "published_at", "channel_id",
    "channel_title", "duration", "definition", "caption", "licensed_content",
    "privacy_status", "view_count", "like_count", "comment_count", "tags",
    "thumbnail_url", "playlist_id", "playlist_title", "fetched_at",
]
CSV_FIELDS = METADATA_FIELDS + [
    "classification", "matched_keywords", "classification_reason", "review_status",
    "review_reason",
]

EXCLUDE_KEYWORDS = [
    "#shorts", "shorts", "쇼츠", "광고", "협찬", "공동구매", "공구",
    "이벤트", "브이로그", "일상", "예능", "먹방", "챌린지", "개스트쇼",
]
TRAINING_KEYWORDS = [
    "훈련", "교육", "행동교정", "행동 교정", "입질", "짖음", "분리불안",
    "분리 불안", "공격성", "산책", "리드줄", "사회화", "배변", "기다려",
    "호출", "리콜", "하우스", "켄넬", "크레이트", "노즈워크", "터그",
]
STRONG_TITLE_KEYWORDS = [
    "퍼피교육", "퍼피 교육", "주니어교육", "주니어 교육", "훈련법", "교육법",
    "행동교정", "행동 교정", "문제행동", "문제 행동", "배변훈련", "배변 훈련",
    "분리불안", "분리 불안", "입질", "공격성", "리콜",
]
SOLUTION_EXPRESSIONS = ["해결", "고치는 법", "훈련하는 방법", "교육하는 방법"]
PLAYLIST_CANDIDATE_KEYWORDS = [
    "퍼피교육", "퍼피 교육", "주니어교육", "주니어 교육",
]
PLAYLIST_EXCLUDE_KEYWORDS = ["개스트쇼", "예능", "shorts", "쇼츠"]
THUMBNAIL_PRIORITY = ("maxres", "standard", "high", "medium", "default")
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_BOILERPLATE_MARKERS = (
    "copyright", "all rights reserved", "무단 전재", "무단전재", "재배포 금지",
    "구독과 좋아요", "구독, 좋아요", "비즈니스 문의", "광고 문의", "협찬 문의",
    "공식 홈페이지", "official website",
)


class ConfigurationError(RuntimeError):
    """Raised when required local configuration is absent."""


class YouTubeAPIError(RuntimeError):
    """Raised for a sanitized YouTube API failure."""


class YouTubeAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def get(self, resource: str, **params: Any) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "key": self.api_key})
        request = urllib.request.Request(f"{API_BASE}/{resource}?{query}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            detail = ""
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                    detail = payload.get("error", {}).get("message", "")
                except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                    pass
            detail = detail.replace(self.api_key, "[REDACTED]")
            suffix = f": {detail}" if detail else ""
            raise YouTubeAPIError(f"YouTube API 요청 실패 ({resource}){suffix}") from None


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수를 입력하세요")
    return number


def chunks(values: list[str], size: int = 50) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def iso8601_duration_to_seconds(value: str) -> int:
    match = _DURATION_RE.fullmatch(value or "")
    if not match:
        raise ValueError(f"지원하지 않는 ISO 8601 duration: {value}")
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def find_channel(api: Any, handle: str) -> tuple[str, str]:
    response = api.get("channels", part="contentDetails", forHandle=handle)
    items = response.get("items") or []
    if not items:
        raise YouTubeAPIError(f"채널 handle을 찾을 수 없습니다: {handle}")
    try:
        return items[0]["id"], items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except KeyError:
        raise YouTubeAPIError("채널의 업로드 플레이리스트를 찾을 수 없습니다") from None


def find_uploads_playlist(api: Any, handle: str) -> str:
    return find_channel(api, handle)[1]


def collect_video_ids(api: Any, playlist_id: str, max_videos: int | None = None) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "part": "contentDetails", "playlistId": playlist_id, "maxResults": 50
        }
        if page_token:
            params["pageToken"] = page_token
        response = api.get("playlistItems", **params)
        for item in response.get("items") or []:
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                ids.append(video_id)
                if max_videos is not None and len(ids) >= max_videos:
                    return ids
        page_token = response.get("nextPageToken")
        if not page_token:
            return ids


def fetch_videos(api: Any, video_ids: list[str]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for batch in chunks(video_ids):
        response = api.get(
            "videos", part="snippet,contentDetails,status,statistics", id=",".join(batch)
        )
        videos.extend(response.get("items") or [])
    return videos


def fetch_playlist_memberships(
    api: Any, channel_id: str, selected_video_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Return public playlist memberships for only the selected videos."""
    playlists: list[tuple[str, str]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "part": "snippet", "channelId": channel_id, "maxResults": 50
        }
        if page_token:
            params["pageToken"] = page_token
        response = api.get("playlists", **params)
        for item in response.get("items") or []:
            playlist_id = item.get("id")
            if playlist_id:
                playlists.append((playlist_id, item.get("snippet", {}).get("title", "")))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    selected = set(selected_video_ids)
    memberships: dict[str, list[dict[str, str]]] = {video_id: [] for video_id in selected}
    for playlist_id, playlist_title in playlists:
        page_token = None
        while True:
            params = {
                "part": "contentDetails", "playlistId": playlist_id, "maxResults": 50
            }
            if page_token:
                params["pageToken"] = page_token
            response = api.get("playlistItems", **params)
            for item in response.get("items") or []:
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id in selected:
                    memberships[video_id].append(
                        {"id": playlist_id, "title": playlist_title}
                    )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return memberships


def classification_description(description: str) -> str:
    """Remove common footer/promotion/hashtag lines before classification."""
    kept: list[str] = []
    for line in description.splitlines():
        stripped = line.strip()
        folded = stripped.casefold()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if "http://" in folded or "https://" in folded:
            continue
        if any(marker in folded for marker in _BOILERPLATE_MARKERS):
            continue
        kept.append(stripped)
    return "\n".join(kept)


def _source_matches(source: str, text: str, keywords: list[str]) -> list[str]:
    folded = text.casefold()
    return [f"{source}:{keyword}" for keyword in keywords if keyword.casefold() in folded]


def classify(
    title: str,
    description: str,
    duration: int | None = None,
    playlist_titles: list[str] | None = None,
) -> tuple[str, list[str], str]:
    cleaned_description = classification_description(description)
    playlist_titles = playlist_titles or []
    excluded = list(dict.fromkeys(
        _source_matches("title", title, EXCLUDE_KEYWORDS)
        + _source_matches("description", cleaned_description, EXCLUDE_KEYWORDS)
        + [
            f"playlist:{keyword}"
            for playlist_title in playlist_titles
            for keyword in PLAYLIST_EXCLUDE_KEYWORDS
            if keyword.casefold() in playlist_title.casefold()
        ]
    ))
    title_evidence = list(dict.fromkeys(
        _source_matches("title", title, STRONG_TITLE_KEYWORDS)
        + _source_matches("title", title, SOLUTION_EXPRESSIONS)
    ))
    playlist_evidence = list(dict.fromkeys(
        f"playlist:{keyword}"
        for playlist_title in playlist_titles
        for keyword in PLAYLIST_CANDIDATE_KEYWORDS
        if keyword.casefold() in playlist_title.casefold()
    ))
    description_evidence = _source_matches("description", cleaned_description, TRAINING_KEYWORDS)
    if duration is not None and duration <= 60:
        return "EXCLUDE", ["duration:60초 이하"], "초기 RAG 제외: 영상 길이 60초 이하"
    if excluded:
        return "EXCLUDE", excluded, f"제외 키워드 일치: {', '.join(excluded)}"
    candidate_evidence = title_evidence + playlist_evidence
    if candidate_evidence and (duration is None or duration >= 180):
        return "CANDIDATE", candidate_evidence, f"강한 후보 근거: {', '.join(candidate_evidence)}"
    review_evidence = candidate_evidence + description_evidence
    if candidate_evidence and duration is not None and duration < 180:
        return "REVIEW", review_evidence, "후보 근거가 있으나 영상 길이 180초 미만"
    if description_evidence:
        return "REVIEW", description_evidence, "설명 키워드만 일치하여 사람 검토 필요"
    return "REVIEW", [], "명시적 후보 근거 없음"


def normalize_video(
    item: dict[str, Any],
    fetched_at: str,
    memberships: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    status = item.get("status") or {}
    statistics = item.get("statistics") or {}
    tags = snippet.get("tags") or []
    memberships = memberships or []
    duration = iso8601_duration_to_seconds(details.get("duration", "PT0S"))
    classification, matched, reason = classify(
        snippet.get("title", ""), snippet.get("description", ""), duration,
        [membership["title"] for membership in memberships],
    )
    thumbnails = snippet.get("thumbnails") or {}
    thumbnail_url = next(
        (thumbnails[name].get("url", "") for name in THUMBNAIL_PRIORITY if thumbnails.get(name)), ""
    )
    return {
        "video_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "published_at": snippet.get("publishedAt", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "duration": duration,
        "definition": details.get("definition", ""),
        "caption": details.get("caption", ""),
        "licensed_content": details.get("licensedContent", ""),
        "privacy_status": status.get("privacyStatus", ""),
        "view_count": statistics.get("viewCount", ""),
        "like_count": statistics.get("likeCount", ""),
        "comment_count": statistics.get("commentCount", ""),
        "tags": json.dumps(tags, ensure_ascii=False),
        "thumbnail_url": thumbnail_url,
        "playlist_id": json.dumps([entry["id"] for entry in memberships], ensure_ascii=False),
        "playlist_title": json.dumps([entry["title"] for entry in memberships], ensure_ascii=False),
        "fetched_at": fetched_at,
        "classification": classification,
        "matched_keywords": json.dumps(matched, ensure_ascii=False),
        "classification_reason": reason,
        "review_status": "PENDING",
        "review_reason": "",
    }


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run(api: Any, handle: str, output: Path, max_videos: int | None = None) -> int:
    channel_id, playlist_id = find_channel(api, handle)
    video_ids = collect_video_ids(api, playlist_id, max_videos)
    memberships = fetch_playlist_memberships(api, channel_id, video_ids)
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = [
        normalize_video(item, fetched_at, memberships.get(item.get("id", ""), []))
        for item in fetch_videos(api, video_ids)
    ]
    write_csv(rows, output)
    print(f"수집 ID: {len(video_ids):,}개 / CSV 기록: {len(rows):,}개")
    print(f"출력: {output}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-videos", type=positive_int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError("YOUTUBE_API_KEY가 없습니다. .env에 설정하세요.")
    handle = os.getenv("YOUTUBE_CHANNEL_HANDLE", DEFAULT_HANDLE).strip() or DEFAULT_HANDLE
    run(YouTubeAPI(api_key), handle, args.output, args.max_videos)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigurationError, YouTubeAPIError) as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from None
