# REVIEW: GDELT GKG 폴백 (2026-11-08, Claude)

## 판정: 조건부 보류 (코드 구조 OK, 지표 호환성 미해결)

## 직접 확인
- diff 읽음: news_monitor.fetch()가 DOC 실패/3일 초과 지연 시 gdelt_gkg로 폴백. evaluate·스키마 불변, source 필드 추가.
- `python -m unittest discover -s tests` 28개 통과 (venv에 pytest 없음, 설치하지 않음).
- 실제 `python gdelt_gkg.py --backfill 1`: 첫 실행은 UnicodeDecodeError(실데이터에 비UTF-8 바이트)로 실패 →
  `errors="replace"`로 수정(gdelt_gkg.py:97) 후 성공. 하루 96파일, 264.8MiB, 19초.
  결과 2026-11-07: count=2, total=64211. 이 회귀 테스트는 아직 없음.

## 문제
- GKG 매칭(테마+URL만)은 DOC(본문 검색)보다 훨씬 좁다: 하루 2건 vs DOC 일 ~244건(만 건당 0.3 vs 평소 ~15).
  DOC 과거 series와 섞으면 기준선이 맞지 않는다. GKG 단독 28일 기준선을 새로 쌓거나 매칭 방식을 바꿔야 한다.
- 28일 백필 추정: 약 9분·7.4GB(실측 1일 기준 ×28). Actions에서 가능한 수준이나 실행당 3일 상한이라 여러 번 나눠야 함.
## 후속
1. 비UTF-8 회귀 테스트 추가. 2. 매칭 방식/기준선 정책 결정(사용자). 3. 결정 후 커밋(미커밋 상태).
