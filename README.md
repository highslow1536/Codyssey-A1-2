# 국내 여행지 추천 프로그램

여행 날짜 하나를 입력하면 **LLM 여행지 추천 → Kakao Local 맛집 검색 → LLM 여행 리포트 작성**을 차례로 수행하는 Python CLI입니다. OpenAI 호환 API의 `gpt-5-mini`와 Kakao Local API를 사용하며, Python 3.10 이상에서 별도 패키지 설치 없이 실행됩니다.

> **실제 실행 결과:** `2026-10-15` → **경주** 추천, 맛집 **5곳** 검색, 오류 **0건**
>
> [원본 데이터 JSON](results/2026-10-15_raw.json) · [최종 여행 리포트 Markdown](results/2026-10-15_travel_plan.md)

## 미션 요구사항 확인

| PDF 필수 조건 | 구현 및 확인 위치 |
| --- | --- |
| `argparse` CLI, 필수 `-date`, 날짜 검증 | [`travel_planner.py`](travel_planner.py)의 `main`, `parse_date` |
| LLM의 날씨·행사·추천 이유를 JSON으로 구조화 | `recommend`, `validate_recommendation`; 실제 값은 [원본 JSON](results/2026-10-15_raw.json)의 `recommendation` |
| 추천 지역으로 국내 맛집 검색 | `PlaceSearcher` 인터페이스와 `KakaoPlaceSearcher`; 실제 Kakao 검색 결과 5곳은 원본 JSON의 `restaurants` |
| 지도 API 교체와 검색어 보정 | `PlaceSearcher` 구현 교체, `normalize_city_for_search`로 괄호·부연 설명 제거 및 지역 토큰 선택 |
| LLM으로 최종 Markdown 리포트 생성 | `generate_report`; [실제 리포트](results/2026-10-15_travel_plan.md)에 필수 7개 섹션 포함 |
| 장소 검색 실패·0건, JSON 파싱 실패 등 처리 | `errors` 기록, 맛집 `데이터 없음` 처리, 추천 JSON 재요청 1회 |
| 결과 저장 | `results/YYYY-MM-DD_raw.json`, `results/YYYY-MM-DD_travel_plan.md` |
| API 키 분리 | `.env` 또는 환경변수 사용; `.env`는 Git 제외, [예시 파일](.env.example) 제공 |

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

실제 실행 시 추천 지역 **경주**, 맛집 **5곳**을 찾았고 마지막에 두 결과 파일의 저장 경로가 출력됐습니다.

## 3. 결과 확인

| 파일 | 내용 |
| --- | --- |
| [`results/2026-10-15_raw.json`](results/2026-10-15_raw.json) | 날짜, `recommendation`(지역·날씨·행사·이유), `restaurants`(이름·주소·분류·URL·좌표), `errors` 배열 |
| [`results/2026-10-15_travel_plan.md`](results/2026-10-15_travel_plan.md) | 추천 지역·이유, 날씨, 행사/축제, 맛집, 오전/오후/저녁 일정, 오류 요약 |

다른 날짜를 입력하면 같은 형식으로 `results/YYYY-MM-DD_raw.json`과 `results/YYYY-MM-DD_travel_plan.md`를 생성합니다. 현재는 같은 날짜로 재실행하면 API를 다시 호출하고 해당 파일을 갱신합니다. 위 두 파일은 **실제 API 실행 결과**이며 제출물에 포함돼 있습니다.

날씨는 일반적인 계절 정보이고 실시간 예보가 아닙니다. 행사/축제는 후보이므로 개최 여부와 식당 영업 정보는 방문 전에 확인해야 합니다. 미션은 정보의 실시간 정확도보다 API 데이터의 구조화와 연결을 평가합니다.

## API 요청과 데이터 연결

1. **LLM 추천:** `POST /v1/chat/completions` 요청에 `model`·`messages`를 JSON 본문으로, API 키를 Bearer 헤더로 전달합니다. `choices[0].message.content`를 JSON으로 파싱해 `recommended_city`, `weather`, `events`, `reason`을 검증합니다. 제공자가 `events`를 문자열 하나로 반환하면 길이 1의 배열로 정규화합니다.
2. **Kakao 맛집 검색:** 추천 JSON의 `recommended_city`를 정규화한 뒤 `"지역명 맛집"` 검색어로 연결합니다. Kakao Local 키워드 검색 API에 `GET` 요청을 보내고, 응답의 상위 5곳을 이름·주소·분류·URL·경위도로 정리합니다.
3. **최종 리포트:** 추천 JSON과 맛집 목록(0건 가능)을 LLM에 다시 전달해 Markdown을 작성합니다. 필수 섹션을 검사하고 오류 요약을 덧붙입니다.

`POST`는 생성에 필요한 데이터를 요청 본문에 담고, `GET`은 조회 조건을 URL 쿼리로 전달합니다. 이 프로그램은 두 방식의 응답을 다음 API 입력으로 연결합니다.

