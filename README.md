# 국내 여행지 추천 프로그램

여행 날짜 하나를 입력하면 **LLM으로 국내 도시 2~3곳 추천 → 도시별 Kakao Local 맛집 검색 → LLM으로 지역별 여행 리포트 작성**을 수행하는 Python CLI입니다. OpenAI 호환 API의 `gpt-5-mini`와 Kakao Local API를 사용하며, Python 3.10 이상에서 별도 패키지 설치 없이 실행됩니다. 같은 날짜의 정상 결과가 저장돼 있으면 API 호출 없이 재사용합니다.

> **실제 실행 결과:** `2026-10-15` → **경주·속초(설악산)·전주**, 도시별 맛집 **5곳씩 총 15곳**, 오류 **0건**
>
> [원본 데이터 JSON](results/2026-10-15_raw.json) · [최종 여행 리포트 Markdown](results/2026-10-15_travel_plan.md)

## 미션 요구사항 확인

| PDF 요구사항 | 구현 및 확인 위치 |
| --- | --- |
| `argparse` CLI, 필수 `-date`, 날짜 검증 | [`travel_planner.py`](travel_planner.py)의 `main`, `parse_date` |
| LLM의 날씨·행사·추천 이유를 JSON으로 구조화 | `recommend`, `validate_recommendation`; 실제 값은 [원본 JSON](results/2026-10-15_raw.json)의 `recommendation.recommended_cities` |
| 추천 지역으로 국내 맛집 검색 | `PlaceSearcher` 인터페이스와 `KakaoPlaceSearcher`; 실제 Kakao 검색 결과는 원본 JSON의 `restaurants_by_city` |
| 지도 API 교체와 검색어 보정 | `PlaceSearcher` 구현 교체, `normalize_city_for_search`로 괄호·부연 설명 제거 및 지역 토큰 선택 |
| LLM으로 최종 Markdown 리포트 생성 | `generate_report`; [실제 리포트](results/2026-10-15_travel_plan.md)에 필수 7개 섹션 포함 |
| 장소 검색 실패·0건, JSON 파싱 실패 등 처리 | `errors` 기록, 맛집 `데이터 없음` 처리, 추천 JSON 재요청 1회 |
| 결과 저장 | `results/YYYY-MM-DD_raw.json`, `results/YYYY-MM-DD_travel_plan.md` |
| API 키 분리 | `.env` 또는 환경변수 사용; `.env`는 Git 제외, [예시 파일](.env.example) 제공 |
| **보너스 1: 복수 지역 추천** | `recommended_cities` 객체 2~3개 검증 → 지역마다 장소 검색 → 리포트의 도시별 소제목 |
| **보너스 2: 결과 캐싱** | 유효한 같은 날짜 결과를 API 호출 없이 재사용; `--refresh`로 강제 갱신 |

## 1. API 키 설정

다음 두 키가 필요합니다.

