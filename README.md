# 국내 여행지 추천 프로그램

여행 날짜를 입력하면 제공받은 OpenAI 호환 LLM API가 국내 여행지를 JSON으로 추천합니다. 추천 지역으로 Kakao Local API에서 음식점 5곳을 검색한 뒤, 두 결과를 활용해 Markdown 여행 리포트를 생성합니다. Python 3.10 이상에서 추가 패키지 없이 실행됩니다.

## API 키 설정

사용 중인 LLM 제공자의 **OpenAI 호환 키**와 [Kakao Developers](https://developers.kakao.com/)의 **REST API 키**가 필요합니다. LLM 호출 주소는 제공받은 `https://copa.codyssey.kr/v1/chat/completions`, 모델 기본값은 `gpt-5-mini`입니다. 카카오는 앱을 만든 뒤 **카카오맵 > 사용 설정**에서 상태를 **ON**으로 바꾸고, **앱 > 플랫폼 키**에서 REST API 키를 복사하세요.

프로젝트의 `.env` 파일을 열어 아래처럼 **등호 뒤에 실제 키를 한 번만** 입력하세요. `.env.example`은 작성 형식을 보여 주는 예시입니다.

```dotenv
LLM_API_KEY=발급받은_virtual_key
KAKAO_REST_API_KEY=발급받은_REST_API_키
LLM_MODEL=gpt-5-mini
```

프로그램은 시작할 때 `.env`를 자동으로 읽으므로 재실행 때마다 키를 입력할 필요가 없습니다. 이미 설정된 환경변수가 있으면 그 값이 `.env`보다 우선합니다. `.env`는 `.gitignore`에 등록되어 있지만, 키를 README, 로그, 결과 파일에 입력하거나 제출하지 마세요.

환경변수만 쓰고 싶다면 현재 터미널 세션에서 다음처럼 설정할 수도 있습니다.

macOS/Linux:

```bash
export LLM_API_KEY="발급받은_virtual_key"
export KAKAO_REST_API_KEY="발급받은_REST_API_키"
```

Windows PowerShell:

```powershell
$env:LLM_API_KEY="발급받은_virtual_key"
$env:KAKAO_REST_API_KEY="발급받은_REST_API_키"
```

키를 설정 파일이나 환경변수에 분리하면 키 교체 때 코드를 수정할 필요가 없습니다. 과금 및 쿼터가 있는 API이므로 키를 공개 저장소에 올리지 마세요. 제공자가 다른 모델명을 안내하면 `.env`의 `LLM_MODEL` 주석을 해제해 변경할 수 있습니다.

## 실행

```bash
python3 travel_planner.py -date "2026-10-15"
```

Windows에서는 `python` 명령을 사용할 수 있습니다. 날짜는 실제 존재하는 `YYYY-MM-DD`여야 합니다. 실행 중 3단계 진행 로그가 출력되고, 완료 시 파일 경로를 안내합니다.

## 결과 확인

`results/YYYY-MM-DD_raw.json`에는 날짜, 1차 추천 JSON, 맛집 목록, 오류 목록이 담깁니다. `results/YYYY-MM-DD_travel_plan.md`에는 추천 지역·이유·계절적 날씨·행사 후보·맛집·오전/오후/저녁 일정·오류 요약이 담깁니다. 실행 검증에 사용한 `2026-10-15` 결과 파일도 제출물에 포함합니다. 같은 날짜로 재실행하면 해당 날짜 파일을 갱신합니다.

날씨는 일반적 계절 정보이고 실시간 예보가 아닙니다. 행사 후보의 개최 여부와 식당 영업 정보는 방문 전에 확인하세요.

## API 흐름과 오류 처리

LLM 제공자에는 `model`, `messages`를 JSON 본문에 넣고 Bearer 인증 헤더와 함께 `POST` 요청을 보냅니다. 응답의 `choices[0].message.content`를 JSON으로 파싱하고 `recommended_city`, `weather`, `events`, `reason`의 타입을 검증합니다. 실패하면 JSON만 다시 출력하도록 요청하는 재시도를 **1회** 합니다. 이후 `recommended_city`를 Kakao Local의 검색어에 넣어 인증 헤더를 담은 `GET` 요청을 보냅니다. `GET`은 조회 조건을 URL 쿼리에, `POST`는 생성 입력을 본문에 담는 차이가 있습니다.

키가 없으면 API 호출 전에 종료합니다. 장소 검색이 0건이거나 인증(401/403), 쿼터(429), 네트워크, 응답 파싱 오류가 발생하면 `errors`에 요약하고 맛집을 `데이터 없음`으로 표시한 채 리포트를 계속 생성합니다. 추천 JSON을 두 번 검증하지 못하면 종료합니다. 리포트 API가 실패하면 필수 섹션을 갖춘 기본 Markdown을 저장하고 오류를 기록합니다. 오류에는 키나 API 응답 원문을 저장하지 않습니다.

응답 형식 참고: [OpenAI Chat Completions](https://developers.openai.com/api/reference/cli/resources/chat), [Kakao Local 키워드 검색](https://developers.kakao.com/docs/ko/local/dev-guide).