### 지도 API 교체 지점과 도시명 검색어

`PlaceSearcher.search_restaurants(city) -> list[dict]`가 지도 API 인터페이스입니다. 현재 `KakaoPlaceSearcher`가 Kakao 호출·응답 변환을 맡고, `main`은 `PlaceSearcher`만 사용합니다. 다른 지도 API를 쓰려면 같은 메서드를 구현하는 클래스를 만들고 **`make_place_searcher` 한 곳**에서 해당 제공자의 키를 확인해 새 구현을 반환하면 됩니다. 반환 항목은 `name`, `address`, `category`, `url`, `lng`, `lat`의 공통 형식을 유지해야 리포트 코드 수정 없이 교체됩니다. 새 제공자의 인증 방식은 해당 구현에 둡니다.

검색 직전 `normalize_city_for_search`가 괄호 속 설명을 제거하고 쉼표·슬래시 등 뒤의 부연 문구를 제외합니다. 그다음 지역 토큰을 골라 `강원도 강릉시 (경포 일대)`는 `강원도 강릉시 맛집`, `경주(경상북도), 가을 여행`은 `경주 맛집`으로 검색합니다. 추천 JSON의 원래 지역명은 보존하고 검색어에만 보정값을 사용합니다. 모호한 지명까지 완전히 해소하는 지오코딩은 적용하지 않았습니다.

### 같은 날짜 결과 캐싱 설계

**현재 캐싱은 구현하지 않았습니다.** 적용한다면 `main`에서 날짜 파싱과 키 설정을 마친 직후, 첫 LLM 호출 전에 `results/YYYY-MM-DD_raw.json`과 `results/YYYY-MM-DD_travel_plan.md`의 존재 여부를 확인합니다. 캐시 키는 날짜·LLM 모델·LLM 제공자·지도 제공자로 구성하고, 원본 JSON에 이 실행 설정을 기록해 현재 설정과 일치할 때만 재사용합니다. 두 파일이 모두 있고 JSON 스키마가 유효하며 오류가 없는 결과만 적중으로 간주합니다. 생성 후 **24시간**이 지나면 만료시키고, `--refresh` 옵션을 추가해 강제 재생성을 허용하는 방식입니다. 날씨·행사·식당 정보의 변경 가능성 때문에 무기한 재사용하지 않습니다.

예외 처리 예시: 파일 하나가 없거나 JSON이 손상됐거나 수정 시각이 미래로 기록됐으면 캐시를 무효로 보고 새로 생성합니다. 파일 읽기 권한이 없을 때는 오류 경로를 알려 주고 종료해 권한 문제를 사용자가 고칠 수 있게 합니다. 이 동작도 캐시를 구현할 때 함께 추가할 설계입니다.

## 오류 처리

| 상황 | 동작 |
| --- | --- |
| 날짜 형식 오류 / 키 미설정 | API 호출 전 종료하고 사용법 또는 키 설정 안내 출력 |
| LLM 추천 JSON 파싱·필수 필드 검증 실패 | JSON 출력 프롬프트로 **1회만 재요청**; 또 실패하면 종료 |
| Kakao 검색 0건 / 인증·쿼터·네트워크·응답 오류 | `restaurants: []`와 오류 요약을 저장하고 리포트 생성 계속 진행; 맛집은 `데이터 없음` |
| 최종 리포트 API 실패 / 섹션 누락 | 오류를 기록하고 필수 섹션을 갖춘 기본 Markdown 저장 |

HTTP 401/403은 인증, 429는 쿼터, 연결 실패는 네트워크 오류로 분류합니다. 오류 목록은 원본 JSON의 `errors`와 리포트의 **오류 요약**에서 확인할 수 있습니다. 키나 API 오류 응답 원문은 저장하지 않습니다.

운영 중 HTTP 401/403이 나오면 키 종류와 Kakao Developers의 앱·카카오맵 사용 설정을 확인하세요. 결과 저장 시 `PermissionError`가 발생하면 `results/`의 쓰기 권한과 파일 소유자를 확인한 뒤 다시 실행하세요(예: macOS/Linux의 `ls -ld results`).

## 검증

```bash
python3 -m unittest -v test_travel_planner.py
```

자동 테스트 **9개**는 추천 JSON 재요청, `.env` 우선순위, 정상 저장, Kakao 인증 실패 시 리포트 계속 생성, 실제 요청 검색어 정규화, 지도 검색 구현 교체 등을 확인합니다. 기존 `2026-10-15` 파일은 실제 API로 실행해 경주·맛집 5곳·오류 0건을 확인한 결과이며, 저장된 결과 파일에 API 키가 없는 것도 검사했습니다.

API 사양: [OpenAI Chat Completions](https://developers.openai.com/api/reference/cli/resources/chat), [Kakao Local 키워드 검색](https://developers.kakao.com/docs/ko/local/dev-guide).