1. 사용 중인 LLM 제공자의 **OpenAI 호환 키**. 호출 주소는 `https://copa.codyssey.kr/v1/chat/completions`, 기본 모델은 `gpt-5-mini`입니다. Anthropic 호환 키로는 이 주소를 호출할 수 없습니다.
2. [Kakao Developers](https://developers.kakao.com/)의 **REST API 키**. 앱을 만든 뒤 **카카오맵 → 사용 설정 → 상태 ON**으로 설정하고 **앱 → 플랫폼 키 → REST API 키**에서 확인합니다.

저장소를 복제한 뒤 `.env.example`을 `.env`로 복사하고, `.env`의 등호 뒤에 실제 키를 입력하세요.

```bash
git clone https://github.com/highslow1536/Codyssey-A1-2.git
cd Codyssey-A1-2
cp .env.example .env
```

`.env` 내용:

```dotenv
LLM_API_KEY=발급받은_OpenAI_호환_키
KAKAO_REST_API_KEY=발급받은_Kakao_REST_API_키
LLM_MODEL=gpt-5-mini
```

프로그램은 실행 시 `.env`를 자동으로 읽습니다. 이미 설정된 환경변수가 있으면 그 값이 우선합니다. `.env`는 [`.gitignore`](.gitignore)에 등록돼 있어 저장소에 포함되지 않습니다. **실제 키를 코드·README·로그·결과 파일에 넣지 마세요.** 키가 누락되면 API 호출 전에 설정 방법을 안내하고 종료합니다.

환경변수로 직접 설정하려면 다음 명령을 사용할 수도 있습니다.

macOS/Linux:

```bash
export LLM_API_KEY="발급받은_OpenAI_호환_키"
export KAKAO_REST_API_KEY="발급받은_REST_API_키"
```

Windows PowerShell:

```powershell
$env:LLM_API_KEY="발급받은_OpenAI_호환_키"
$env:KAKAO_REST_API_KEY="발급받은_REST_API_키"
```

키를 설정 파일이나 환경변수에 분리하면 키를 교체할 때 코드를 수정하지 않아도 되고, 공개 저장소에 키가 노출되는 사고를 줄일 수 있습니다. `LLM_MODEL`은 선택 항목이며 기본값도 `gpt-5-mini`입니다.

## 2. 실행

```bash
python3 travel_planner.py -date "2026-10-15"
```

Windows PowerShell에서는 `Copy-Item .env.example .env`와 `python travel_planner.py -date "2026-10-15"`를 사용할 수 있습니다. `-date`는 필수이며 실제 존재하는 `YYYY-MM-DD` 형식이어야 합니다. 잘못된 날짜는 사용법을 출력하고 종료합니다.

저장된 결과를 무시하고 새로 생성하려면 `python3 travel_planner.py -date "2026-10-15" --refresh`를 실행합니다. 첫 실행에는 3단계 진행 로그와 저장 경로가 출력되고, 캐시 적중 시에는 `캐시 사용`과 기존 파일 경로가 출력됩니다.

## 3. 결과 확인

| 파일 | 내용 |
| --- | --- |
| [`results/2026-10-15_raw.json`](results/2026-10-15_raw.json) | 날짜, `recommendation.recommended_cities`(도시별 날씨·행사·이유), `restaurants_by_city`(도시별 장소 목록), `errors` 배열, 키가 아닌 캐시 설정 정보 |
| [`results/2026-10-15_travel_plan.md`](results/2026-10-15_travel_plan.md) | 각 도시의 추천 이유·날씨·행사/축제·맛집·오전/오후/저녁 일정, 오류 요약 |

다른 날짜를 입력하면 같은 형식으로 `results/YYYY-MM-DD_raw.json`과 `results/YYYY-MM-DD_travel_plan.md`를 생성합니다. 위 두 파일은 **실제 API 실행 결과**이며 제출물에 포함돼 있습니다. 같은 날짜를 다시 실행하면 파일을 재사용하고 API를 호출하지 않습니다.

날씨는 일반적인 계절 정보이고 실시간 예보가 아닙니다. 행사/축제는 후보이므로 개최 여부와 식당 영업 정보는 방문 전에 확인해야 합니다. 미션은 정보의 실시간 정확도보다 API 데이터의 구조화와 연결을 평가합니다.

## API 요청과 데이터 연결

1. **LLM 추천:** `POST /v1/chat/completions` 요청에 `model`·`messages`를 JSON 본문으로, API 키를 Bearer 헤더로 전달합니다. 응답을 `recommended_cities` 배열로 파싱하고 **서로 다른 지역 2~3개**와 각 지역의 `city`, `weather`, `events`, `reason`을 검증합니다. `events`가 문자열 하나면 길이 1의 배열로 정규화합니다.
2. **Kakao 맛집 검색:** 각 지역의 `city`를 정규화한 뒤 `"지역명 맛집"` 검색어로 연결합니다. Kakao Local 키워드 검색 API에 **도시마다 한 번씩 `GET` 요청**을 보내고, 상위 5곳을 이름·주소·분류·URL·경위도로 정리합니다. 한 도시에서 검색이 실패해도 나머지 도시를 계속 검색합니다.
3. **최종 리포트:** 추천 JSON과 `restaurants_by_city`를 LLM에 다시 전달해 Markdown을 작성합니다. 이유·날씨·행사·맛집·일정을 **도시별 소제목**으로 나누고 오류 요약을 덧붙입니다.

`POST`는 생성에 필요한 데이터를 요청 본문에 담고, `GET`은 조회 조건을 URL 쿼리로 전달합니다. 이 프로그램은 두 방식의 응답을 다음 API 입력으로 연결합니다.

### 지도 API 교체 지점과 도시명 검색어

`PlaceSearcher.search_restaurants(city) -> list[dict]`가 지도 API 인터페이스입니다. 현재 `KakaoPlaceSearcher`가 Kakao 호출·응답 변환을 맡고, `main`은 `PlaceSearcher`만 사용합니다. 다른 지도 API를 쓰려면 같은 메서드를 구현하는 클래스를 만들고 **`make_place_searcher` 한 곳**에서 해당 제공자의 키를 확인해 새 구현을 반환하면 됩니다. 반환 항목은 `name`, `address`, `category`, `url`, `lng`, `lat`의 공통 형식을 유지해야 리포트 코드 수정 없이 교체됩니다. 새 제공자의 인증 방식은 해당 구현에 둡니다.

검색 직전 `normalize_city_for_search`가 괄호 속 설명을 제거하고 쉼표·슬래시 등 뒤의 부연 문구를 제외합니다. 그다음 지역 토큰을 골라 `강원도 강릉시 (경포 일대)`는 `강원도 강릉시 맛집`, 실제 결과의 `속초(설악산)`은 `속초 맛집`으로 검색합니다. 추천 JSON의 원래 지역명은 보존하고 검색어에만 보정값을 사용합니다. 모호한 지명까지 완전히 해소하는 지오코딩은 적용하지 않았습니다.

### 같은 날짜 결과 캐싱

날짜 파싱과 키 설정 직후, 첫 API 호출 전에 `results/YYYY-MM-DD_raw.json`을 확인합니다. 원본 JSON에 **해당 날짜·현재 모델·LLM 주소·지도 제공자**가 일치하며, 2~3개 도시별 데이터가 유효하고 `errors`가 비어 있으면 API 호출을 건너뜁니다. 리포트 파일도 유효하면 그대로 반환하고, 리포트가 없거나 손상됐으면 원본 데이터로 기본 형식의 리포트를 다시 저장합니다. 실제로 같은 날짜를 연속 실행했을 때 두 번째 실행은 `캐시 사용`을 출력하고 API를 호출하지 않았습니다.

원본 JSON이 없거나 손상됐거나 이전 단일 지역 형식이거나 오류가 기록된 결과면 API로 새로 생성합니다. 읽기·저장 권한 오류는 파일 경로를 알리고 종료합니다. 캐시는 자동 만료되지 않으므로 여행 정보의 최신성이 필요하면 `--refresh`를 사용하세요. 캐시 설정 정보에는 API 키를 넣지 않습니다.

## 오류 처리

| 상황 | 동작 |
| --- | --- |
| 날짜 형식 오류 / 키 미설정 | API 호출 전 종료하고 사용법 또는 키 설정 안내 출력 |
| LLM 추천 JSON 파싱·필수 필드 검증 실패 | JSON 출력 프롬프트로 **1회만 재요청**; 또 실패하면 종료 |
| Kakao 검색 0건 / 인증·쿼터·네트워크·응답 오류 | 해당 도시의 `restaurants: []`와 도시명이 포함된 오류를 저장하고 나머지 도시 검색 및 리포트 생성 계속 진행; 해당 도시 맛집은 `데이터 없음` |
| 최종 리포트 API 실패 / 섹션 누락 | 오류를 기록하고 필수 섹션을 갖춘 기본 Markdown 저장 |

HTTP 401/403은 인증, 429는 쿼터, 연결 실패는 네트워크 오류로 분류합니다. 오류 목록은 원본 JSON의 `errors`와 리포트의 **오류 요약**에서 확인할 수 있습니다. 키나 API 오류 응답 원문은 저장하지 않습니다.

운영 중 HTTP 401/403이 나오면 키 종류와 Kakao Developers의 앱·카카오맵 사용 설정을 확인하세요. 결과 저장 시 `PermissionError`가 발생하면 `results/`의 쓰기 권한과 파일 소유자를 확인한 뒤 다시 실행하세요(예: macOS/Linux의 `ls -ld results`).

## 검증

```bash
python3 -m unittest -v test_travel_planner.py
```

자동 테스트 **12개**는 2~3개 지역 스키마, 지역별 검색·오류 분리, `.env` 우선순위, 검색어 정규화, 지도 제공자 교체, 캐시 적중·손상 파일 무효화·`--refresh` 등을 확인합니다. 실제 API로 `2026-10-15`를 실행해 **3개 지역·맛집 15곳·오류 0건**을 확인했고, 두 번째 실행에서 캐시 사용을 확인했습니다.

API 사양: [OpenAI Chat Completions](https://developers.openai.com/api/reference/cli/resources/chat), [Kakao Local 키워드 검색](https://developers.kakao.com/docs/ko/local/dev-guide).
