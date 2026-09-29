import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import travel_planner as app


RECOMMENDATION = {
    "recommended_cities": [
        {"city": "강릉", "weather": "가을에는 선선합니다.", "events": ["가을 행사 후보"],
         "reason": "바다를 보기 좋습니다. 산책하기에도 좋습니다."},
        {"city": "경주", "weather": "가을에는 온화합니다.", "events": ["문화 행사 후보"],
         "reason": "유적을 보기 좋습니다. 산책하기에도 좋습니다."},
    ],
}


def response(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def report_text(empty_city=None):
    sections = ["# 여행", "## 추천 지역\n- 강릉\n- 경주"]
    for heading in ("추천 이유", "날씨 요약", "행사 / 축제", "맛집 추천", "1일 일정 제안"):
        second = "데이터 없음" if heading == "맛집 추천" and empty_city == "경주" else "경주 내용"
        sections.append(f"## {heading}\n### 강릉\n강릉 내용\n### 경주\n{second}")
    return "\n".join(sections)


class TravelPlannerTests(unittest.TestCase):
    def test_city_search_keyword_normalization(self):
        self.assertEqual(app.normalize_city_for_search("강원도 강릉시 (경포 일대)"), "강원도 강릉시")
        self.assertEqual(app.normalize_city_for_search("경주(경상북도), 가을 여행"), "경주")
        self.assertEqual(app.normalize_city_for_search("서울특별시 종로구 / 도보 여행"), "서울특별시 종로구")

    def test_kakao_request_uses_normalized_city(self):
        with patch.object(app, "call_json", return_value={"documents": []}) as api:
            self.assertEqual(app.KakaoPlaceSearcher("dummy").search_restaurants("강원도 강릉시 (경포 일대)"), [])
        self.assertEqual(parse_qs(urlsplit(api.call_args.args[0]).query)["query"], ["강원도 강릉시 맛집"])

    def test_place_searcher_can_be_replaced_without_changing_report_flow(self):
        class AlternatePlaceSearcher:
            def search_restaurants(self, city):
                self.city = city
                return [{"name": "대체 장소", "address": "가상 주소", "category": "음식점",
                         "url": "", "lng": None, "lat": None}]

        searcher = AlternatePlaceSearcher()
        with patch.object(app, "make_place_searcher", return_value=searcher), \
                patch.object(app, "recommend", return_value=RECOMMENDATION), \
                patch.object(app, "generate_report", return_value=report_text()), \
                patch.dict(os.environ, {"LLM_API_KEY": "dummy-llm", "KAKAO_REST_API_KEY": "dummy-kakao"}):
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, "RESULTS_DIR", Path(tmp)):
                self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
                raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))

        self.assertEqual(searcher.city, "경주")
        self.assertEqual([group["city"] for group in raw["restaurants_by_city"]], ["강릉", "경주"])
        self.assertEqual(raw["restaurants_by_city"][0]["restaurants"][0]["name"], "대체 장소")

    def test_recommendation_retries_invalid_json_once(self):
        with patch.object(app, "llm_text", side_effect=["잘못된 JSON", json.dumps(RECOMMENDATION)]) as model:
            self.assertEqual(app.recommend("dummy", "2026-10-15"), RECOMMENDATION)
        self.assertEqual(model.call_count, 2)

    def test_recommendation_accepts_json_code_block(self):
        wrapped = "```json\n" + json.dumps(RECOMMENDATION, ensure_ascii=False) + "\n```"
        self.assertEqual(app.parse_recommendation_text(wrapped), RECOMMENDATION)

    def test_recommendation_normalizes_single_event_string(self):
        value = {"recommended_cities": [{**RECOMMENDATION["recommended_cities"][0], "events": "가을 행사 후보"},
                                      RECOMMENDATION["recommended_cities"][1]]}
        self.assertEqual(app.validate_recommendation(value)["recommended_cities"][0]["events"], ["가을 행사 후보"])

    def test_recommendation_requires_two_distinct_cities(self):
        with self.assertRaises(ValueError):
            app.validate_recommendation({"recommended_cities": RECOMMENDATION["recommended_cities"][:1]})
        with self.assertRaises(ValueError):
            app.validate_recommendation({"recommended_cities": [RECOMMENDATION["recommended_cities"][0]] * 2})

    def test_success_creates_regional_results_and_reuses_cache(self):
        calls = []

        def fake_call(url, *, method, headers, body=None):
            calls.append((url, method, body, headers))
            if method == "GET":
                return {"documents": [{
                    "place_name": "가상 식당", "road_address_name": "강원 강릉시 가상로 1",
                    "category_name": "음식점", "place_url": "https://place.map.kakao.com/example",
                    "x": "128.9", "y": "37.7",
                }]}
            if len([call for call in calls if call[1] == "POST"]) == 1:
                return response(json.dumps(RECOMMENDATION, ensure_ascii=False))
            return response(report_text())

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("LLM_API_KEY=dummy-llm\nKAKAO_REST_API_KEY=dummy-kakao\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.object(app, "ENV_FILE", env_path), \
                    patch.object(app, "RESULTS_DIR", Path(tmp)), patch.object(app, "call_json", side_effect=fake_call):
                self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
                raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))
                report = (Path(tmp) / "2026-10-15_travel_plan.md").read_text(encoding="utf-8")
                with patch.object(app, "call_json", side_effect=AssertionError("cache hit must skip APIs")):
                    self.assertEqual(app.main(["-date", "2026-10-15"]), 0)

        self.assertEqual(raw["recommendation"], RECOMMENDATION)
        self.assertEqual([group["city"] for group in raw["restaurants_by_city"]], ["강릉", "경주"])
        self.assertEqual(raw["restaurants_by_city"][0]["restaurants"][0]["lat"], 37.7)
        self.assertEqual(raw["errors"], [])
        self.assertIn("### 강릉", report)
        self.assertIn("### 경주", report)
        self.assertEqual([parse_qs(urlsplit(call[0]).query)["query"][0] for call in calls if call[1] == "GET"],
                         ["강릉 맛집", "경주 맛집"])
        self.assertEqual([call[1] for call in calls], ["POST", "GET", "GET", "POST"])
        self.assertEqual(calls[0][0], "https://copa.codyssey.kr/v1/chat/completions")
        self.assertEqual(calls[0][2]["model"], "gpt-5-mini")
        self.assertEqual(calls[0][2]["messages"][0]["role"], "user")
        self.assertEqual(calls[0][3]["Authorization"], "Bearer dummy-llm")

    def test_refresh_rebuilds_results_and_invalid_legacy_cache_is_ignored(self):
        class Searcher:
            def __init__(self):
                self.calls = []

            def search_restaurants(self, city):
                self.calls.append(city)
                return [{"name": city + " 식당", "address": "가상 주소", "category": "음식점",
                         "url": "", "lng": None, "lat": None}]

        searcher = Searcher()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "LLM_API_KEY": "dummy-llm", "KAKAO_REST_API_KEY": "dummy-kakao",
        }), patch.object(app, "RESULTS_DIR", Path(tmp)), \
                patch.object(app, "make_place_searcher", return_value=searcher), \
                patch.object(app, "recommend", return_value=RECOMMENDATION) as recommend, \
                patch.object(app, "generate_report", return_value=report_text()) as report:
            raw_path = Path(tmp) / "2026-10-15_raw.json"
            report_path = Path(tmp) / "2026-10-15_travel_plan.md"
            raw_path.write_text(json.dumps({"date": "2026-10-15", "recommendation": {
                "recommended_city": "경주"}}), encoding="utf-8")
            report_path.write_text("이전 형식", encoding="utf-8")
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            self.assertEqual(recommend.call_count, 1)
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            self.assertEqual(recommend.call_count, 1)
            self.assertEqual(report.call_count, 1)
            report_path.unlink()
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            self.assertEqual(recommend.call_count, 1)
            self.assertEqual(report.call_count, 1)
            self.assertIn("강릉 식당", report_path.read_text(encoding="utf-8"))
            self.assertEqual(app.main(["-date", "2026-10-15", "--refresh"]), 0)
            self.assertEqual(recommend.call_count, 2)
            self.assertEqual(report.call_count, 2)
            self.assertEqual(searcher.calls, ["강릉", "경주", "강릉", "경주"])
            raw_path.write_text("{broken json", encoding="utf-8")
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            self.assertEqual(recommend.call_count, 3)

    def test_environment_variable_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text('LLM_API_KEY="file-key"\n', encoding="utf-8")
            with patch.dict(os.environ, {"LLM_API_KEY": "session-key"}, clear=True), \
                    patch.object(app, "ENV_FILE", env_path):
                app.load_dotenv()
                self.assertEqual(os.environ["LLM_API_KEY"], "session-key")

    def test_place_error_is_recorded_per_city_and_others_continue(self):
        post_count = 0

        def fake_call(url, *, method, headers, body=None):
            nonlocal post_count
            if method == "GET" and "경주" in parse_qs(urlsplit(url).query)["query"][0]:
                raise app.APIError("AUTH_ERROR", "HTTP 401")
            if method == "GET":
                return {"documents": [{"place_name": "가상 식당", "address_name": "강릉시 가상로", "x": "128", "y": "37"}]}
            post_count += 1
            if post_count == 1:
                return response(json.dumps(RECOMMENDATION, ensure_ascii=False))
            return response(report_text(empty_city="경주"))

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "LLM_API_KEY": "dummy-llm", "KAKAO_REST_API_KEY": "dummy-kakao",
        }), patch.object(app, "RESULTS_DIR", Path(tmp)), patch.object(app, "call_json", side_effect=fake_call):
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))
            report = (Path(tmp) / "2026-10-15_travel_plan.md").read_text(encoding="utf-8")

        self.assertEqual(len(raw["restaurants_by_city"][0]["restaurants"]), 1)
        self.assertEqual(raw["restaurants_by_city"][1]["restaurants"], [])
        self.assertEqual(raw["errors"][0]["city"], "경주")
        self.assertEqual(raw["errors"][0]["type"], "AUTH_ERROR")
        self.assertIn("데이터 없음", report)
        self.assertIn("HTTP 401", report)
        self.assertNotIn("dummy-kakao", report)

    def test_report_missing_city_restaurants_is_rejected_cleanly(self):
        groups = [{"city": "강릉", "restaurants": [{"name": "가상 식당"}]},
                  {"city": "경주", "restaurants": []}]
        text = report_text(empty_city="경주").replace("## 맛집 추천\n### 강릉\n강릉 내용\n### 경주\n데이터 없음",
                                                 "## 맛집 추천\n### 강릉\n강릉 내용")
        with patch.object(app, "llm_text", return_value=text):
            with self.assertRaises(app.APIError) as caught:
                app.generate_report("dummy", "2026-10-15", RECOMMENDATION, groups, [])
        self.assertEqual(caught.exception.kind, "PARSE_ERROR")


if __name__ == "__main__":
    unittest.main()
