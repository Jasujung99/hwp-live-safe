# 후속 후보 정리: safe의 경계

이번 PR은 로컬 수동 릴리스 probe의 **native 검증 순서**만
[native_release_gate.py](../scripts/native_release_gate.py)로 승격한다.

- 호출자 Python/MCP 2.x 환경을 사용하며 개인 경로나 인터프리터를 고정하지 않는다.
- 임시 빈 프로필 디렉터리를 사용한다. 프로필 값을 읽거나 삽입하지 않는다.
- 새 문서 생성, read → preview → 명시적 확인 → apply, 제한 Undo,
  수동 변경 후 stale preview/Undo 거부를 검사한다.
- 기존 창 자동 선택과 foreground 입력은 포함하지 않는다. 문서 저장·닫기도 하지 않는다.
- 입력은 합성 제목과 2×2 표뿐이다. 실제 문서와 수동 입력을 눈으로 확인해야 한다.
- 취소/실패 시 자동으로 더 편집하거나 사용자 문서를 정리하지 않는다.

## 검증 증거

로컬 자동 회귀 **45 passed**, fake stdio MCP **15 tools** 확인, 공개 파일 검사,
wheel/sdist 빌드와 패키지 검사 통과. 게이트 전용 5개 테스트는 실제 service와
FakeHwpBackend로 순서·권한 범위·취소를 확인했다. 이번 PR 작업 중 수동 실기는
실행하지 않았으며 fake 성공을 한/글 화면 검증으로 대신하지 않는다.

## hwpctl과의 관계

hwpctl의 패키지·입출력 / 문서 모델 / 구성·조판 / 검증이라는 4계층은 safe에 새
작성 엔진을 연결하는 약속이 아니다. 이 스크립트는 **검증 하네스**이고 런타임 API는
그대로다. 세션·문서·revision·Undo·잠금은 다른 엔진과 공유하지 않는다.
safe의 제공 기능 기준은 기존 main이며, 이 PR의 추가는 도구나 런타임 변경이 아니다.
