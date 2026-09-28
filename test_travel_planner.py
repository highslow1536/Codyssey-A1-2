import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import travel_planner as app


RECOMMENDATION = {
    "recommended_city": "강릉",
    "weather": "가을에는 선선합니다.",
    "events": ["가을 행사 후보"],
    "reason": "바다를 보기 좋습니다. 산책하기에도 좋습니다.",
}


def response(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


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
                patch.object(app, "generate_report", return_value="대체 장소가 포함된 리포트"), \
                patch.dict(os.environ, {"LLM_API_KEY": "dummy-llm", "KAKAO_REST_API_KEY": "dummy-kakao"}):
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, "RESULTS_DIR", Path(tmp)):
                self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
                raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))

        self.assertEqual(searcher.city, "강릉")
        self.assertEqual(raw["restaurants"][0]["name"], "대체 장소")

    def test_recommendation_retries_invalid_json_once(self):
        with patch.object(app, "llm_text", side_effect=["잘못된 JSON", json.dumps(RECOMMENDATION)]) as model:
            self.assertEqual(app.recommend("dummy", "2026-10-15"), RECOMMENDATION)
        self.assertEqual(model.call_count, 2)

    def test_recommendation_accepts_json_code_block(self):
        wrapped = "```json\n" + json.dumps(RECOMMENDATION, ensure_ascii=False) + "\n```"
        self.assertEqual(app.parse_recommendation_text(wrapped), RECOMMENDATION)

    def test_recommendation_normalizes_single_event_string(self):
        value = {**RECOMMENDATION, "events": "가을 행사 후보"}
        self.assertEqual(app.validate_recommendation(value)["events"], ["가을 행사 후보"])

    def test_success_creates_both_files_and_passes_city_to_kakao(self):
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
            return response("# 여행\n## 추천 지역\n강릉\n## 추천 이유\n좋음\n## 날씨 요약\n선선함\n## 행사 / 축제\n후보\n## 맛집 추천\n가상 식당\n## 1일 일정 제안\n오전, 오후, 저녁")

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("LLM_API_KEY=dummy-llm\nKAKAO_REST_API_KEY=dummy-kakao\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.object(app, "ENV_FILE", env_path), \
                    patch.object(app, "RESULTS_DIR", Path(tmp)), patch.object(app, "call_json", side_effect=fake_call):
                self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
                raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))
                report = (Path(tmp) / "2026-10-15_travel_plan.md").read_text(encoding="utf-8")

        self.assertEqual(raw["recommendation"], RECOMMENDATION)
        self.assertEqual(raw["restaurants"][0]["lat"], 37.7)
        self.assertEqual(raw["errors"], [])
        self.assertIn("가상 식당", report)
        self.assertEqual(parse_qs(urlsplit(calls[1][0]).query)["query"], ["강릉 맛집"])
        self.assertEqual([call[1] for call in calls], ["POST", "GET", "POST"])
        self.assertEqual(calls[0][0], "https://copa.codyssey.kr/v1/chat/completions")
        self.assertEqual(calls[0][2]["model"], "gpt-5-mini")
        self.assertEqual(calls[0][2]["messages"][0]["role"], "user")
        self.assertEqual(calls[0][3]["Authorization"], "Bearer dummy-llm")

    def test_environment_variable_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text('LLM_API_KEY="file-key"\n', encoding="utf-8")
            with patch.dict(os.environ, {"LLM_API_KEY": "session-key"}, clear=True), \
                    patch.object(app, "ENV_FILE", env_path):
                app.load_dotenv()
                self.assertEqual(os.environ["LLM_API_KEY"], "session-key")

    def test_place_error_still_generates_report_with_no_data(self):
        post_count = 0

        def fake_call(url, *, method, headers, body=None):
            nonlocal post_count
            if method == "GET":
                raise app.APIError("AUTH_ERROR", "HTTP 401")
            post_count += 1
            if post_count == 1:
                return response(json.dumps(RECOMMENDATION, ensure_ascii=False))
            return response("# 여행\n## 추천 지역\n강릉\n## 추천 이유\n좋음\n## 날씨 요약\n선선함\n## 행사 / 축제\n후보\n## 맛집 추천\n데이터 없음\n## 1일 일정 제안\n오전, 오후, 저녁")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "LLM_API_KEY": "dummy-llm", "KAKAO_REST_API_KEY": "dummy-kakao",
        }), patch.object(app, "RESULTS_DIR", Path(tmp)), patch.object(app, "call_json", side_effect=fake_call):
            self.assertEqual(app.main(["-date", "2026-10-15"]), 0)
            raw = json.loads((Path(tmp) / "2026-10-15_raw.json").read_text(encoding="utf-8"))
            report = (Path(tmp) / "2026-10-15_travel_plan.md").read_text(encoding="utf-8")

        self.assertEqual(raw["restaurants"], [])
        self.assertEqual(raw["errors"][0]["type"], "AUTH_ERROR")
        self.assertIn("데이터 없음", report)
        self.assertIn("HTTP 401", report)
        self.assertNotIn("dummy-kakao", report)


if __name__ == "__main__":
    unittest.main()
