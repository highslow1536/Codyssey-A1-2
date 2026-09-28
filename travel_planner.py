"""OpenAI 호환 LLM과 Kakao Local로 국내 여행 리포트를 만든다."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
from typing import Protocol
from urllib import error, parse, request


LLM_URL = "https://copa.codyssey.kr/v1/chat/completions"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DEFAULT_MODEL = "gpt-5-mini"
ENV_FILE = Path(__file__).resolve().parent / ".env"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

RECOMMENDATION_KEYS = ("recommended_city", "weather", "events", "reason")


class APIError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def load_dotenv() -> None:
    """프로젝트의 .env를 읽되 이미 설정된 환경변수는 유지한다."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in {"LLM_API_KEY", "KAKAO_REST_API_KEY", "LLM_MODEL"}:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def parse_date(value: str) -> str:
    try:
        if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 실제 존재하는 YYYY-MM-DD 형식이어야 합니다.") from exc
    return value


def call_json(url: str, *, method: str, headers: dict[str, str], body: dict | None = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=45) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        kind = "AUTH_ERROR" if exc.code in (401, 403) else "QUOTA_ERROR" if exc.code == 429 else "HTTP_ERROR"
        raise APIError(kind, f"HTTP {exc.code}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise APIError("NETWORK_ERROR", "네트워크 연결 또는 시간 초과") from exc
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise APIError("PARSE_ERROR", "API 응답 JSON 파싱 실패") from exc
    if not isinstance(result, dict):
        raise APIError("PARSE_ERROR", "API 응답 형식이 올바르지 않습니다")
    return result


def llm_text(api_key: str, prompt: str) -> str:
    payload = {"model": os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
               "messages": [{"role": "user", "content": prompt}]}
    result = call_json(
        LLM_URL, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        body=payload,
    )
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise APIError("PARSE_ERROR", "LLM 응답에 choices 목록이 없습니다")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise APIError("PARSE_ERROR", "LLM 텍스트 응답이 없습니다")
    return content.strip()


def validate_recommendation(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("추천 결과가 객체가 아닙니다")
    for key in ("recommended_city", "weather", "reason"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"{key} 필드가 비어 있거나 문자열이 아닙니다")
    events = value.get("events")
    if isinstance(events, str) and events.strip():
        events = [events.strip()]
    if not isinstance(events, list) or not 1 <= len(events) <= 3 or any(
        not isinstance(event, str) or not event.strip() for event in events
    ):
        raise ValueError("events는 비어 있지 않은 문자열 1~3개여야 합니다")
    return {**{key: value[key] for key in RECOMMENDATION_KEYS if key != "events"}, "events": events}


def parse_recommendation_text(text: str) -> dict:
    """모델이 코드 블록으로 감싼 경우에도 JSON 객체를 추출한다."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    return validate_recommendation(value)


def recommend(api_key: str, travel_date: str) -> dict:
    prompt = (
        f"{travel_date} 국내 하루 여행 도시 1곳을 추천하세요. JSON 객체만 출력: "
        "recommended_city(도시명), weather(계절적 일반 날씨), "
        "events(확인이 필요한 행사 후보 문자열 배열, 예: [\"가을 행사\"]), "
        "reason(추천 이유 2~4문장). "
        "실제 예보나 확정되지 않은 행사 일정은 단정하지 말고 각 문장을 짧게 쓰세요."
    )
    for attempt in range(2):
        text = llm_text(api_key, prompt)
        try:
            return parse_recommendation_text(text)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt:
                raise APIError("PARSE_ERROR", "추천 JSON을 2회 파싱/검증하지 못했습니다") from exc
            prompt += " 이전 응답은 파싱/검증에 실패했습니다. 필수 키와 타입을 지켜 JSON만 다시 출력하세요."
    raise AssertionError("도달할 수 없음")


def normalize_city_for_search(city: str) -> str:
    """LLM의 설명을 덜어내고 검색에 쓸 행정구역 지명을 고른다."""
    clean = re.sub(r"\([^)]*\)|（[^）]*）", " ", city)
    clean = re.split(r"[,，/·:：\n]", clean, maxsplit=1)[0]
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", clean)
    regions = [token for token in tokens if token.endswith(("시", "군", "구", "도"))]
    if len(regions) >= 2 and regions[0].endswith(("시", "도")):
        return " ".join(regions[:2])
    if regions:
        return regions[0]
    if tokens:
        return tokens[0]
    raise APIError("PARSE_ERROR", "검색할 지역명이 비어 있습니다")


class PlaceSearcher(Protocol):
    """지도 제공자별 구현이 반환해야 하는 공통 장소 형식."""

    def search_restaurants(self, city: str) -> list[dict]: ...


class KakaoPlaceSearcher:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search_restaurants(self, city: str) -> list[dict]:
        query = parse.urlencode({"query": f"{normalize_city_for_search(city)} 맛집", "size": 5, "category_group_code": "FD6"})
        result = call_json(
            f"{KAKAO_URL}?{query}", method="GET",
            headers={"Authorization": f"KakaoAK {self.api_key}"},
        )
        documents = result.get("documents")
        if not isinstance(documents, list):
            raise APIError("PARSE_ERROR", "장소 검색 응답에 documents 목록이 없습니다")
        places = []
        for item in documents:
            if not isinstance(item, dict) or not item.get("place_name"):
                continue
            try:
                lng, lat = float(item["x"]), float(item["y"])
            except (KeyError, TypeError, ValueError):
                lng = lat = None
            places.append({
                "name": str(item["place_name"]),
                "address": str(item.get("road_address_name") or item.get("address_name") or "주소 정보 없음"),
                "category": str(item.get("category_name") or ""),
                "url": str(item.get("place_url") or ""),
                "lng": lng, "lat": lat,
            })
        return places


def make_place_searcher() -> PlaceSearcher:
    """지도 제공자를 선택하고 해당 제공자의 인증값을 확인한다."""
    kakao_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not kakao_key:
        raise APIError("CONFIG_ERROR", "API 키 미설정: KAKAO_REST_API_KEY. README의 환경변수 설정 방법을 확인하세요.")
    return KakaoPlaceSearcher(kakao_key)


def fallback_report(travel_date: str, recommendation: dict, restaurants: list[dict], errors: list[dict]) -> str:
    city = recommendation["recommended_city"]
    events = "\n".join(f"- {event}" for event in recommendation["events"])
    places = "\n".join(
        f"- {place['name']} — {place['address']}" + (f" ([지도]({place['url']}))" if place["url"] else "")
        for place in restaurants
    ) or "- 데이터 없음"
    error_lines = "\n".join(f"- {item['step']}: {item['type']} ({item['message']})" for item in errors) or "- 없음"
    return (
        f"# {travel_date} 국내 여행 추천 리포트\n\n"
        f"## 추천 지역\n{city}\n\n## 추천 이유\n{recommendation['reason']}\n\n"
        f"## 날씨 요약\n{recommendation['weather']} (계절적 일반 정보, 실제 예보 아님)\n\n"
        f"## 행사 / 축제\n{events}\n\n## 맛집 추천\n{places}\n\n"
        f"## 1일 일정 제안\n- 오전: {city} 주요 명소 둘러보기\n"
        "- 오후: 행사 및 주변 관광지 방문 (운영 여부 확인)\n"
        "- 저녁: " + (f"{restaurants[0]['name']} 방문" if restaurants else "현지 식당 탐색") + "\n\n"
        f"## 오류 요약 (errors)\n{error_lines}\n"
    )


def generate_report(api_key: str, travel_date: str, recommendation: dict, restaurants: list[dict], errors: list[dict]) -> str:
    source = {"date": travel_date, "recommendation": recommendation, "restaurants": restaurants, "errors": errors}
    prompt = (
        "다음 JSON 자료만 사용해 한국어 Markdown 국내 여행 리포트를 작성하세요. "
        "제목은 날짜가 들어간 국내 여행 추천 리포트로 하세요. "
        "반드시 ## 추천 지역, ## 추천 이유, ## 날씨 요약, ## 행사 / 축제, "
        "## 맛집 추천, ## 1일 일정 제안, ## 오류 요약 (errors) 섹션을 포함하세요. "
        "일정은 오전/오후/저녁으로 나누세요. 맛집 목록이 비었으면 정확히 '데이터 없음'이라고 쓰세요. "
        "맛집마다 장소 이름을 목록 항목으로, 주소·카테고리·URL·좌표는 하위 목록 항목으로 쓰세요. "
        "JSON에 없는 식당, 확정되지 않은 행사 일정, 실시간 예보를 만들어내지 마세요. "
        "오류가 없으면 '없음'이라고 쓰세요. 자료: " + json.dumps(source, ensure_ascii=False)
    )
    report = llm_text(api_key, prompt)
    required = ("## 추천 지역", "## 추천 이유", "## 날씨 요약", "## 행사 / 축제", "## 맛집 추천", "## 1일 일정 제안")
    if any(heading not in report for heading in required) or (not restaurants and "데이터 없음" not in report):
        raise APIError("PARSE_ERROR", "리포트의 필수 섹션이 누락되었습니다")
    # 오류 기록은 코드가 직접 덧붙여 최신 오류를 빠짐없이 보존한다.
    report = report.split("## 오류 요약", 1)[0].rstrip()
    error_lines = "\n".join(f"- {item['step']}: {item['type']} ({item['message']})" for item in errors) or "- 없음"
    return report + f"\n\n## 오류 요약 (errors)\n{error_lines}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="국내 여행지와 맛집을 추천하고 리포트를 저장합니다.")
    parser.add_argument("-date", "--date", required=True, type=parse_date, help="여행 날짜 (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    load_dotenv()
    llm_key = os.environ.get("LLM_API_KEY", "").strip()
    if not llm_key:
        parser.exit(2, "API 키 미설정: LLM_API_KEY. README의 환경변수 설정 방법을 확인하세요.\n")
    try:
        place_searcher = make_place_searcher()
    except APIError as exc:
        parser.exit(2, f"{exc}\n")

    errors: list[dict] = []
    print("[1/3] 여행지 추천 생성 중 (LLM)...")
    try:
        recommendation = recommend(llm_key, args.date)
    except APIError as exc:
        print(f"추천 생성 실패: {exc.kind} ({exc})", file=sys.stderr)
        return 1
    print(f"  추천 지역: {recommendation['recommended_city']}")

    print("[2/3] 맛집 검색 중...")
    try:
        restaurants = place_searcher.search_restaurants(recommendation["recommended_city"])
        if not restaurants:
            errors.append({"step": "place_search", "type": "EMPTY_RESULT", "message": "검색 결과 0건"})
    except APIError as exc:
        restaurants = []
        errors.append({"step": "place_search", "type": exc.kind, "message": str(exc)})
    print(f"  맛집 {len(restaurants)}곳" + (" (데이터 없음)" if not restaurants else ""))

    print("[3/3] 최종 리포트 생성 중 (LLM)...")
    try:
        report = generate_report(llm_key, args.date, recommendation, restaurants, errors)
    except APIError as exc:
        errors.append({"step": "report", "type": exc.kind, "message": str(exc)})
        report = fallback_report(args.date, recommendation, restaurants, errors)
        print("  리포트 API 실패: 기본 형식으로 저장합니다.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.date}_raw.json"
    report_path = RESULTS_DIR / f"{args.date}_travel_plan.md"
    raw_path.write_text(json.dumps({
        "date": args.date, "recommendation": recommendation,
        "restaurants": restaurants, "errors": errors,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    print(f"완료! 원본 데이터: {raw_path}\n여행 리포트: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
